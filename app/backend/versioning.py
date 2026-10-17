"""Immutable evidence-version references and page-aware text comparison."""
import copy
import difflib
from fastapi import HTTPException

def document_versions(review):
    return [{k:d.get(k,1 if k=='version_number' else None) for k in ('id','name','sha256','document_family_id','version_number','company_id')} for d in review['documents'] if d.get('is_current',True) and d.get('pages')]

def snapshot(review):
    analysis=copy.deepcopy(review.get('analysis',{}));analysis.pop('reconciliation_cache',None)
    return {'id':analysis.get('snapshot_id',review['id']+'-'+analysis.get('generated_at',review['updated_at'])),'created_at':analysis.get('generated_at',review['updated_at']),'analysis':analysis,'findings':copy.deepcopy(review.get('findings',[])),'document_versions':copy.deepcopy(analysis.get('document_versions',document_versions(review))),'policy_pack_id':review.get('policy_pack_id','data-handling'),'policy_pack_version':review.get('policy_pack_version','1.0')}

def review_history(review):
    snapshots=copy.deepcopy(review.get('_analysis_history',[]))
    if review.get('findings'):
        current=snapshot(review)
        snapshots=[item for item in snapshots if item.get('id')!=current['id']]
        snapshots.append(current)
    for item in snapshots:item.get('analysis',{}).pop('reconciliation_cache',None)
    changes=[]
    if len(snapshots)>1:
        before={f['control_id']:f for f in snapshots[-2]['findings']}
        for finding in snapshots[-1]['findings']:
            old=before.get(finding['control_id'],{})
            changes.append({'control_id':finding['control_id'],'control_name':finding['control_name'],'before_status':old.get('status','not_reviewed'),'after_status':finding['status'],'decision_status':finding.get('reviewer',{}).get('decision','unreviewed')})
    return {'snapshots':snapshots,'changes':changes}

def compare_documents(review,did,against):
    docs={d['id']:d for d in review['documents']}
    before=docs.get(against);after=docs.get(did)
    if not before or not after:raise HTTPException(404,'Document not found.')
    if before['id']==after['id'] or before.get('document_family_id',before['id'])!=after.get('document_family_id',after['id']):raise HTTPException(400,'Compare two versions of the same document.')
    result={'before':{k:before.get(k,1) for k in ('id','name','version_number','sha256','document_family_id')},'after':{k:after.get(k,1) for k in ('id','name','version_number','sha256','document_family_id')}}
    if not before.get('pages') or not after.get('pages'):return {**result,'status':'pending','pages':[],'summary':{'added_lines':0,'removed_lines':0,'changed_pages':0},'message':'Run the review to extract both versions. Failed files require a readable replacement.'}
    a={p['page']:p['text'] for p in before['pages']};b={p['page']:p['text'] for p in after['pages']}
    pages=[{'page':n,'before':a.get(n,''),'after':b.get(n,''),'changed':a.get(n,'')!=b.get(n,'')} for n in sorted(set(a)|set(b))]
    delta=list(difflib.ndiff('\n'.join(a.values()).splitlines(),'\n'.join(b.values()).splitlines()))
    return {**result,'status':'ready','pages':pages,'summary':{'added_lines':sum(x.startswith('+ ') for x in delta),'removed_lines':sum(x.startswith('- ') for x in delta),'changed_pages':sum(p['changed'] for p in pages)},'message':'Extracted text comparison. A changed claim is not proof of remediation; review the evidence and reconfirm the decision.'}


def failed_latest_replacement(documents):
    latest={}
    for document in documents:
        family=document.get('document_family_id',document['id'])
        if document.get('version_number',1)>latest.get(family,{}).get('version_number',0):latest[family]=document
    return any(d.get('_replaces') and d['status']=='failed' for d in latest.values())
