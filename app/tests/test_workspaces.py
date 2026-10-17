"""Owner/version/history integration against real routes and durable local store.

Only the model transport is replaced; parsing, worker orchestration, filtering,
quote validation, snapshotting and file authorization run unchanged. No cloud.
"""
import copy
import hashlib
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen.canvas import Canvas
from app.backend import main, pipeline, store as storage, worker
from app.backend.policy_packs import list_policy_packs


class OfflineModel:
    model = 'offline-workspace-test'

    def __init__(self):
        self.usage = {'calls': 0, 'input_tokens': 0, 'output_tokens': 0, 'cost_usd': 0}

    def generate(self, **kwargs):
        self.usage['calls'] += 1
        value = json.loads(kwargs['prompt'])
        if 'documents' in value:
            scope = value['review_scope']
            return {'documents': [
                {'document_id': d['document_id'], 'context': {
                    **{k: scope[k] for k in ('vendor', 'service', 'environment', 'period')},
                    'version': scope['policy_version'], 'document_type': 'other',
                    'currency': 'current', 'scope_status': 'applicable', 'scope_reason': 'Offline test scope'},
                 'suspicious_instructions': False, 'observations': []}
                for d in value['documents']]}
        raise AssertionError('This test transport provides no policy requirement and must not reconcile.')


def pdf(text):
    output = io.BytesIO(); canvas = Canvas(output)
    canvas.drawString(40, 750, text); canvas.showPage(); canvas.save()
    return output.getvalue()


@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'ROOT', tmp_path)
    db = storage.LocalStore(); monkeypatch.setattr(main, 'store', db)
    monkeypatch.setattr(main, 'CLOUD', False)
    monkeypatch.delenv('EVIDENCEDESK_OCR_PROCESSOR', raising=False)
    monkeypatch.setattr(pipeline, 'AIClient', OfflineModel)
    with TestClient(main.app) as alice, TestClient(main.app) as bob:
        alice.get('/api/session'); bob.get('/api/session')
        yield alice, bob, db


def company(client, name='Vendor A'):
    response = client.post('/api/companies', json={'name': name, 'type': 'vendor'})
    assert response.status_code == 200, response.text
    return response.json()


def project(client, companies=(), **extra):
    response = client.post('/api/projects', json={'name': 'Review project', 'parties': [
        {'company_id': c['id'], 'role': 'vendor'} for c in companies], **extra})
    assert response.status_code == 200, response.text
    return response.json()


def review(client, **extra):
    response = client.post('/api/reviews', json=extra)
    assert response.status_code == 200, response.text
    return response.json()


def upload(client, rid, text='Original current evidence describes production records.', **metadata):
    data = pdf(text)
    response = client.post(f'/api/reviews/{rid}/documents', files={'files': ('source.pdf', data, 'application/pdf')}, data=metadata)
    assert response.status_code == 200, response.text
    return response.json()['documents'][-1], data


def replace(client, rid, did, content=None):
    content = content if content is not None else pdf('Revised evidence describes a newly approved production location.')
    response = client.post(f'/api/reviews/{rid}/documents/{did}/versions', files={'file': ('revision.pdf', content, 'application/pdf')}, data={'note': 'Updated evidence'})
    assert response.status_code == 200, response.text
    return response.json()['documents'][-1], content


def test_owner_isolation_for_projects_reviews_files_history_and_mutations(clients):
    alice, bob, db = clients
    vendor = company(alice); plan = project(alice, [vendor])
    r = review(alice, project_id=plan['id'], company_id=vendor['id'])
    doc, _ = upload(alice, r['id'])
    foreign = bob.get('/api/workspace').json()
    assert foreign['companies'] == foreign['projects'] == foreign['reviews'] == foreign['documents'] == []
    for url in [f"/api/projects/{plan['id']}", f"/api/reviews/{r['id']}",
                f"/api/reviews/{r['id']}/documents/{doc['id']}/file", f"/api/reviews/{r['id']}/history",
                f"/api/reviews/{r['id']}/documents/{doc['id']}/compare?against=unknown"]:
        assert bob.get(url).status_code == 404
    assert bob.patch(f"/api/projects/{plan['id']}", json={'name': 'Stolen'}).status_code == 404
    assert bob.patch(f"/api/reviews/{r['id']}/documents/{doc['id']}", json={'document_kind': 'policy'}).status_code == 404
    assert bob.post(f"/api/reviews/{r['id']}/documents/{doc['id']}/versions", files={'file': ('x.pdf', pdf('A foreign attempt must never change evidence.'), 'application/pdf')}).status_code == 404
    assert db.get(r['id'])['documents'][0]['sha256'] == doc['sha256']


