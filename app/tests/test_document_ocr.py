"""Offline OCR contract tests: no Google calls, credentials or billable requests."""
import copy
import io
import json
from unittest.mock import Mock

import pytest
from pypdf import PdfWriter
from reportlab.pdfgen.canvas import Canvas
from app.backend import document_ocr as ocr, documents
from app.backend.pipeline import validate_quote

PROCESSOR = 'projects/test-project/locations/asia-south1/processors/testprocessor/processorVersions/pretrained-ocr-v2.1-2024-08-07'
REAL_AUTHORIZED_SESSION = ocr._authorized_session
TEXT = 'Production backups are stored in Singapore for customer Nimbus.\n'


def pdf_bytes(texts=(None,), encrypted=False):
    output = io.BytesIO()
    if all(text is None for text in texts):
        writer = PdfWriter()
        for _ in texts:
            writer.add_blank_page(width=612, height=792)
    else:
        canvas = Canvas(output)
        for text in texts:
            if text:
                canvas.drawString(40, 750, text)
            canvas.showPage()
        canvas.save()
        writer = PdfWriter(io.BytesIO(output.getvalue()))
    if encrypted:
        writer.encrypt('test-password')
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def payload(texts=(TEXT,)):
    start, pages = 0, []
    for n, text in enumerate(texts, 1):
        pages.append({'pageNumber': n, 'layout': {'textAnchor': {'textSegments': [
            {'startIndex': str(start), 'endIndex': str(start + len(text))}]}, 'confidence': 0.94}})
        start += len(text)
    return {'document': {'text': ''.join(texts), 'pages': pages}}


class MemoryStore:
    def __init__(self, data):
        self.doc = {'id': 'doc1', '_blob': 'documents/review1/doc1.pdf', 'status': 'pending',
                    'sha256': 'original-hash', 'name': 'source.pdf', 'pages': []}
        self.review = {'id': 'review1', 'documents': [copy.deepcopy(self.doc)]}
        self.data, self.quota, self.allowed = data, [], True

    def update(self, review_id, fn):
        assert review_id == 'review1'
        candidate = copy.deepcopy(self.review)
        result = fn(candidate)
        self.review = candidate
        return result

    def read_blob(self, key):
        assert key == self.doc['_blob']
        return self.data

    def take_limit(self, owner, maximum=5, amount=1):
        self.quota.append((owner, maximum, amount))
        return self.allowed


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.delenv('EVIDENCEDESK_OCR_PROCESSOR', raising=False)
    monkeypatch.delenv('EVIDENCEDESK_OCR_DAILY_PAGES', raising=False)
    monkeypatch.setattr(ocr, '_authorized_session', Mock(side_effect=AssertionError('No real OCR requests in tests')))


def fake_session(monkeypatch, body=None, status=200, error=None):
    response = Mock(status_code=status)
    response.iter_content.return_value = [json.dumps(body or payload()).encode()]
    session = Mock()
    session.post.return_value = response
    if error:
        session.post.side_effect = error
    monkeypatch.setenv('EVIDENCEDESK_OCR_PROCESSOR', PROCESSOR)
    monkeypatch.setattr(ocr, '_authorized_session', Mock(return_value=session))
    return session, response


def test_capability_is_disabled_without_configuration_and_never_discloses_resource(monkeypatch):
    assert ocr.ocr_capability()['enabled'] is False
    monkeypatch.setenv('EVIDENCEDESK_OCR_PROCESSOR', PROCESSOR)
    result = ocr.ocr_capability()
    assert result['configured'] and result['status'] == 'configured_not_verified'
    assert result['region'] == 'asia-south1' and result['daily_page_limit'] == 100
    assert 'test-project' not in json.dumps(result) and 'testprocessor' not in json.dumps(result)
    ocr._authorized_session.assert_not_called()


@pytest.mark.parametrize('resource', ['https://attacker.example/path', PROCESSOR + '?key=secret',
                                      PROCESSOR.replace('asia-south1', 'global')])
def test_processor_endpoint_cannot_be_overridden(monkeypatch, resource):
    monkeypatch.setenv('EVIDENCEDESK_OCR_PROCESSOR', resource)
    assert ocr.ocr_capability()['enabled'] is False


@pytest.mark.parametrize('limit', ['0', '101', '-1', 'invalid'])
def test_page_ceiling_cannot_be_increased_or_disabled_by_bad_config(monkeypatch, limit):
    monkeypatch.setenv('EVIDENCEDESK_OCR_PROCESSOR', PROCESSOR)
    monkeypatch.setenv('EVIDENCEDESK_OCR_DAILY_PAGES', limit)
    assert ocr.ocr_capability()['enabled'] is False


@pytest.mark.parametrize('data,code', [(b'%PDF-malformed', 'invalid_pdf'), (b'not a pdf', 'invalid_pdf'),
                                      (b'%PDF-'+b'x'*documents.MAX_BYTES, 'size_limit')])
def test_malformed_or_oversized_pdf_never_qualifies_for_ocr(data, code):
    result = documents.parse_pdf(data)
    assert result['error_code'] == code and not result.get('ocr_eligible')


