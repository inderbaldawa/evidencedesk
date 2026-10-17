"""Opt-in, single-attempt Google Document AI OCR with a durable page quota.

REST contract: https://docs.cloud.google.com/document-ai/docs/reference/rest/v1/projects.locations.processors/process
OCR limits/regions: https://docs.cloud.google.com/document-ai/docs/processors-list
Text offsets: https://docs.cloud.google.com/document-ai/docs/reference/rest/v1/Document#TextSegment
No client retries: a dispatched/uncertain request consumes its entire reservation.
"""
import base64
import json
import math
import os
import re
from datetime import datetime, timezone

MAX_BYTES = 5 * 1024 * 1024
MAX_PAGES = 25
MAX_TEXT = 150000
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
EXTRACTION_VERSION = 'document-ai-ocr-v1'
OCR_WARNING = ('OCR-derived text can contain recognition errors. Quotations are checked against '
               'the extracted OCR text, not independently against the scanned image. '
               'Verify the cited original PDF page before relying on a finding.')
REGIONS = frozenset(('us', 'eu', 'asia-south1', 'asia-southeast1', 'australia-southeast1',
                     'europe-west2', 'europe-west3', 'northamerica-northeast1'))
RESOURCE = re.compile(r'projects/([a-zA-Z0-9-]+)/locations/([a-z0-9-]+)/processors/([a-zA-Z0-9_-]+)'
                      r'(?:/processorVersions/([a-zA-Z0-9_.-]+))?')


class OCRError(ValueError):
    """Safe, user-facing failure. Never include raw HTTP/provider error bodies."""


def _configuration():
    resource = os.environ.get('EVIDENCEDESK_OCR_PROCESSOR', '').strip()
    if not resource:
        raise OCRError('Scanned PDF OCR is not configured; this document remains unresolved.')
    match = RESOURCE.fullmatch(resource)
    if not match or match[2] not in REGIONS:
        raise OCRError('OCR processor configuration is invalid; this document remains unresolved.')
    try:
        maximum = int(os.environ.get('EVIDENCEDESK_OCR_DAILY_PAGES', '100'))
    except ValueError:
        raise OCRError('OCR daily page limit is invalid.') from None
    # Lower deployment limits are supported; a config typo cannot increase the ceiling.
    if not 1 <= maximum <= 100:
        raise OCRError('OCR daily page limit must be between 1 and 100.')
    return resource, match[2], match[4] or 'processor-default', maximum


def ocr_capability():
    """Configuration capability only: no credentials/network probes or identities."""
    try:
        _, region, _, maximum = _configuration()
    except OCRError as exc:
        return {'enabled': False, 'configured': False, 'status': 'unavailable',
                'message': str(exc), 'requires_human_verification': True}
    return {'enabled': True, 'configured': True, 'status': 'configured_not_verified',
            'region': region, 'daily_page_limit': maximum, 'max_document_pages': MAX_PAGES,
            'requires_human_verification': True, 'warning': OCR_WARNING}