def test_company_and_project_link_validation(clients):
    alice, bob, _ = clients
    mine, unrelated, foreign = company(alice), company(alice, 'Unrelated'), company(bob)
    assert alice.post('/api/companies', json={'name': '   '}).status_code == 400
    assert alice.post('/api/companies', json={'name': 'Name', 'type': 'invented'}).status_code == 422
    for parties in [[{'company_id': foreign['id']}], [{'company_id': mine['id']}, {'company_id': mine['id']}]]:
        assert alice.post('/api/projects', json={'name': 'Invalid', 'parties': parties}).status_code == 400
    for values in [{'start_date': '2026-02-31'}, {'start_date': '2026-10-20', 'target_date': '2026-10-01'}, {'policy_pack_id': 'unknown'}]:
        assert alice.post('/api/projects', json={'name': 'Invalid', **values}).status_code == 400
    plan = project(alice, [mine])
    assert alice.post('/api/reviews', json={'project_id': plan['id'], 'company_id': unrelated['id']}).status_code == 400
    assert alice.post('/api/reviews', json={'project_id': 'foreign-project'}).status_code == 404
    assert alice.post('/api/reviews', json={'company_id': foreign['id']}).status_code == 404
    assert alice.patch(f"/api/projects/{plan['id']}", json={'parties': []}).status_code == 400
    assert alice.patch(f"/api/projects/{plan['id']}", json={'_owner': 'attacker'}).status_code == 400


@pytest.mark.parametrize('pack_id', [p['id'] for p in list_policy_packs()])
def test_all_demo_seeds_match_manifest_scope_hashes_and_pack_controls(clients, pack_id):
    alice, bob, db = clients
    response = alice.post('/api/workspace/demo', json={'policy_pack_id': pack_id})
    assert response.status_code == 200, response.text
    seeded = response.json(); stored = db.get(seeded['review_id'])
    manifest = json.loads((Path(__file__).resolve().parents[2]/'data/demo-packs/demo_manifest.json').read_text())['packs'][pack_id]
    assert seeded['project']['policy_pack_id'] == stored['policy_pack_id'] == pack_id
    assert stored['findings'] == []
    assert {d['sha256'] for d in stored['documents']} == {d['sha256'] for d in manifest['files']}
    assert all(d['is_current'] and d['version_number'] == 1 for d in stored['documents'])
    for doc in stored['documents']:
        downloaded = alice.get(f"/api/reviews/{stored['id']}/documents/{doc['id']}/file")
        assert hashlib.sha256(downloaded.content).hexdigest() == doc['sha256']
    worker.process(stored['id'], db)
    finished = alice.get(f"/api/reviews/{stored['id']}").json()
    assert finished['coverage']['processed'] == len(manifest['files'])
    assert {f['control_id'] for f in finished['findings']} == {c['id'] for c in finished['policy_pack']['controls']}
    assert all(f['reviewer']['decision'] == 'unreviewed' for f in finished['findings'])
    assert bob.get('/api/workspace').json()['reviews'] == []