def test_encryption_and_page_limit_are_never_ocr_fallbacks():
    assert documents.parse_pdf(pdf_bytes(encrypted=True))['error_code'] == 'encrypted'
    assert documents.parse_pdf(pdf_bytes((None,) * 26))['error_code'] == 'page_limit'


def test_mixed_pdf_marks_original_unreadable_page_without_discarding_native_text():
    result = documents.parse_pdf(pdf_bytes(('Readable buyer policy requires backups in India.', None)))
    assert result['ocr_eligible'] and result['unreadable_pages'] == [2]
    assert [page['page'] for page in result['pages']] == [1, 2]
    assert 'India' in result['pages'][0]['text']


def test_native_pdf_does_not_create_ocr_session_or_consume_quota():
    store = MemoryStore(pdf_bytes(('Readable buyer policy requires backups in India.',)))
    result = documents.extract_document(store.doc, store)
    assert result['status'] == 'pending' and result['extraction_method'] == 'native_pdf'
    assert result['extraction_version'] == 'pypdf-isolated-v1'
    assert store.quota == []
    ocr._authorized_session.assert_not_called()


def test_unconfigured_scan_is_unresolved_without_attempt_or_charge():
    store = MemoryStore(pdf_bytes())
    result = documents.extract_document(store.doc, store)
    assert result['status'] == 'failed' and 'not configured' in result['error']
    assert not result['pages'] and not store.quota and '_ocr_attempt' not in result


def test_scan_uses_regional_single_request_and_preserves_quote_provenance(monkeypatch):
    session, response = fake_session(monkeypatch)
    store = MemoryStore(pdf_bytes())
    result = documents.extract_document(store.doc, store)
    assert result['status'] == 'pending' and result['page_count'] == 1
    assert result['_blob'] == 'documents/review1/doc1.pdf' and result['sha256'] == 'original-hash'
    assert result['extraction_method'] == 'document_ai_ocr'
    assert result['ocr']['requires_human_verification'] and result['pages'][0]['ocr_confidence'] == .94
    assert result['pages'][0]['text'] == TEXT
    assert validate_quote(result, 1, 'backups are stored in Singapore')
    assert not validate_quote(result, 2, 'backups are stored in Singapore')
    assert not validate_quote(result, 1, 'backups are stored in India')
    assert store.quota == [('document-ai-ocr-pages', 100, 1)]
    session.post.assert_called_once()
    args, kwargs = session.post.call_args
    assert args[0] == f'https://asia-south1-documentai.googleapis.com/v1/{PROCESSOR}:process'
    assert kwargs['json']['imagelessMode'] is True
    assert kwargs['timeout'] == (10, 60) and kwargs['allow_redirects'] is False
    assert result['_ocr_attempt']['state'] == 'completed'
    response.close.assert_called_once(); session.close.assert_called_once()


def test_mixed_scan_preserves_native_page_and_reserves_all_billed_pages(monkeypatch):
    fake_session(monkeypatch, payload(('Untrusted OCR replacement must not overwrite native text.', TEXT)))
    store = MemoryStore(pdf_bytes(('Readable buyer policy requires backups in India.', None)))
    result = documents.extract_document(store.doc, store)
    assert result['status'] == 'pending'
    assert result['extraction_method'] == 'native_pdf_with_ocr' and result['ocr']['ocr_pages'] == [2]
    assert 'India' in result['pages'][0]['text'] and result['pages'][0]['extraction_method'] == 'native_pdf'
    assert result['pages'][1]['text'] == TEXT and result['pages'][1]['page'] == 2
    assert store.quota == [('document-ai-ocr-pages', 100, 2)]


@pytest.mark.parametrize('failure', ['http', 'timeout', 'bad_json', 'large_response'])
def test_dispatched_failures_are_never_retried_or_refunded(monkeypatch, failure):
    session, response = fake_session(monkeypatch, status=503 if failure == 'http' else 200,
                                     error=TimeoutError('private request context') if failure == 'timeout' else None)
    if failure == 'bad_json': response.iter_content.return_value = [b'not-json-secret']
    if failure == 'large_response': response.iter_content.return_value = [b'x'*(ocr.MAX_RESPONSE_BYTES+1)]
    store = MemoryStore(pdf_bytes())
    result = documents.extract_document(store.doc, store)
    assert result['status'] == 'failed' and not result['pages']
    assert 'secret' not in result['error'] and 'private' not in result['error']
    assert len(store.quota) == 1
    # Simulate a recovered worker reading the durable pre-dispatch marker.
    recovered = copy.deepcopy(store.review['documents'][0])
    result2 = documents.extract_document(recovered, store)
    assert result2['status'] == 'failed' and 'already recorded' in result2['error']
    session.post.assert_called_once()
    assert len(store.quota) == 1


