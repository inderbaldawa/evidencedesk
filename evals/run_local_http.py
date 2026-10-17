"""Fresh local upload -> durable queue -> real worker -> isolation/export check.

Requires running localhost:8080 and explicitly enabled, budgeted AI worker env.
Never reads expected findings into the analysis pipeline.
"""
import json
import subprocess
import sys
import time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:8080'


def main():
    if '--run' not in sys.argv:
        raise SystemExit('Explicit --run required; this queues real model work.')
    client = requests.Session()
    client.get(BASE + '/api/session').raise_for_status()
    response = client.post(BASE + '/api/reviews', json={
        'name': 'Fresh HTTP workflow verification', 'vendor': 'Nimbus Support',
        'service': 'Customer Support Platform', 'environment': 'production',
        'period': '2026-10', 'policy_version': '3.0'})
    response.raise_for_status()
    rid = response.json()['id']
    names = ['policy-v3.pdf', 'questionnaire-202610.pdf', 'backup-inventory-202610.pdf']
    files = [('files', (name, (ROOT/'data/compact/pdfs'/name).read_bytes(), 'application/pdf')) for name in names]
    files.extend([
        ('files', ('questionnaire-duplicate.pdf', (ROOT/'data/compact/pdfs/questionnaire-202610.pdf').read_bytes(), 'application/pdf')),
        ('files', ('no-extractable-text.pdf', (ROOT/'data/adversarial/no-extractable-text.pdf').read_bytes(), 'application/pdf')),
        ('files', ('malformed.pdf', (ROOT/'data/adversarial/malformed.pdf').read_bytes(), 'application/pdf')),
        ('files', ('unsupported.docx', (ROOT/'data/adversarial/unsupported.docx').read_bytes(), 'application/octet-stream')),
    ])
    response = client.post(BASE + f'/api/reviews/{rid}/documents', files=files)
    response.raise_for_status()
    before = response.json()
    assert before['coverage']['submitted'] == 7
    assert before['coverage']['duplicates'] == 1
    start = time.monotonic()
    response = client.post(BASE + f'/api/reviews/{rid}/analyze')
    response.raise_for_status()
    assert response.json()['status'] == 'queued'
    subprocess.run([sys.executable, '-m', 'app.backend.worker', '--once'], cwd=ROOT, check=True)
    response = client.get(BASE + f'/api/reviews/{rid}')
    response.raise_for_status()
    review = response.json()
    (ROOT/'evals/local-http-actual.json').write_text(json.dumps(review, indent=2))
    cov = review['coverage']
    assert review['status'] == 'incomplete', review['status']
    assert cov['processed'] == 3 and cov['failed'] == 3 and cov['duplicates'] == 1, cov
    conflict = next(f for f in review['findings'] if f['control_id'] == 'backup_location')
    assert conflict['status'] == 'conflicting_evidence', conflict['status']
    response = client.post(BASE + f'/api/reviews/{rid}/findings/{conflict["id"]}/decision', json={
        'decision': 'clarification_requested', 'note': 'Fresh HTTP review: reconcile Singapore replica with India-only claim. Unreadable files remain unresolved.'})
    response.raise_for_status()
    private_paths = [f'/api/reviews/{rid}', f'/api/reviews/{rid}/export?format=json',
                     f'/api/reviews/{rid}/documents/{review["documents"][0]["id"]}/file']
    outsider = requests.Session()
    outsider.get(BASE + '/api/session').raise_for_status()
    assert all(outsider.get(BASE + path).status_code == 404 for path in private_paths)
    exported = client.get(BASE + f'/api/reviews/{rid}/export?format=json')
    exported.raise_for_status()
    assert next(f for f in exported.json()['findings'] if f['id'] == conflict['id'])['reviewer']['decision'] == 'clarification_requested'
    source = client.get(BASE + f'/api/reviews/{rid}/documents/{review["documents"][0]["id"]}/file')
    source.raise_for_status()
    assert source.content == (ROOT/'data/compact/pdfs/policy-v3.pdf').read_bytes()
    pdf = client.get(BASE + f'/api/reviews/{rid}/export?format=pdf')
    pdf.raise_for_status()
    assert pdf.content.startswith(b'%PDF-')
    (ROOT/'evals/artifacts/fresh-http-evidence-pack.pdf').write_bytes(pdf.content)
    summary = {'review_id': rid, 'status': review['status'], 'coverage': cov,
               'http_to_result_seconds': round(time.monotonic()-start,3),
               'analysis': review['analysis'], 'isolation': 'three private routes denied to second identity',
               'source_bytes_match': True, 'decision_exported': True, 'pdf_exported': True}
    (ROOT/'evals/local-http-summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
