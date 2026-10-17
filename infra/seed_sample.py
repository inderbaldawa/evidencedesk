#!/usr/bin/env python3
"""Seed the reviewed synthetic output and its exact PDFs; default is local plan only."""
import argparse
import copy
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PROJECT = os.environ.get('GOOGLE_CLOUD_PROJECT', 'your-gcp-project')
BUCKET = PROJECT + '-evidencedesk'


def prepare(source):
    from pypdf import PdfReader
    raw = source.read_bytes()
    review = json.loads(raw)
    manifest = json.loads((ROOT / 'data/compact/manifest.json').read_text())
    expected = hashlib.sha256((ROOT / 'evals/fixtures.expected.json').read_bytes()).hexdigest()
    if manifest.get('synthetic') is not True or manifest.get('expected_manifest_sha256') != expected:
        raise ValueError('Synthetic manifest provenance failed')
    if review.get('synthetic') is not True or review.get('status') != 'complete':
        raise ValueError('Only a completed genuine synthetic analysis may seed the sample')
    if not review.get('analysis', {}).get('model') or not review.get('analysis', {}).get('generated_at'):
        raise ValueError('Missing actual analysis provenance')
    if len(review.get('findings', [])) != 6 or review.get('analysis', {}).get('stale'):
        raise ValueError('Expected six current actual findings')
    by_name = {d['name']: d for d in manifest['documents']}
    if set(by_name) != {d['name'] for d in review['documents']} or len(review['documents']) != len(by_name):
        raise ValueError('Sample documents differ from the approved compact synthetic pack')
    payloads = {}
    for doc in review['documents']:
        item = by_name[doc['name']]
        if item.get('synthetic') is not True or Path(doc['name']).name != doc['name']:
            raise ValueError('Non-synthetic or unsafe source document')
        path = ROOT / 'data/compact/pdfs' / doc['name']
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != doc['sha256'] or digest != item['sha256'] or doc['status'] != 'processed':
            raise ValueError('Source PDF hash/status does not match reviewed analysis')
        reader = PdfReader(path)
        if len(reader.pages) != doc['page_count'] or any('SYNTHETIC DEMONSTRATION DATA' not in p.extract_text() for p in reader.pages):
            raise ValueError('Source PDF is not the complete labeled synthetic artifact')
        doc['_blob'] = f'documents/sample/{digest}.pdf'
        payloads[doc['_blob']] = data
    if review['coverage']['processed'] != len(payloads) or review['coverage']['failed']:
        raise ValueError('Sample coverage is incomplete')
    ids = {d['id']: d for d in review['documents']}
    normalize = lambda value: ' '.join(value.split())
    for finding in review['findings']:
        if finding.get('reviewer', {}).get('decision') != 'unreviewed':
            raise ValueError('Shared sample must not claim a human decision')
        for citation in finding['citations']:
            doc = ids[citation['document_id']]
            page = PdfReader(ROOT / 'data/compact/pdfs' / doc['name']).pages[citation['page'] - 1]
            if citation['page'] < 1 or normalize(citation['quote']) not in normalize(page.extract_text()):
                raise ValueError('Actual finding citation is not literal on its source PDF page')
    source_hash = hashlib.sha256(raw).hexdigest()
    review.update(id='sample', _owner='public-synthetic-sample', read_only=True, _seed_sha256=source_hash)
    return review, payloads, source_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'evals/compact-actual.json')
    parser.add_argument('--source-sha256', help='Required with --apply; bind the reviewed local source bytes')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    review, payloads, source_hash = prepare(args.source)
    print(json.dumps({'mode': 'apply' if args.apply else 'local-plan', 'project': PROJECT, 'bucket': BUCKET,
                      'database': 'evidencedesk', 'review': 'sample', 'documents': len(payloads),
                      'source_sha256': source_hash, 'model_calls': 0}, indent=2))
    if not args.apply:
        print('No cloud clients initialized. --apply requires the printed --source-sha256.')
        return
    if args.source_sha256 != source_hash:
        raise ValueError('Supply the exact reviewed --source-sha256 before seeding')
    os.environ.update(GOOGLE_CLOUD_PROJECT=PROJECT, FIRESTORE_DATABASE='evidencedesk',
                      EVIDENCEDESK_BUCKET=BUCKET, EVIDENCEDESK_STORAGE='cloud',
                      EVIDENCEDESK_BUDGET_BACKEND='firestore', EVIDENCEDESK_BUDGET_DOCUMENT='budgets/development')
    from google.api_core.exceptions import PreconditionFailed
    from app.backend.cloud_store import CloudStore
    store = CloudStore()
    store.bucket.reload()
    iam = store.bucket.iam_configuration
    if iam.public_access_prevention != 'enforced' or not iam.uniform_bucket_level_access_enabled:
        raise ValueError('Bucket must enforce private uniform access before sample upload')
    existing, _ = store._read('sample')
    if existing and existing.get('_seed_sha256') != source_hash:
        raise ValueError('A different sample already exists; refusing replacement')
    for key, data in payloads.items():
        blob = store.bucket.blob(key)
        try:
            blob.upload_from_string(data, content_type='application/pdf', if_generation_match=0)
        except PreconditionFailed:
            if hashlib.sha256(blob.download_as_bytes()).digest() != hashlib.sha256(data).digest():
                raise ValueError('Existing sample PDF content differs; refusing replacement')
    if not existing:
        store.put(copy.deepcopy(review))  # create-only GCS CAS; preserves genuine findings/history
    saved = store.get('sample')
    for doc in saved['documents']:
        if hashlib.sha256(store.read_blob(doc['_blob'])).hexdigest() != doc['sha256']:
            raise ValueError('Seeded source reference verification failed')
    print('Sample and every clone-compatible source PDF reference verified. No model calls or existing sample replacement.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Seed stopped: {type(exc).__name__}. Inspect local inputs/permissions; no automatic replacement.', file=sys.stderr)
        raise SystemExit(1)