def test_quota_denial_cannot_dispatch(monkeypatch):
    session, _ = fake_session(monkeypatch)
    store = MemoryStore(pdf_bytes()); store.allowed = False
    result = documents.extract_document(store.doc, store)
    assert 'daily OCR page limit' in result['error'] and result['status'] == 'failed'
    session.post.assert_not_called()


def test_missing_shared_quota_fails_closed(monkeypatch):
    session, _ = fake_session(monkeypatch)
    store = MemoryStore(pdf_bytes()); store.take_limit = None
    result = documents.extract_document(store.doc, store)
    assert 'quota is unavailable' in result['error']
    session.post.assert_not_called()


def test_atomic_attempt_claim_prevents_stale_second_worker_dispatch(monkeypatch):
    session, _ = fake_session(monkeypatch)
    store = MemoryStore(pdf_bytes()); stale = copy.deepcopy(store.doc)
    assert documents.extract_document(store.doc, store)['status'] == 'pending'
    assert 'already recorded' in documents.extract_document(stale, store)['error']
    session.post.assert_called_once()
    assert len(store.quota) == 1


def test_blank_ocr_text_does_not_produce_findings(monkeypatch):
    fake_session(monkeypatch, payload(('tiny',)))
    store = MemoryStore(pdf_bytes())
    result = documents.extract_document(store.doc, store)
    assert result['status'] == 'failed' and not result['pages']


@pytest.mark.parametrize('mutator', [
    lambda p: p['document']['pages'].clear(),
    lambda p: p['document']['pages'][0].update(pageNumber=2),
    lambda p: p['document']['pages'][0]['layout']['textAnchor']['textSegments'][0].update(endIndex='99999'),
    lambda p: p['document']['pages'][0]['layout']['textAnchor']['textSegments'][0].update(startIndex='-1'),
    lambda p: p['document']['pages'][0]['layout']['textAnchor'].update(textSegments=[{'endIndex':'5'}, {'startIndex':'6','endIndex':'10'}]),
    lambda p: p['document']['pages'][0]['layout']['textAnchor'].update(textSegments=[{'endIndex':'10'}, {'startIndex':'5','endIndex':'15'}]),
])
def test_invalid_page_coverage_or_offsets_cannot_fabricate_citations(mutator):
    result = payload(); mutator(result)
    with pytest.raises(ocr.OCRError): ocr.parse_ocr_response(result, 1)


def test_unicode_offsets_and_omitted_zero_start_are_literal():
    result = payload(('Café production backup: भारत Singapore.\n', TEXT))
    del result['document']['pages'][0]['layout']['textAnchor']['textSegments'][0]['startIndex']
    pages = ocr.parse_ocr_response(result, 2)
    assert pages[0]['text'] == 'Café production backup: भारत Singapore.\n'
    assert pages[1]['text'] == TEXT
    assert validate_quote({'pages': pages}, 1, 'भारत Singapore')
    assert not validate_quote({'pages': pages}, 2, 'भारत Singapore')


def test_staged_replacement_can_extract_without_activating_itself(monkeypatch):
    fake_session(monkeypatch)
    store = MemoryStore(pdf_bytes())
    for doc in (store.doc, store.review['documents'][0]):
        doc.update(is_current=False, replacement_pending=True, _replaces='old-version')
    result = documents.extract_document(store.doc, store)
    assert result['status'] == 'pending' and result['pages'][0]['text'] == TEXT
    assert result['is_current'] is False and result['replacement_pending'] is True
    assert result['_replaces'] == 'old-version'
    assert store.review['documents'][0]['is_current'] is False


def test_coverage_excludes_historical_and_staged_replacement_versions():
    review = {'documents': [
        {'id': 'current', 'status': 'processed', 'page_count': 2},
        {'id': 'old', 'status': 'failed', 'page_count': 5, 'is_current': False},
        {'id': 'staged', 'status': 'pending', 'page_count': 0, 'is_current': False, 'replacement_pending': True},
        {'id': 'duplicate', 'status': 'duplicate', 'page_count': 2, 'is_current': True},
    ]}
    assert documents.coverage(review) == {'submitted': 2, 'processed': 1, 'failed': 0, 'duplicates': 1, 'pages': 2}


def test_configured_ocr_never_receives_encrypted_or_malformed_pdf(monkeypatch):
    session, _ = fake_session(monkeypatch)
    for data in (b'%PDF-invalid-file', pdf_bytes(encrypted=True)):
        store = MemoryStore(data)
        result = documents.extract_document(store.doc, store)
        assert result['status'] == 'failed' and not result.get('_ocr_attempt') and not store.quota
    session.post.assert_not_called()


def test_authorized_session_disables_auth_replay(monkeypatch):
    import google.auth
    import google.auth.transport.requests
    # Restore the real factory, but mock its credentials and transport constructor.
    with monkeypatch.context() as patch:
        patch.setattr(google.auth, 'default', Mock(return_value=(object(), 'unused')))
        constructor = Mock()
        patch.setattr(google.auth.transport.requests, 'AuthorizedSession', constructor)
        REAL_AUTHORIZED_SESSION()
        assert constructor.call_args.kwargs['max_refresh_attempts'] == 0
