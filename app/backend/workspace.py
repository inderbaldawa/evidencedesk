"""Owner-isolated company/project organization and longitudinal evidence views."""
import copy
import json
import uuid
from pathlib import Path
from typing import Literal
from fastapi import HTTPException, Request, UploadFile, File, Form
from pydantic import BaseModel, Field
from .store import now, new_review, public_review
from .policy_packs import get_policy_pack, list_policy_packs
from .document_ocr import ocr_capability
from .documents import ingest_pdf, coverage, MAX_BYTES
from .versioning import compare_documents, review_history

DocumentKind = Literal['policy','questionnaire','contract','inventory','operational_record','audit_report','other']
class CompanyBody(BaseModel):
    name: str = Field(min_length=1,max_length=100)
    type: Literal['buyer','vendor','subprocessor','auditor','partner','other'] = 'vendor'
    notes: str = Field(default='',max_length=2000)
class Party(BaseModel):
    company_id: str = Field(max_length=64)
    role: str = Field(default='vendor',max_length=80)
    contact: str = Field(default='',max_length=200)
class ProjectBody(BaseModel):
    name: str = Field(min_length=1,max_length=160)
    type: Literal['onboarding','renewal','ai-procurement','other'] = 'onboarding'
    description: str = Field(default='',max_length=4000)
    owner_name: str = Field(default='',max_length=100)
    status: Literal['active','paused','completed'] = 'active'
    start_date: str = Field(default='',max_length=10)
    target_date: str = Field(default='',max_length=10)
    parties: list[Party] = Field(default_factory=list,max_length=30)
    policy_pack_id: str = 'data-handling'
class DocumentBody(BaseModel):
    company_id: str | None = Field(default=None,max_length=64)
    document_kind: DocumentKind | None = None
class DemoBody(BaseModel):
    policy_pack_id: str = 'data-handling'

def pack(identity):
    try:return get_policy_pack(identity)
    except ValueError as exc:raise HTTPException(400,str(exc)) from None

def validate_links(workspace, project_id, company_id):
    project=next((p for p in workspace['projects'] if p['id']==project_id),None)
    if project_id and not project:raise HTTPException(404,'Project not found.')
    if company_id and not any(c['id']==company_id for c in workspace['companies']):raise HTTPException(404,'Company not found.')
    if project and company_id and not any(p['company_id']==company_id for p in project['parties']):
        raise HTTPException(400,'Choose a company participating in this project.')
    return project

def stamp_document(doc,company_id='',kind='other'):
    doc.update(company_id=company_id,document_kind=kind,uploaded_at=now(),document_family_id=doc['id'],version_number=1,previous_document_id=None,is_current=True)
    return doc

def summarize(review):
    result={k:review.get(k,'') for k in ('id','name','vendor','service','environment','period','policy_version','project_id','company_id','status','created_at','updated_at')}
    result.update(policy_pack_id=review.get('policy_pack_id') or 'data-handling',coverage=review.get('coverage',{}),analysis_stale=review.get('analysis',{}).get('stale',False),document_count=sum(d.get('is_current',True) for d in review.get('documents',[])),finding_count=len(review.get('findings',[])),unresolved_count=sum(f.get('reviewer',{}).get('decision')!='accepted' for f in review.get('findings',[])))
    return result

def workspace_view(store,who):
    workspace=store.workspace_get(who)
    reviews=store.list_reviews(who,limit=501)
    truncated=len(reviews)>500
    reviews=reviews[:500]
    companies={c['id']:c for c in workspace['companies']};projects={p['id']:p for p in workspace['projects']}
    docs=[]
    for review in reviews:
        for original in review.get('documents',[]):
            doc={k:v for k,v in original.items() if not k.startswith('_') and k not in ('pages','extraction','path','file_path','artifact_generation')}
            doc.setdefault('document_family_id',doc['id']);doc.setdefault('version_number',1);doc.setdefault('is_current',True)
            doc.setdefault('document_kind','other');doc.setdefault('uploaded_at',review['created_at'])
            company_id=doc.get('company_id',review.get('company_id',''))
            doc.update(review_id=review['id'],review_name=review['name'],project_id=review.get('project_id',''),project_name=projects.get(review.get('project_id'),{}).get('name','Unassigned'),company_id=company_id,company_name=companies.get(company_id,{}).get('name','Unassigned'),file_url=f"/api/reviews/{review['id']}/documents/{doc['id']}/file")
            docs.append(doc)
    return {**workspace,'truncated':truncated,'review_limit':500,'reviews':[summarize(r) for r in reviews],'documents':docs,'policy_packs':list_policy_packs(),'capabilities':{'ocr':ocr_capability(),'collaboration':False}}