def test_workspace_metadata_and_original_download_remain_owner_scoped(clients):
    alice, _, db = clients
    vendor = company(alice); buyer = company(alice, 'Buyer'); plan = project(alice, [vendor, buyer])
    r = review(alice, project_id=plan['id'], company_id=vendor['id'])
    doc, data = upload(alice, r['id'], company_id=buyer['id'], document_kind='policy')
    listed = alice.get('/api/workspace').json()['documents'][0]
    assert listed['company_id'] == buyer['id'] and listed['project_id'] == plan['id']
    assert listed['document_kind'] == 'policy' and listed['document_family_id'] == doc['id']
    assert listed['sha256'] == hashlib.sha256(data).hexdigest() and listed['uploaded_at']
    assert not set(listed) & {'_blob', '_ocr_attempt', 'pages', 'extraction', 'path', 'file_path', 'artifact_generation'}
    assert alice.get(listed['file_url']).content == data
    assert alice.patch(f"/api/reviews/{r['id']}/documents/{doc['id']}", json={'company_id': 'unknown'}).status_code == 404
    response = alice.patch(f"/api/reviews/{r['id']}/documents/{doc['id']}", json={'company_id': vendor['id'], 'document_kind': 'inventory'})
    assert response.status_code == 200
    assert db.get(r['id'])['documents'][0]['company_id'] == vendor['id']


def test_successful_version_activation_history_hashes_and_decisions_not_inherited(clients):
    alice, _, db = clients
    r = review(alice); old, old_data = upload(alice, r['id'])
    worker.process(r['id'], db)
    first = alice.get(f"/api/reviews/{r['id']}").json()
    first_id = first['analysis']['snapshot_id']
    f = first['findings'][0]
    assert alice.post(f"/api/reviews/{r['id']}/findings/{f['id']}/decision", json={'decision': 'accepted', 'note': 'Old evidence approved'}).status_code == 200
    new, new_data = replace(alice, r['id'], old['id'])
    staged = db.get(r['id'])
    assert staged['documents'][0]['is_current'] and not staged['documents'][1]['is_current']
    assert staged['documents'][1]['replacement_pending'] and staged['analysis']['stale']
    assert alice.get(f"/api/reviews/{r['id']}/documents/{new['id']}/compare", params={'against': old['id']}).json()['status'] == 'pending'
    worker.process(r['id'], db)
    current = db.get(r['id'])
    assert not current['documents'][0]['is_current'] and current['documents'][1]['is_current']
    assert not current['documents'][1]['replacement_pending'] and current['coverage']['submitted'] == 1
    assert all(f['reviewer']['decision'] == 'unreviewed' and not f.get('history') for f in current['findings'])
    history = alice.get(f"/api/reviews/{r['id']}/history").json()
    assert len(history['snapshots']) == 2
    before, after = history['snapshots']
    assert before['id'] == first_id and after['id'] != first_id
    assert before['document_versions'][0]['id'] == old['id']
    assert before['document_versions'][0]['sha256'] == hashlib.sha256(old_data).hexdigest()
    assert after['document_versions'][0]['id'] == new['id']
    assert after['document_versions'][0]['sha256'] == hashlib.sha256(new_data).hexdigest()
    assert before['findings'][0]['reviewer']['decision'] == 'accepted'
    assert all(c['decision_status'] == 'unreviewed' for c in history['changes'])
    assert all('reconciliation_cache' not in s['analysis'] for s in history['snapshots'])
    assert alice.get(f"/api/reviews/{r['id']}/documents/{old['id']}/file").content == old_data
    compare = alice.get(f"/api/reviews/{r['id']}/documents/{new['id']}/compare", params={'against': old['id']}).json()
    assert compare['status'] == 'ready' and compare['summary']['changed_pages'] == 1
    assert 'Original current' in compare['pages'][0]['before'] and 'Revised evidence' in compare['pages'][0]['after']
    assert compare['before']['sha256'] == old['sha256']
    assert compare['after']['sha256'] == new['sha256']
    # Historical annotation must not retroactively rewrite captured company metadata.
    assert len(alice.get(f"/api/reviews/{r['id']}/export").json()['analysis_history']) == 1


