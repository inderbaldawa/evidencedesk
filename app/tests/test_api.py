import copy
import io
import json
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from app.backend import main,store as storage

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'ROOT',tmp_path)
    db=storage.LocalStore();monkeypatch.setattr(main,'store',db)
    with TestClient(main.app) as client:
        client.get('/api/session')
        yield client,db

def test_session_isolation_and_public_sample_immutable(client):
    c,db=client
    review=c.post('/api/reviews',json={}).json()
    assert c.get('/api/reviews/'+review['id']).status_code==200
    stranger=TestClient(main.app);stranger.get('/api/session')
    assert stranger.get('/api/reviews/'+review['id']).status_code==404
    assert stranger.get('/api/reviews/'+review['id']+'/export').status_code==404
    sample=copy.deepcopy(db.get(review['id']));sample['id']='sample';sample['_owner']='system'
    db.put(sample)
    assert stranger.get('/api/sample').json()['read_only'] is True
    assert c.post('/api/reviews/sample/analyze').status_code==403
    clone=c.post('/api/reviews/sample').json()
    assert clone['id']!='sample' and clone['read_only'] is False

def test_unreadable_upload_is_unresolved_not_missing_evidence(client):
    c,db=client
    r=c.post('/api/reviews',json={}).json()
    pdf=PdfWriter();pdf.add_blank_page(width=612,height=792);stream=io.BytesIO();pdf.write(stream)
    result=c.post(f"/api/reviews/{r['id']}/documents",files=[('files',('blank.pdf',stream.getvalue(),'application/pdf')),('files',('fake.pdf',b'not a pdf','application/pdf'))]).json()
    assert result['status']=='incomplete'
    assert result['coverage']['failed']==1 and result['findings']==[]
    # Text extraction runs durably in the worker, not the web request.
    from app.backend.documents import extract_document,coverage
    def parse(v):
        v['documents']=[extract_document(d,db) for d in v['documents']]
        v['coverage']=coverage(v)
    db.update(r['id'],parse)
    assert db.get(r['id'])['coverage']['failed']==2
    assert c.post(f"/api/reviews/{r['id']}/analyze").status_code==400

def test_decision_history_persistence_and_export(client):
    c,db=client
    r=c.post('/api/reviews',json={}).json()
    def fixture(v):
        v['status']='complete';v['findings']=[{'id':'unit-finding','control_id':'backup_location','control_name':'Backup location','status':'needs_human_review','requirement':'Unit test requirement','policy_version':'v3','explanation':'Unit test only','next_action':'Review','citations':[],'reviewer':{'decision':'unreviewed','note':'','at':None}}]
        v['_analysis_history']=[{'secret_internal':'not exposed'}]
    db.update(r['id'],fixture)
    for decision in ['clarification_requested','unresolved']:
        result=c.post(f"/api/reviews/{r['id']}/findings/unit-finding/decision",json={'decision':decision,'note':'Reviewer note'});assert result.status_code==200
    result=c.get(f"/api/reviews/{r['id']}/export?format=json").json()
    assert len(result['findings'][0]['history'])==2
    assert result['findings'][0]['reviewer']['decision']=='unresolved'
    assert '_owner' not in result and '_analysis_history' not in result
    # Reopening the store verifies durability beyond a request-local object.
    assert storage.LocalStore().get(r['id'])['findings'][0]['reviewer']['note']=='Reviewer note'
    pdf=c.get(f"/api/reviews/{r['id']}/export?format=pdf")
    assert pdf.status_code==200 and pdf.content.startswith(b'%PDF-')

def test_cross_origin_rejected_and_durable_job_claim(client):
    c,db=client
    assert c.post('/api/reviews',json={},headers={'Origin':'https://untrusted.example'}).status_code==403
    db.enqueue('review-test')
    fresh=storage.LocalStore();job=fresh.claim();assert job['review_id']=='review-test'
    assert fresh.claim() is None
    with fresh.connect() as conn:conn.execute('UPDATE jobs SET lease=0 WHERE id=?',(job['id'],))
    recovered=storage.LocalStore().claim();assert recovered['id']==job['id']
    fresh.finish(job['id']);assert fresh.claim() is None

def test_ambiguous_dispatch_does_not_mark_running_review_failed(client,monkeypatch):
    from app.backend.cloud_store import DispatchUncertain
    c,db=client
    r=c.post('/api/reviews',json={}).json()
    db.update(r['id'],lambda v:v['documents'].append({'id':'test','name':'source.pdf','status':'pending','_blob':'test-only','page_count':0}))
    def uncertain(review_id):
        db.update(review_id,lambda v:v.update(status='processing'))
        raise DispatchUncertain('test-dispatch')
    monkeypatch.setattr(db,'enqueue',uncertain)
    result=c.post(f"/api/reviews/{r['id']}/analyze")
    assert result.status_code==200 and result.json()['status']=='processing'
    assert db.get(r['id'])['status']=='processing'

def test_active_worker_edit_conflict_is_retryable(client,monkeypatch):
    from app.backend.cloud_store import ReviewLeaseLost
    c,db=client
    r=c.post('/api/reviews',json={}).json()
    def conflict(*args,**kwargs):raise ReviewLeaseLost('test lease')
    monkeypatch.setattr(db,'update',conflict)
    result=c.post(f"/api/reviews/{r['id']}/findings/test/decision",json={'decision':'unresolved'})
    assert result.status_code==409 and 'Refresh' in result.json()['detail']
