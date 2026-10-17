import copy
import json
import os
import secrets
import uuid
from pathlib import Path
from fastapi import FastAPI, Request, Response, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .store import get_store,new_review,public_review,now
from .documents import ingest_pdf,coverage,MAX_BYTES
from .report import export_pdf
from .cloud_store import ReviewLeaseLost, DispatchUncertain

app=FastAPI(title='EvidenceDesk',docs_url=None,redoc_url=None)
store=get_store()
CLOUD=os.environ.get('EVIDENCEDESK_AUTH','cookie')=='firebase'
COOKIE='evidencedesk_session'

@app.exception_handler(ReviewLeaseLost)
async def processing_conflict(request,exc):
    return JSONResponse(status_code=409,content={'detail':'Processing is finishing or retrying. Refresh the review before editing.'})

@app.middleware('http')
async def security_headers(request,call_next):
    # Same-origin check supplements authentication on mutations; no permissive CORS.
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
            # Local Vite proxy development origin is explicit, never accepted on cloud.
            if CLOUD or origin not in ('http://127.0.0.1:5173','http://localhost:5173'):
                return Response('Cross-origin request denied',status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['X-Frame-Options']='SAMEORIGIN'
    if request.url.path.startswith('/api/'):response.headers['Cache-Control']='no-store'
    return response

def owner(request):
    if CLOUD:
        token=request.headers.get('authorization','')
        if not token.startswith('Bearer '):raise HTTPException(401,'Sign in to your isolated review session.')
        try:
            import firebase_admin
            from firebase_admin import auth
            if not firebase_admin._apps:firebase_admin.initialize_app(options={'projectId':os.environ['GOOGLE_CLOUD_PROJECT']})
            claims=auth.verify_id_token(token[7:],check_revoked=True)
            return claims['uid']
        except Exception:raise HTTPException(401,'Session expired. Please sign in again.')
    value=request.cookies.get(COOKIE,'')
    if len(value)!=64 or not all(c in '0123456789abcdef' for c in value):raise HTTPException(401,'Initialize your review session first.')
    return value

def owned(review_id,request,write=False):
    review=store.get(review_id)
    if not review:raise HTTPException(404,'Review not found.')
    if review_id=='sample' and not write:return review
    if review_id=='sample':raise HTTPException(403,'The shared sample is read-only. Create your own copy.')
    if review['_owner']!=owner(request):raise HTTPException(404,'Review not found.')
    return review

def idle(review):
    if review['status'] in ('queued','processing'):raise HTTPException(409,'Wait for processing to finish before changing this review.')

@app.get('/api/health')
def health():return {'status':'ok','service':'EvidenceDesk','storage':os.environ.get('EVIDENCEDESK_STORAGE','local')}

@app.get('/api/session')
def session(request:Request,response:Response):
    if CLOUD:return {'authenticated':False,'auth_mode':'firebase','firebase_config':json.loads(os.environ.get('FIREBASE_WEB_CONFIG','{}'))}
    value=request.cookies.get(COOKIE)
    if not value or len(value)!=64:
        value=secrets.token_hex(32)
        response.set_cookie(COOKIE,value,httponly=True,samesite='strict',secure=False,max_age=86400)
    return {'authenticated':True,'auth_mode':'cookie'}

@app.get('/api/sample')
def sample():
    review=store.get('sample')
    if not review:raise HTTPException(503,'The sample review is being prepared with real Gemini analysis. Please try again shortly.')
    return public_review(review,True)

@app.post('/api/reviews/sample')
def clone_sample(request:Request):
    who=owner(request)
    original=store.get('sample')
    if not original:raise HTTPException(503,'Sample analysis is not ready yet.')
    if not store.take_limit(who+':create',10):raise HTTPException(429,'Daily review creation limit reached.')
    review=copy.deepcopy(original)
    review.update(id=uuid.uuid4().hex,_owner=who,created_at=now(),updated_at=now(),read_only=False)
    for f in review['findings']:f.update(reviewer={'decision':'unreviewed','note':'','at':None},history=[])
    store.put(review)
    return public_review(review)

class CreateReview(BaseModel):
    name:str=Field(default='Vendor evidence review',max_length=160)
    vendor:str=Field(default='Nimbus Support',max_length=100)
    service:str=Field(default='Customer Support Platform',max_length=100)
    environment:str=Field(default='production',max_length=60)
    period:str=Field(default='2026-10',max_length=60)
    policy_version:str=Field(default='v3.0',max_length=60)

@app.post('/api/reviews')
def create(body:CreateReview,request:Request):
    who=owner(request)
    if not store.take_limit(who+':create',10):raise HTTPException(429,'Daily review creation limit reached.')
    review=new_review(who,**body.model_dump());store.put(review)
    return public_review(review)

@app.get('/api/reviews/{review_id}')
def get_review(review_id:str,request:Request):return public_review(owned(review_id,request),review_id=='sample')

@app.post('/api/reviews/{review_id}/documents')
async def upload(review_id:str,request:Request,files:list[UploadFile]=File(...)):
    review=owned(review_id,request,True);idle(review)
    if len(files)>20:raise HTTPException(400,'Upload at most 20 PDFs at once.')
    if len(review['documents'])+len(files)>150:raise HTTPException(400,'Review limit is 150 documents.')
    payload=[]
    for file in files:
        data=await file.read(MAX_BYTES+1)
        payload.append((Path(file.filename or 'document.pdf').name,data))
    def add(r):
        idle(r)
        known={d['sha256']:d['id'] for d in r['documents'] if d['status'] not in ('failed','duplicate')}
        for name,data in payload:
            d=ingest_pdf(name,data,store,review_id,known);r['documents'].append(d)
            if d['status'] not in ('failed','duplicate'):known[d['sha256']]=d['id']
        r['coverage']=coverage(r)
        r['status']='incomplete'
        r['events'].append({'at':now(),'type':'uploaded','message':f'{len(payload)} documents received. Run analysis to update findings.'})
        # Retain original analysis for audit but clearly mark it stale.
        if r.get('analysis'):r['analysis']['stale']=True
    store.update(review_id,add)
    return public_review(store.get(review_id))

@app.post('/api/reviews/{review_id}/analyze')
def analyze(review_id:str,request:Request):
    review=owned(review_id,request,True);idle(review)
    if not any(d.get('_blob') and d['status'] not in ('failed','duplicate') or d.get('pages') and d.get('analysis_error') for d in review['documents']):raise HTTPException(400,'Upload at least one PDF eligible for processing.')
    if not store.take_limit(review['_owner']+':analysis',5):raise HTTPException(429,'Daily analysis limit reached for this session.')
    def queue(r):
        idle(r);r['status']='queued';r['events'].append({'at':now(),'type':'queued','message':'Analysis queued for durable processing.'})
    store.update(review_id,queue)
    try:store.enqueue(review_id)
    except DispatchUncertain:
        # A transport timeout does not prove that Cloud Run rejected the job.
        # Preserve queued/processing state; poll it instead of dispatching twice.
        current=store.get(review_id)
        return public_review(current)
    except Exception:
        store.update(review_id,lambda r:r.update(status='failed'))
        raise HTTPException(503,'Could not queue analysis. Please retry.')
    return public_review(store.get(review_id))

class Decision(BaseModel):
    decision:str
    note:str=Field(default='',max_length=4000)

@app.post('/api/reviews/{review_id}/findings/{finding_id}/decision')
def decide(review_id:str,finding_id:str,body:Decision,request:Request):
    owned(review_id,request,True)
    if body.decision not in ('accepted','clarification_requested','unresolved'):raise HTTPException(400,'Invalid reviewer decision.')
    def save(r):
        idle(r)
        f=next((f for f in r['findings'] if f['id']==finding_id),None)
        if not f:raise HTTPException(404,'Finding not found.')
        action={'decision':body.decision,'note':body.note,'at':now()}
        f['reviewer']=action;f.setdefault('history',[]).append(action)
        r['events'].append({'at':now(),'type':'reviewer_decision','message':f"{f['control_name']}: {body.decision}"})
    store.update(review_id,save)
    return public_review(store.get(review_id))

@app.get('/api/reviews/{review_id}/documents/{document_id}/file')
def document_file(review_id:str,document_id:str,request:Request):
    review=owned(review_id,request)
    doc=next((d for d in review['documents'] if d['id']==document_id),None)
    if not doc or not doc.get('_blob'):raise HTTPException(404,'Source PDF is unavailable for this document.')
    return Response(store.read_blob(doc['_blob']),media_type='application/pdf',headers={'Content-Disposition':'inline; filename="source.pdf"'})

@app.get('/api/reviews/{review_id}/export')
def export(review_id:str,request:Request,format:str='json'):
    review=public_review(owned(review_id,request),review_id=='sample')
    if format=='json':
        review['exported_at']=now()
        return Response(json.dumps(review,indent=2),media_type='application/json',headers={'Content-Disposition':'attachment; filename="evidencedesk-review.json"'})
    if format=='pdf':return Response(export_pdf(review),media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="evidencedesk-review.pdf"'})
    raise HTTPException(400,'Choose pdf or json.')

dist=Path(__file__).resolve().parents[1]/'frontend'/'dist'
if dist.exists():app.mount('/',StaticFiles(directory=dist,html=True),name='frontend')
