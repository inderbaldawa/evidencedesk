"""Offline interleaving checks for GCS fencing and repairable Firestore indexes."""
import copy
import json
import threading
import pytest
from google.api_core.exceptions import NotFound, PreconditionFailed
from app.backend import cloud_store, worker
from app.backend.store import new_review


class Snapshot:
    def __init__(self, value):
        self.value = copy.deepcopy(value)
    def to_dict(self):
        return copy.deepcopy(self.value)


class Reference:
    def __init__(self, db, path):
        self.db, self.path = db, path
    def document(self, value):
        return Reference(self.db, self.path + '/' + value)
    def collection(self, value):
        return Reference(self.db, self.path + '/' + value)
    def get(self, transaction=None):
        return Snapshot(self.db.values.get(self.path))
    def set(self, value, merge=False):
        if merge:
            self.db.values.setdefault(self.path, {}).update(copy.deepcopy(value))
        else:
            self.db.values[self.path] = copy.deepcopy(value)


class Transaction:
    def __init__(self, db):
        self.db = db
    def set(self, ref, value, merge=False):
        self.db.writes.append(ref.path)
        ref.set(value, merge=merge)
    def delete(self, ref):
        self.db.values.pop(ref.path, None)


class Database:
    def __init__(self):
        self.values, self.writes = {}, []
    def collection(self, value):
        return Reference(self, value)
    def transaction(self):
        return Transaction(self)


class Blob:
    def __init__(self, bucket, key):
        self.bucket, self.key, self.generation = bucket, key, None
    def reload(self):
        if self.key not in self.bucket.values:
            raise NotFound('missing')
        self.generation = self.bucket.values[self.key][0]
    def download_as_bytes(self, if_generation_match=None):
        if self.key not in self.bucket.values:
            raise NotFound('missing')
        generation, data = self.bucket.values[self.key]
        if if_generation_match is not None and generation != if_generation_match:
            raise PreconditionFailed('generation changed')
        return data
    def upload_from_string(self, value, content_type=None, if_generation_match=None):
        hook, self.bucket.before_upload = self.bucket.before_upload, None
        if hook:
            hook()
        actual = self.bucket.values.get(self.key, (0, b''))[0]
        if if_generation_match is not None and actual != if_generation_match:
            raise PreconditionFailed('generation changed')
        self.bucket.sequence += 1
        self.generation = self.bucket.sequence
        data = value.encode() if isinstance(value, str) else value
        self.bucket.values[self.key] = self.generation, data


class Bucket:
    def __init__(self):
        self.values, self.sequence, self.before_upload = {}, 0, None
    def blob(self, key):
        return Blob(self, key)


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr(cloud_store.firestore, 'transactional', lambda fn: fn)
    value = cloud_store.CloudStore.__new__(cloud_store.CloudStore)
    value.db, value.bucket = Database(), Bucket()
    value.project, value.region = 'test-project', 'test-region'
    return value


def queued(store):
    review = new_review('owner')
    review['id'] = 'review-1'
    review['status'] = 'queued'
    store.put(review)
    store.update(review['id'], lambda r: r.update(_analysis_run_id='run-1', _queued_at=cloud_store.time.time()))
    return review['id']


def test_retry_attempt_cannot_share_live_execution_lease(store):
    rid = queued(store)
    assert store.acquire_review(rid, 'same-execution:attempt-0', 'run-1')
    assert not store.acquire_review(rid, 'same-execution:attempt-1', 'run-1')
    with pytest.raises(cloud_store.ReviewLeaseLost):
        store.update(rid, lambda r: r.update(name='unauthorized'), lease_token='same-execution:attempt-1')