def test_failed_replacement_preserves_original_and_allows_new_attempt(clients):
    alice, _, db = clients
    r = review(alice); old, old_data = upload(alice, r['id'])
    worker.process(r['id'], db)
    bad, _ = replace(alice, r['id'], old['id'], b'%PDF-malformed replacement')
    worker.process(r['id'], db)
    saved = db.get(r['id']); by_id = {d['id']: d for d in saved['documents']}
    assert by_id[old['id']]['is_current'] and by_id[old['id']]['pages']
    assert not by_id[bad['id']]['is_current'] and not by_id[bad['id']]['replacement_pending']
    assert by_id[bad['id']]['status'] == 'failed' and saved['coverage']['submitted'] == 1
    assert alice.get(f"/api/reviews/{r['id']}/documents/{old['id']}/file").content == old_data
    replacement, _ = replace(alice, r['id'], old['id'])
    assert replacement['version_number'] == 3 and replacement['previous_document_id'] == old['id']
    worker.process(r['id'], db)
    recovered = db.get(r['id'])
    assert recovered['status'] == 'complete'
    assert next(d for d in recovered['documents'] if d['id'] == replacement['id'])['is_current']


def test_duplicate_staged_or_historical_replacements_are_rejected(clients):
    alice, _, db = clients
    r = review(alice); old, old_data = upload(alice, r['id']); worker.process(r['id'], db)
    route = f"/api/reviews/{r['id']}/documents/{old['id']}/versions"
    assert alice.post(route, files={'file': ('duplicate.pdf', old_data, 'application/pdf')}).status_code == 400
    new, _ = replace(alice, r['id'], old['id'])
    assert alice.post(route, files={'file': ('overlap.pdf', pdf('Another document while prior replacement is pending.'), 'application/pdf')}).status_code == 409
    worker.process(r['id'], db)
    assert alice.post(route, files={'file': ('historical.pdf', pdf('Cannot replace the historical inactive version.'), 'application/pdf')}).status_code == 409
    unrelated, _ = upload(alice, r['id'], 'Different family should never compare as a version.')
    assert alice.get(f"/api/reviews/{r['id']}/documents/{new['id']}/compare", params={'against': unrelated['id']}).status_code == 400


def test_legacy_snapshot_survives_failure_after_version_activation(clients, monkeypatch):
    alice, _, db = clients
    r = review(alice); old, _ = upload(alice, r['id']); worker.process(r['id'], db)
    def legacy(saved):
        saved['analysis'].pop('document_versions', None)
        saved['analysis'].pop('snapshot_id', None)
        saved['findings'][0]['reviewer'] = {'decision': 'accepted', 'note': 'Approved original', 'at': storage.now()}
    db.update(r['id'], legacy)
    new, _ = replace(alice, r['id'], old['id'])
    original = pipeline.analyze_review
    def fail(*args, **kwargs): raise RuntimeError('Simulated worker failure after source extraction')
    monkeypatch.setattr(pipeline, 'analyze_review', fail)
    with pytest.raises(RuntimeError): worker.process(r['id'], db)
    assert db.get(r['id'])['documents'][1]['is_current']
    monkeypatch.setattr(pipeline, 'analyze_review', original)
    worker.process(r['id'], db)
    history = alice.get(f"/api/reviews/{r['id']}/history").json()
    retained = next(s for s in history['snapshots'] if s['findings'][0]['reviewer']['decision'] == 'accepted')
    assert retained['document_versions'][0]['id'] == old['id']
    assert retained['document_versions'][0]['sha256'] == old['sha256']


def test_snapshot_is_immutable_after_later_decision_and_repeat_analysis(clients):
    alice, _, db = clients
    r = review(alice); old, _ = upload(alice, r['id']); worker.process(r['id'], db)
    first = db.get(r['id']); finding_id = first['findings'][0]['id']
    alice.post(f"/api/reviews/{r['id']}/findings/{finding_id}/decision", json={'decision': 'accepted', 'note': 'First run accepted'})
    worker.process(r['id'], db)
    frozen = copy.deepcopy(db.get(r['id'])['_analysis_history'][0])
    alice.post(f"/api/reviews/{r['id']}/findings/{finding_id}/decision", json={'decision': 'unresolved', 'note': 'Second run unresolved'})
    worker.process(r['id'], db)
    history = alice.get(f"/api/reviews/{r['id']}/history").json()['snapshots']
    assert len(history) == 3 and len({item['id'] for item in history}) == 3
    assert history[0] == frozen
    assert history[0]['findings'][0]['reviewer']['note'] == 'First run accepted'
    assert history[1]['findings'][0]['reviewer']['note'] == 'Second run unresolved'
    assert history[2]['findings'][0]['reviewer']['decision'] == 'unreviewed'
    assert all(s['document_versions'][0]['sha256'] == old['sha256'] for s in history)