def register(app, get_store, owner, owned, idle):
    @app.get('/api/workspace')
    def workspace(request:Request):return workspace_view(get_store(),owner(request))

    @app.get('/api/policy-packs')
    def packs():return {'policy_packs':list_policy_packs(),'capabilities':{'ocr':ocr_capability()}}

    @app.post('/api/companies')
    def company(body:CompanyBody,request:Request):
        who=owner(request); data={**body.model_dump(),'name':body.name.strip(),'id':uuid.uuid4().hex,'created_at':now(),'updated_at':now()}
        if not data['name']:raise HTTPException(400,'Company name is required.')
        def add(w):
            if len(w['companies'])>=100:raise HTTPException(400,'Workspace limit is 100 companies.')
            w['companies'].append(data)
        get_store().workspace_update(who,add)
        return data

    def validate_project(w,data):
        pack(data['policy_pack_id'])
        if not data['name'].strip():raise HTTPException(400,'Project name is required.')
        ids=[p['company_id'] for p in data['parties']]
        if len(set(ids))!=len(ids):raise HTTPException(400,'Each company may appear once in a project.')
        if not set(ids).issubset({c['id'] for c in w['companies']}):raise HTTPException(400,'Project contains an unknown company.')
        from datetime import date
        for key in ('start_date','target_date'):
            if data[key]:
                try:date.fromisoformat(data[key])
                except ValueError:raise HTTPException(400,'Use YYYY-MM-DD dates.') from None
        if data['start_date'] and data['target_date'] and data['target_date']<data['start_date']:raise HTTPException(400,'Target date must follow the start date.')

    @app.post('/api/projects')
    def project(body:ProjectBody,request:Request):
        who=owner(request);data={**body.model_dump(),'id':uuid.uuid4().hex,'created_at':now(),'updated_at':now()}
        def add(w):
            if len(w['projects'])>=100:raise HTTPException(400,'Workspace limit is 100 projects.')
            validate_project(w,data);w['projects'].append(data)
        get_store().workspace_update(who,add)
        return data

    @app.patch('/api/projects/{project_id}')
    async def edit_project(project_id:str,request:Request):
        who=owner(request);patch=await request.json()
        if not isinstance(patch,dict) or set(patch)-set(ProjectBody.model_fields):raise HTTPException(400,'Unknown project fields.')
        def update(w):
            existing=next((p for p in w['projects'] if p['id']==project_id),None)
            if not existing:raise HTTPException(404,'Project not found.')
            from pydantic import ValidationError
            try:data=ProjectBody(**{**existing,**patch}).model_dump()
            except ValidationError:raise HTTPException(422,'Invalid project details.') from None
            validate_project(w,data)
            removed={p['company_id'] for p in existing['parties']}-{p['company_id'] for p in data['parties']}
            if removed:raise HTTPException(400,'Keep existing parties to preserve document provenance; add new parties as needed.')
            existing.update(**data,updated_at=now());return copy.deepcopy(existing)
        return get_store().workspace_update(who,update)

    @app.get('/api/projects/{project_id}')
    def project_detail(project_id:str,request:Request):
        who=owner(request);data=workspace_view(get_store(),who)
        project=validate_links(data,project_id,'');ids={p['company_id'] for p in project['parties']}
        reviews=[r for r in data['reviews'] if r['project_id']==project_id]
        activity=[]
        for summary in reviews:
            r=get_store().get(summary['id'])
            if r and r['_owner']==who:activity.extend({**e,'review_id':r['id'],'review_name':r['name']} for e in r.get('events',[]))
        return {'project':project,'companies':[c for c in data['companies'] if c['id'] in ids],'reviews':reviews,'documents':[d for d in data['documents'] if d['project_id']==project_id],'activity':sorted(activity,key=lambda e:e['at'],reverse=True)[:200]}

    @app.patch('/api/reviews/{rid}/documents/{did}')
    def edit_document(rid:str,did:str,body:DocumentBody,request:Request):
        review=owned(rid,request,True);idle(review)
        changes=body.model_dump(exclude_none=True)
        validate_links(get_store().workspace_get(owner(request)),review.get('project_id',''),changes.get('company_id',review.get('company_id','')))
        def save(r):
            idle(r);doc=next((d for d in r['documents'] if d['id']==did),None)
            if not doc:raise HTTPException(404,'Document not found.')
            # Organization metadata applies to the family, preserving a coherent file history.
            family=doc.get('document_family_id',did)
            for item in r['documents']:
                if item.get('document_family_id',item['id'])==family:item.update(changes)
            r['events'].append({'at':now(),'type':'document_organized','message':f"Updated organization for {doc['name']}."})
        get_store().update(rid,save);return public_review(get_store().get(rid))

    @app.post('/api/reviews/{rid}/documents/{did}/versions')
    async def version(rid:str,did:str,request:Request,file:UploadFile=File(...),note:str=Form(default='',max_length=2000)):
        review=owned(rid,request,True);idle(review)
        previous=next((d for d in review['documents'] if d['id']==did),None)
        if not previous:raise HTTPException(404,'Document not found.')
        payload=await file.read(MAX_BYTES+1); filename=Path(file.filename or 'document.pdf').name
        def save(r):
            idle(r)
            if len(r['documents'])>=150:raise HTTPException(400,'Review limit is 150 documents.')
            old=next(d for d in r['documents'] if d['id']==did);family=old.get('document_family_id',did)
            siblings=[d for d in r['documents'] if d.get('document_family_id',d['id'])==family]
            if not old.get('is_current',True) or any(d.get('replacement_pending') for d in siblings):raise HTTPException(409,'Upload against the current version after its pending replacement finishes.')
            known={d['sha256']:d['id'] for d in r['documents'] if d['status']!='failed'}
            doc=ingest_pdf(filename,payload,get_store(),rid,known)
            if doc['status'] in ('failed','duplicate'):raise HTTPException(400,doc['error'])
            stamp_document(doc,old.get('company_id',r.get('company_id','')),old.get('document_kind','other'))
            doc.update(document_family_id=family,version_number=max(d.get('version_number',1) for d in siblings)+1,previous_document_id=did,is_current=False,replacement_pending=True,_replaces=did,version_note=note)
            r['documents'].append(doc);r['status']='incomplete';r['synthetic']=False
            if r.get('analysis'):r['analysis']['stale']=True
            r['events'].append({'at':now(),'type':'version_uploaded','message':f"{filename} version {doc['version_number']} received; prior evidence stays current until extraction succeeds."})
            r['coverage']=coverage(r)
        get_store().update(rid,save);return public_review(get_store().get(rid))

    @app.get('/api/reviews/{rid}/documents/{did}/compare')
    def comparison(rid:str,did:str,request:Request,against:str):return compare_documents(owned(rid,request),did,against)

    @app.get('/api/reviews/{rid}/history')
    def history(rid:str,request:Request):return review_history(owned(rid,request))

    @app.post('/api/workspace/demo')
    def demo(body:DemoBody,request:Request):
        who=owner(request);selected=pack(body.policy_pack_id);store=get_store()
        root=Path(__file__).resolve().parents[2]
        manifest=json.loads((root/'data/demo-packs/demo_manifest.json').read_text())['packs'][selected['id']]
        if not store.take_limit(who+':create',10):raise HTTPException(429,'Daily review creation limit reached.')
        buyer={**CompanyBody(name='Aster Finance (demo)',type='buyer').model_dump(),'id':uuid.uuid4().hex,'created_at':now(),'updated_at':now()}
        vendor={**CompanyBody(name=manifest['vendor'],type='vendor').model_dump(),'id':uuid.uuid4().hex,'created_at':now(),'updated_at':now()}
        project={**ProjectBody(name=manifest['project'],type='ai-procurement' if selected['id']=='ai-vendor' else 'onboarding',description='Synthetic demonstration with supplied policy, vendor claims, and operational evidence.',parties=[Party(company_id=buyer['id'],role='buyer'),Party(company_id=vendor['id'],role='vendor')],policy_pack_id=selected['id']).model_dump(),'id':uuid.uuid4().hex,'created_at':now(),'updated_at':now()}
        review=new_review(who,name=manifest['project'],project_id=project['id'],company_id=vendor['id'],policy_pack_id=selected['id'],policy_pack_version=selected['version'],**{k:manifest[k] for k in ('vendor','service','environment','period','policy_version')})
        for source in manifest['files']:
            doc=ingest_pdf(source['name'],(root/source['path']).read_bytes(),store,review['id'],{})
            stamp_document(doc,buyer['id'] if source['role']=='policy' else vendor['id'],source['role'].replace('-','_'));review['documents'].append(doc)
        def add(w):
            if len(w['companies'])>98 or len(w['projects'])>=100:raise HTTPException(400,'Workspace demo would exceed the company/project limit.')
            w['companies'].extend([buyer,vendor]);w['projects'].append(project)
        store.workspace_update(who,add)
        review['coverage']=coverage(review);review['status']='incomplete';review['events'].append({'at':now(),'type':'demo_loaded','message':'Synthetic PDFs loaded. Run analysis to generate real findings.'})
        store.put(review)
        return {'project':project,'review_id':review['id']}