def test_expired_owner_is_fenced_even_when_takeover_races_its_cas(store, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(cloud_store.time, 'time', lambda: clock[0])
    rid = queued(store)
    assert store.acquire_review(rid, 'old', 'run-1')
    def takeover():
        clock[0] += cloud_store.LEASE_SECONDS + 1
        assert store.acquire_review(rid, 'new', 'run-1')
        store.update(rid, lambda r: r.update(name='successor result'), lease_token='new')
    store.bucket.before_upload = takeover
    with pytest.raises(cloud_store.ReviewLeaseLost):
        store.update(rid, lambda r: r.update(name='stale result'), lease_token='old')
    assert store.get(rid)['name'] == 'successor result'
    assert not store.release_review(rid, 'old')
    assert store.get(rid)['_processing_lease']['owner'] == 'new'


def test_expired_heartbeat_cannot_resurrect_old_owner(store, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(cloud_store.time, 'time', lambda: clock[0])
    rid = queued(store)
    store.acquire_review(rid, 'old', 'run-1')
    clock[0] += cloud_store.LEASE_SECONDS + 1
    with pytest.raises(cloud_store.ReviewLeaseLost):
        store.heartbeat_review(rid, 'old')
    assert store.acquire_review(rid, 'new', 'run-1')


def test_interrupted_worker_recovers_visible_failure_without_losing_progress(store, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(cloud_store.time, 'time', lambda: clock[0])
    rid = queued(store)
    store.acquire_review(rid, 'old', 'run-1')
    store.update(rid, lambda r: r.update(status='processing', analysis={'reconciliation_cache': {'saved': True}}), lease_token='old')
    clock[0] += cloud_store.LEASE_SECONDS + 1
    result = store.get(rid)
    assert result['status'] == 'failed'
    assert result['analysis']['reconciliation_cache']['saved']
    assert result['events'][-1]['type'] == 'worker_interrupted'
    assert store.acquire_review(rid, 'retry', 'run-1')


def test_heartbeat_preserves_work_and_blocks_browser_mutation(store):
    rid = queued(store)
    store.acquire_review(rid, 'worker', 'run-1')
    store.heartbeat_review(rid, 'worker')
    with pytest.raises(cloud_store.ReviewLeaseLost):
        store.update(rid, lambda r: r.update(name='concurrent edit'))
    store.release_review(rid, 'worker')
    store.update(rid, lambda r: r.update(name='edit after release'))
    assert store.get(rid)['name'] == 'edit after release'


def test_superseded_or_completed_dispatch_never_reexecutes(store):
    rid = queued(store)
    with pytest.raises(cloud_store.ReviewRunObsolete):
        store.acquire_review(rid, 'old', 'wrong-run')
    store.update(rid, lambda r: r.update(_completed_run_id='run-1', status='complete'))
    with pytest.raises(cloud_store.ReviewRunObsolete):
        store.acquire_review(rid, 'retry', 'run-1')
    calls = []
    assert not worker.run_cloud_review(store, rid, run_id='run-1', process_fn=lambda *args: calls.append(args))
    assert calls == []


def test_delayed_index_cannot_overwrite_newer_metadata_or_children(store):
    rid = queued(store)
    older, old_generation = store._read(rid)
    store.update(rid, lambda r: r.update(status='complete', findings=[{'id': 'finding-1', 'status': 'evidence_found'}]))
    assert not store._index(older, old_generation)
    assert store.db.values[f'reviews/{rid}']['status'] == 'complete'
    assert store.db.values[f'reviews/{rid}/findings/finding-1']['status'] == 'evidence_found'


def test_index_failure_never_replays_successful_mutation_and_read_repairs(store, monkeypatch):
    rid = queued(store)
    publish = store._index
    monkeypatch.setattr(store, '_index', lambda *args: (_ for _ in ()).throw(PreconditionFailed('index failure')))
    calls = []
    def append(r):
        calls.append(1)
        r['events'].append({'type': 'once'})
    store.update(rid, append)
    assert calls == [1]
    monkeypatch.setattr(store, '_index', publish)
    result = store.get(rid)
    assert result['events'].count({'type': 'once'}) == 1
    assert store.db.values[f'reviews/{rid}']['artifact_generation'] == store._read(rid)[1]


def test_heartbeat_projection_does_not_rewrite_unchanged_documents(store):
    rid = queued(store)
    store.update(rid, lambda r: r.update(documents=[{'id': 'doc-1', 'name': 'source.pdf', 'pages': [{'page': 1, 'text': 'private source'}], '_blob': 'private-key'}]))
    store.acquire_review(rid, 'worker', 'run-1')
    store.db.writes.clear()
    store.heartbeat_review(rid, 'worker')
    assert store.db.writes == [f'reviews/{rid}']
    doc = store.db.values[f'reviews/{rid}/documents/doc-1']
    assert 'pages' not in doc and '_blob' not in doc


def test_new_projection_removes_obsolete_child_records(store):
    rid = queued(store)
    store.update(rid, lambda r: r.update(findings=[{'id': 'old'}]))
    store.update(rid, lambda r: r.update(findings=[{'id': 'new'}]))
    assert f'reviews/{rid}/findings/old' not in store.db.values
    assert f'reviews/{rid}/findings/new' in store.db.values


def test_cloned_review_does_not_inherit_lease_or_run_identity(store):
    rid = queued(store)
    store.acquire_review(rid, 'worker', 'run-1')
    clone = store.get(rid)
    clone['id'] = 'clone'
    store.put(clone)
    result = store.get('clone')
    assert '_processing_lease' not in result and '_analysis_run_id' not in result


def test_worker_failure_after_lease_loss_cannot_mark_successor_failed(store, monkeypatch):
    from app.backend import pipeline
    clock = [1000.0]
    monkeypatch.setattr(cloud_store.time, 'time', lambda: clock[0])
    rid = queued(store)
    store.acquire_review(rid, 'old', 'run-1')
    bound = worker.LeaseBoundStore(store, rid, 'old', threading.Event())
    def supersede(*args, **kwargs):
        clock[0] += cloud_store.LEASE_SECONDS + 1
        store.acquire_review(rid, 'new', 'run-1')
        store.update(rid, lambda r: r.update(status='complete'), lease_token='new')
        raise RuntimeError('old model response failed')
    monkeypatch.setattr(pipeline, 'analyze_review', supersede)
    with pytest.raises(RuntimeError, match='old model'):
        worker.process(rid, bound)
    assert store.get(rid)['status'] == 'complete'


def test_attempt_identity_unique_with_same_cloud_execution_and_retry_number(monkeypatch):
    monkeypatch.setenv('CLOUD_RUN_EXECUTION', 'same-execution')
    monkeypatch.setenv('CLOUD_RUN_TASK_ATTEMPT', '1')
    first, second = worker.attempt_identity(), worker.attempt_identity()
    assert first.startswith('same-execution:0:1:')
    assert first != second


def test_worker_retries_after_short_dead_owner_lease(store, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(cloud_store.time, 'time', lambda: clock[0])
    monkeypatch.setattr(worker.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(worker.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    rid = queued(store)
    store.acquire_review(rid, 'dead-attempt', 'run-1')
    def finish(review_id, bound):
        bound.update(review_id, lambda r: r.update(status='complete', _completed_run_id='run-1'))
    assert worker.run_cloud_review(store, rid, run_id='run-1', process_fn=finish)
    assert 1090 <= clock[0] <= 1092
    assert store.get(rid)['status'] == 'complete'
    assert store.get(rid)['_processing_lease']['expires_at'] == 0


def test_index_orders_by_cas_revision_not_opaque_gcs_generation(store):
    rid = queued(store)
    store.bucket.sequence = 500
    store.update(rid, lambda r: r.update(name='older'))
    old, old_generation = store._read(rid)
    store.bucket.sequence = 100  # GCS does not guarantee increasing generation IDs.
    store.update(rid, lambda r: r.update(name='newer'))
    assert store.db.values[f'reviews/{rid}']['name'] == 'newer'
    assert store.db.values[f'reviews/{rid}']['artifact_generation'] < old_generation
    assert not store._index(old, old_generation)
    assert store.db.values[f'reviews/{rid}']['name'] == 'newer'


def test_queued_dispatch_that_never_started_becomes_retryable(store, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(cloud_store.time, 'time', lambda: clock[0])
    rid = queued(store)
    clock[0] += cloud_store.QUEUE_TIMEOUT_SECONDS + 1
    result = store.get(rid)
    assert result['status'] == 'failed'
    assert result['events'][-1]['type'] == 'worker_interrupted'


def test_lost_heartbeat_stops_worker_mutations(store):
    rid = queued(store)
    store.acquire_review(rid, 'worker', 'run-1')
    lost = threading.Event()
    bound = worker.LeaseBoundStore(store, rid, 'worker', lost)
    lost.set()
    with pytest.raises(cloud_store.ReviewLeaseLost):
        bound.update(rid, lambda r: r.update(status='complete'))
    assert store.get(rid)['status'] == 'queued'


def test_pdf_extraction_exception_is_persisted_as_failed(store, monkeypatch):
    rid = queued(store)
    store.update(rid, lambda r: r.update(documents=[{'id': 'doc', 'name': 'broken.pdf', '_blob': 'object', 'pages': [], 'status': 'pending', 'page_count': 0}]))
    store.acquire_review(rid, 'worker', 'run-1')
    bound = worker.LeaseBoundStore(store, rid, 'worker', threading.Event())
    monkeypatch.setattr(worker, 'extract_document', lambda *args: (_ for _ in ()).throw(RuntimeError('storage unavailable')))
    with pytest.raises(RuntimeError, match='storage unavailable'):
        worker.process(rid, bound)
    assert store.get(rid)['status'] == 'failed'


class DispatchResponse:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self.body = {'name': 'operations/test'} if body is None else body
    def raise_for_status(self):
        from requests.exceptions import HTTPError
        if self.status_code >= 400:
            raise HTTPError(f'HTTP {self.status_code}', response=self)
    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


def dispatch_session(monkeypatch, store, response=None, error=None, on_post=None, close_error=False):
    import google.auth
    import google.auth.transport.requests
    class Session:
        def __init__(self):
            self.calls, self.closed = [], False
        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            if on_post:
                on_post(kwargs)
            if error:
                raise error
            return response or DispatchResponse()
        def close(self):
            self.closed = True
            if close_error:
                raise RuntimeError('cleanup unavailable')
    session = Session()
    monkeypatch.setattr(store, 'take_limit', lambda *args: True)
    monkeypatch.setattr(google.auth, 'default', lambda **kwargs: (object(), 'test-project'))
    monkeypatch.setattr(google.auth.transport.requests, 'AuthorizedSession', lambda credentials: session)
    return session


@pytest.mark.parametrize('failure', ['timeout', 'connection', 'auth_transport', 500, 503])
def test_uncertain_dispatch_preserves_run_and_never_reposts(store, monkeypatch, failure):
    from requests.exceptions import Timeout, ConnectionError
    from google.auth.exceptions import TransportError
    errors = {'timeout': Timeout('response lost'), 'connection': ConnectionError('connection lost'), 'auth_transport': TransportError('transport lost')}
    rid = queued(store)
    session = dispatch_session(monkeypatch, store, response=DispatchResponse(failure) if isinstance(failure, int) else None, error=errors.get(failure))
    with pytest.raises(cloud_store.DispatchUncertain) as caught:
        store.enqueue(rid)
    result = store.get(rid)
    assert result['status'] == 'queued'
    assert result['_analysis_run_id'] == caught.value.run_id != 'run-1'
    assert len(session.calls) == 1 and session.closed
    payload = session.calls[0][1]
    assert payload['allow_redirects'] is False
    assert payload['json']['overrides']['containerOverrides'][0]['env'][1]['value'] == caught.value.run_id


def test_explicit_dispatch_rejection_is_known_failure(store, monkeypatch):
    from requests.exceptions import HTTPError
    rid = queued(store)
    session = dispatch_session(monkeypatch, store, response=DispatchResponse(403))
    with pytest.raises(HTTPError):
        store.enqueue(rid)
    assert len(session.calls) == 1 and session.closed


def test_accepted_dispatch_metadata_failure_cannot_fail_running_worker(store, monkeypatch):
    rid = queued(store)
    original_set = Reference.set
    def reject_auxiliary(ref, value, merge=False):
        if 'last_dispatched_operation' in value:
            raise RuntimeError('Firestore metadata unavailable')
        return original_set(ref, value, merge)
    monkeypatch.setattr(Reference, 'set', reject_auxiliary)
    def start_worker(payload):
        run_id = payload['json']['overrides']['containerOverrides'][0]['env'][1]['value']
        assert store.acquire_review(rid, 'started-worker', run_id)
        store.update(rid, lambda r: r.update(status='processing'), lease_token='started-worker')
    session = dispatch_session(monkeypatch, store, on_post=start_worker)
    store.enqueue(rid)
    assert store.get(rid)['status'] == 'processing'
    assert len(session.calls) == 1 and session.closed


@pytest.mark.parametrize('body', [{}, {'name': ''}, ValueError('response body lost')])
def test_accepted_dispatch_invalid_auxiliary_body_is_not_retried(store, monkeypatch, body):
    rid = queued(store)
    session = dispatch_session(monkeypatch, store, response=DispatchResponse(200, body))
    store.enqueue(rid)
    assert store.get(rid)['status'] == 'queued'
    assert len(session.calls) == 1 and session.closed


def test_session_cleanup_cannot_mask_accepted_dispatch(store, monkeypatch):
    rid = queued(store)
    session = dispatch_session(monkeypatch, store, close_error=True)
    store.enqueue(rid)
    assert store.db.values[f'reviews/{rid}']['last_dispatched_operation'] == 'operations/test'
    assert len(session.calls) == 1 and session.closed
