"""Offline Firebase auth failure classification and cold-start concurrency checks."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import firebase_admin
from firebase_admin import auth, exceptions
import pytest
from fastapi.testclient import TestClient
from requests.exceptions import ConnectionError
from app.backend import main, store as storage


@pytest.fixture
def auth_client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'ROOT', tmp_path)
    db = storage.LocalStore()
    monkeypatch.setattr(main, 'store', db)
    monkeypatch.setattr(main, 'CLOUD', True)
    app = object()
    monkeypatch.setattr(main, '_firebase_app', lambda: app)
    with TestClient(main.app) as client:
        yield client, app, db


def test_concurrent_first_requests_initialize_one_default_app(monkeypatch):
    project = 'test-auth-project'
    monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', project)
    state = {'app': None, 'initializations': 0}
    barrier = threading.Barrier(12)
    def get_app():
        if state['app'] is None:
            raise ValueError('App not yet initialized')
        return state['app']
    def initialize_app(*, options):
        state['initializations'] += 1
        time.sleep(0.02)  # Expose check-then-initialize races without network calls.
        if state['app'] is not None:
            raise ValueError('Default app already exists')
        state['app'] = SimpleNamespace(project_id=options['projectId'])
        return state['app']
    monkeypatch.setattr(firebase_admin, 'get_app', get_app)
    monkeypatch.setattr(firebase_admin, 'initialize_app', initialize_app)
    def request():
        barrier.wait()
        return main._firebase_app()
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: request(), range(12)))
    assert state['initializations'] == 1
    assert all(result is state['app'] for result in results)


@pytest.mark.parametrize('failure', [
    auth.InvalidIdTokenError('bad signature'),
    auth.ExpiredIdTokenError('expired token', None),
    auth.RevokedIdTokenError('revoked token'),
    auth.UserDisabledError('disabled user'),
    auth.UserNotFoundError('deleted user'),
])
def test_rejected_identity_stays_401_and_never_writes(auth_client, monkeypatch, failure):
    client, application, db = auth_client
    calls = []
    def verify(token, **kwargs):
        calls.append(kwargs)
        raise failure
    monkeypatch.setattr(auth, 'verify_id_token', verify)
    response = client.post('/api/reviews', json={}, headers={'Authorization': 'Bearer test-token'})
    assert response.status_code == 401
    assert calls == [{'app': application, 'check_revoked': True}]
    with db.connect() as connection:
        assert connection.execute('SELECT COUNT(*) FROM reviews').fetchone()[0] == 0


@pytest.mark.parametrize('failure', [
    auth.CertificateFetchError('certificate fetch failed', ConnectionError('network unavailable')),
    exceptions.UnavailableError('upstream service unavailable'),
    exceptions.PermissionDeniedError('missing IAM permission'),
    exceptions.ResourceExhaustedError('upstream quota'),
    ConnectionError('transport unavailable'),
    RuntimeError('unexpected SDK failure'),
])
def test_operational_failure_is_503_and_retry_reverifies(auth_client, monkeypatch, failure):
    client, application, db = auth_client
    calls = []
    def verify(token, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise failure
        return {'uid': 'same-user'}
    monkeypatch.setattr(auth, 'verify_id_token', verify)
    headers = {'Authorization': 'Bearer same-token'}
    first = client.post('/api/reviews', json={}, headers=headers)
    assert first.status_code == 503 and first.headers['Retry-After'] == '5'
    second = client.post('/api/reviews', json={}, headers=headers)
    assert second.status_code == 200 and db.get(second.json()['id'])['_owner'] == 'same-user'
    assert calls == [{'app': application, 'check_revoked': True}] * 2


def test_auth_log_never_contains_message_token_url_or_untrusted_code(auth_client, monkeypatch, caplog):
    client, _, _ = auth_client
    token = 'DO_NOT_LOG_AUTH_TOKEN'
    url = 'https://example.invalid/?secret=DO_NOT_LOG_URL'
    failure = RuntimeError(token + ' ' + url)
    failure.code = 'DO_NOT_LOG_CODE'
    monkeypatch.setattr(auth, 'verify_id_token', lambda *a, **kw: (_ for _ in ()).throw(failure))
    with caplog.at_level('WARNING', logger=main.__name__):
        response = client.post('/api/reviews', json={}, headers={'Authorization': 'Bearer ' + token})
    assert response.status_code == 503
    assert 'exception_type=RuntimeError code=UNCLASSIFIED' in caplog.text
    assert all(secret not in caplog.text + response.text for secret in [token, url, failure.code])
    assert all(record.exc_info is None for record in caplog.records)


def test_initializer_failure_is_503_without_attempting_verification(auth_client, monkeypatch):
    client, _, _ = auth_client
    monkeypatch.setattr(main, '_firebase_app', lambda: (_ for _ in ()).throw(ValueError('configuration failure')))
    monkeypatch.setattr(auth, 'verify_id_token', lambda *a, **kw: pytest.fail('Verification must not run with failed initialization'))
    assert client.post('/api/reviews', json={}, headers={'Authorization': 'Bearer test'}).status_code == 503


def test_wrong_existing_firebase_project_fails_closed(monkeypatch):
    monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'expected-project')
    monkeypatch.setattr(firebase_admin, 'get_app', lambda: SimpleNamespace(project_id='other-project'))
    with pytest.raises(RuntimeError, match='project'):
        main._firebase_app()


def test_missing_or_empty_bearer_does_not_initialize_sdk(auth_client, monkeypatch):
    client, _, _ = auth_client
    monkeypatch.setattr(main, '_firebase_app', lambda: pytest.fail('No SDK call for missing bearer token'))
    for header in ['', 'Bearer ', 'Bearer   ', 'Basic test']:
        assert client.post('/api/reviews', json={}, headers={'Authorization': header}).status_code == 401


def test_valid_token_then_revocation_is_checked_again(auth_client, monkeypatch):
    client, _, _ = auth_client
    calls = []
    def verify(token, **kwargs):
        calls.append(kwargs)
        if len(calls) > 1:
            raise auth.RevokedIdTokenError('user revoked between requests')
        return {'uid': 'user'}
    monkeypatch.setattr(auth, 'verify_id_token', verify)
    headers = {'Authorization': 'Bearer same-token'}
    created = client.post('/api/reviews', json={}, headers=headers)
    assert created.status_code == 200
    assert client.get('/api/reviews/' + created.json()['id'], headers=headers).status_code == 401
    assert len(calls) == 2 and all(call['check_revoked'] is True for call in calls)