def _integer(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise OCRError('OCR returned an invalid page number or text offset.')
    if isinstance(value, str) and not value.isdigit():
        raise OCRError('OCR returned an invalid page number or text offset.')
    return int(value)


def parse_ocr_response(payload, expected_pages):
    """Use page text anchors verbatim, rejecting missing pages/invalid offsets.

    Document AI indices address Unicode characters in Document.text. Do not guess
    page numbering, infer text from layout.content or stitch noncontiguous spans
    into a contiguous quotation. Noncontiguous page anchors fail closed.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get('document'), dict):
        raise OCRError('OCR returned no readable document.')
    document = payload['document']
    if document.get('error', {}).get('code', 0):
        raise OCRError('OCR could not process this document.')
    text, raw_pages = document.get('text'), document.get('pages')
    if not isinstance(text, str) or len(text) > MAX_TEXT:
        raise OCRError('OCR text is missing or exceeds the document limit.')
    if not isinstance(raw_pages, list) or len(raw_pages) != expected_pages or not 1 <= expected_pages <= MAX_PAGES:
        raise OCRError('OCR page coverage does not match the original PDF.')
    pages = []
    previous_end = 0
    for number, raw in enumerate(raw_pages, 1):
        if not isinstance(raw, dict) or _integer(raw.get('pageNumber')) != number:
            raise OCRError('OCR page numbering does not match the original PDF.')
        layout = raw.get('layout', {})
        if not isinstance(layout, dict):
            raise OCRError('OCR page layout is invalid.')
        anchor = layout.get('textAnchor', {})
        segments = anchor.get('textSegments', []) if isinstance(anchor, dict) else []
        if not isinstance(segments, list):
            raise OCRError('OCR text offsets are invalid.')
        start = end = None
        for segment in segments:
            if not isinstance(segment, dict):
                raise OCRError('OCR text offsets are invalid.')
            seg_start = _integer(segment.get('startIndex', 0))
            seg_end = _integer(segment.get('endIndex'))
            if not previous_end <= seg_start < seg_end <= len(text) or (end is not None and seg_start != end):
                raise OCRError('OCR text offsets are out of range, overlapping or noncontiguous.')
            if start is None:
                start = seg_start
            end = seg_end
        page_text = text[start:end] if start is not None else ''
        if end is not None:
            previous_end = end
        page = {'page': number, 'text': page_text, 'extraction_method': 'document_ai_ocr',
                'ocr_text_offsets': {'start': start, 'end': end}, 'requires_human_verification': True}
        confidence = layout.get('confidence')
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) and math.isfinite(confidence) and 0 <= confidence <= 1:
            page['ocr_confidence'] = confidence
        pages.append(page)
    return pages


def _claim_attempt(doc, store, page_count):
    """Persist before dispatch, so a recovered worker cannot silently re-bill."""
    blob = doc.get('_blob', '')
    match = re.fullmatch(r'documents/([a-zA-Z0-9_-]+)/([a-zA-Z0-9_-]+)\.pdf', blob)
    if not match or match[2] != doc.get('id') or not callable(getattr(store, 'update', None)):
        raise OCRError('Durable OCR attempt tracking is unavailable; no OCR request was sent.')
    attempt = {'state': 'reserved', 'at': datetime.now(timezone.utc).isoformat(), 'pages': page_count}
    def claim(review):
        source = next((item for item in review.get('documents', []) if item.get('id') == doc['id']), None)
        if source is None or source.get('_blob') != blob or source.get('sha256') != doc.get('sha256'):
            raise OCRError('OCR source changed before dispatch; no request was sent.')
        if source.get('_ocr_attempt'):
            raise OCRError('An OCR attempt was already recorded; automatic retry is disabled. This document remains unresolved.')
        source['_ocr_attempt'] = attempt.copy()
    store.update(match[1], claim)
    doc['_ocr_attempt'] = attempt.copy()


def _authorized_session():
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
    # Even an auth challenge must not replay the billed POST automatically.
    return AuthorizedSession(credentials, max_refresh_attempts=0)


def extract_ocr(data, doc, parsed, store):
    """OCR only after the bounded parser positively identifies unreadable pages."""
    resource, region, version, maximum = _configuration()
    pages = parsed.get('pages', [])
    count = len(pages)
    if (parsed.get('error_code') != 'no_readable_text' or not parsed.get('ocr_eligible')
            or not 1 <= count <= MAX_PAGES or len(data) > MAX_BYTES or not data.startswith(b'%PDF-')):
        raise OCRError('This PDF is not eligible for OCR fallback.')
    if doc.get('_ocr_attempt'):
        raise OCRError('An OCR attempt was already recorded; automatic retry is disabled. This document remains unresolved.')
    take_limit = getattr(store, 'take_limit', None)
    if not callable(take_limit):
        raise OCRError('Shared OCR page quota is unavailable; no request was sent.')
    # Atomic per-document claim precedes quota; crashes fail closed without retry.
    _claim_attempt(doc, store, count)
    if not take_limit('document-ai-ocr-pages', maximum=maximum, amount=count):
        doc['_ocr_attempt']['state'] = 'quota_denied'
        raise OCRError('The shared daily OCR page limit has been reached; this document remains unresolved.')
    doc['_ocr_attempt']['state'] = 'dispatched'
    session = response = None
    try:
        session = _authorized_session()
        response = session.post(
            f'https://{region}-documentai.googleapis.com/v1/{resource}:process',
            json={'rawDocument': {'content': base64.b64encode(data).decode('ascii'), 'mimeType': 'application/pdf'},
                  'imagelessMode': True, 'fieldMask': 'text,pages.pageNumber,pages.layout'},
            timeout=(10, 60), allow_redirects=False, stream=True)
        if response.status_code != 200:
            raise OCRError(f'Document OCR failed (HTTP {response.status_code}); no automatic retry was made.')
        body = bytearray()
        for chunk in response.iter_content(chunk_size=65536):
            body.extend(chunk)
            if len(body) > MAX_RESPONSE_BYTES:
                raise OCRError('OCR response exceeds the safe document limit.')
        ocr_pages = parse_ocr_response(json.loads(body), count)
        unreadable = set(parsed.get('unreadable_pages', []))
        combined = []
        for native, ocr in zip(pages, ocr_pages):
            if native['page'] in unreadable:
                if len(ocr['text'].strip()) < 20:
                    raise OCRError('OCR could not read every scanned page; this document remains unresolved.')
                combined.append(ocr)
            else:
                combined.append({**native, 'extraction_method': 'native_pdf'})
        if sum(len(page['text']) for page in combined) > MAX_TEXT:
            raise OCRError('Extracted text exceeds the document limit.')
        doc['_ocr_attempt']['state'] = 'completed'
        return {'pages': combined, 'extraction_method': 'document_ai_ocr' if len(unreadable) == count else 'native_pdf_with_ocr',
                'extraction_version': EXTRACTION_VERSION,
                'ocr': {'provider': 'Google Document AI', 'region': region, 'configured_processor_version': version,
                        'pages_reserved': count, 'ocr_pages': sorted(unreadable), 'requires_human_verification': True,
                        'warning': OCR_WARNING}}
    except OCRError:
        raise
    except Exception:
        raise OCRError('Document OCR did not complete; no automatic retry was made. This document remains unresolved.') from None
    finally:
        for handle in (response, session):
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
