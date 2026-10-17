"""Run real pipeline; do not import expected findings into product analysis."""
import json
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.backend.store import get_store,new_review,now
from app.backend.documents import ingest_pdf,coverage
from app.backend.worker import process

def main():
    manifest=json.loads((ROOT/'data/compact/manifest.json').read_text())
    store=get_store()
    existing=store.get('local-compact')
    if existing:
        review=existing
        def repair_legacy_failure(r):
            for d in r['documents']:
                if d['status']=='failed' and d.get('pages'):d['analysis_error']=True
        store.update(review['id'],repair_legacy_failure)
    else:
        review=new_review('evaluation',name='Nimbus Support | October vendor review',**{k:v for k,v in manifest['review_scope'].items() if k in ('vendor','service','environment','period','policy_version')})
        review['id']='local-compact'
        known={}
        for source in manifest['documents']:
            doc=ingest_pdf(source['name'],(ROOT/source['path']).read_bytes(),store,review['id'],known)
            known[doc['sha256']]=doc['id']
            review['documents'].append(doc)
        review['coverage']=coverage(review);store.put(review)
    process(review['id'],store)
    review=store.get(review['id'])
    out=ROOT/'evals/compact-actual.json';out.write_text(json.dumps(review,indent=2))
    print(json.dumps({'status':review['status'],'coverage':review['coverage'],'analysis':{k:v for k,v in review['analysis'].items() if k!='reconciliation_cache'},'findings':[{k:f[k] for k in ('control_id','status','explanation')} for f in review['findings']]},indent=2))
    if review['status']=='complete':
        review['id']='sample';review['_owner']='system';review['read_only']=True
        review['analysis']['label']='Previously processed synthetic sample - real Gemini analysis'
        store.put(review);print('Published locally as read-only sample; no external publication.')

if __name__=='__main__':main()