def test_cloud_workspace_owner_key_and_tamper_check_are_enforced(monkeypatch):
    from app.backend import cloud_store
    from app.tests.test_cloud_store import Database
    monkeypatch.setattr(cloud_store.firestore, 'transactional', lambda fn: fn)
    db = cloud_store.CloudStore.__new__(cloud_store.CloudStore); db.db = Database()
    db.workspace_update('owner-a', lambda w: w['companies'].append({'id': 'private-a', 'name': 'Confidential'}))
    assert db.workspace_get('owner-b')['companies'] == []
    assert db.workspace_get('owner-a')['companies'][0]['id'] == 'private-a'
    assert '_owner' not in db.workspace_get('owner-a')
    key = 'workspaces/' + hashlib.sha256(b'owner-a').hexdigest()
    db.db.values[key]['_owner'] = 'different-owner'
    with pytest.raises(PermissionError): db.workspace_get('owner-a')
    with pytest.raises(PermissionError): db.workspace_update('owner-a', lambda w: w.update(projects=[]))


def test_workspace_byte_limit_is_atomic_locally_and_in_cloud(clients, monkeypatch):
    from fastapi import HTTPException
    from app.backend import cloud_store
    from app.tests.test_cloud_store import Database
    alice, _, local = clients
    owner = alice.cookies.get(main.COOKIE)
    monkeypatch.setattr(cloud_store.firestore, 'transactional', lambda fn: fn)
    cloud = cloud_store.CloudStore.__new__(cloud_store.CloudStore); cloud.db = Database()
    for db in (local, cloud):
        db.workspace_update(owner, lambda w: w['companies'].append({'id': 'original', 'name': 'Keep'}))
        before = db.workspace_get(owner)
        with pytest.raises(HTTPException) as error:
            db.workspace_update(owner, lambda w: w.update(oversized='x'*800001))
        assert error.value.status_code == 400
        assert db.workspace_get(owner) == before


def test_decision_after_failed_analysis_is_not_lost_from_frozen_history(clients, monkeypatch):
    alice, _, db = clients
    r = review(alice); upload(alice, r['id']); worker.process(r['id'], db)
    first = db.get(r['id']); finding_id = first['findings'][0]['id']; snapshot_id = first['analysis']['snapshot_id']
    alice.post(f"/api/reviews/{r['id']}/findings/{finding_id}/decision", json={'decision': 'accepted', 'note': 'Initial approval'})
    original = pipeline.analyze_review
    def fail(*args, **kwargs): raise RuntimeError('Simulated interrupted analysis')
    monkeypatch.setattr(pipeline, 'analyze_review', fail)
    with pytest.raises(RuntimeError): worker.process(r['id'], db)
    response = alice.post(f"/api/reviews/{r['id']}/findings/{finding_id}/decision", json={'decision': 'unresolved', 'note': 'Approval withdrawn after failed run'})
    assert response.status_code == 200
    monkeypatch.setattr(pipeline, 'analyze_review', original)
    worker.process(r['id'], db)
    history = alice.get(f"/api/reviews/{r['id']}/history").json()['snapshots']
    archived = next(s for s in history if s['id'] == snapshot_id)
    assert archived['findings'][0]['reviewer']['decision'] == 'unresolved'
    assert archived['findings'][0]['reviewer']['note'] == 'Approval withdrawn after failed run'
    assert len(archived['findings'][0]['history']) == 2
