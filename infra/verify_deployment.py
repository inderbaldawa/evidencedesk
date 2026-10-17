#!/usr/bin/env python3
"""Operator-run live verification. Default prints a plan without network calls.

--read-only checks public HTTP. --resources adds ADC infrastructure reads.
--exercise creates two anonymous identities and isolated synthetic reviews/uploads.
--allow-ai additionally dispatches ONE fresh review through the shared cloud ledger.
No token/config values are printed or written in the sanitized receipt.
"""
import argparse
import os
import hashlib
import json
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit
import requests

ROOT = Path(__file__).resolve().parents[1]
PROJECT = os.environ.get('GOOGLE_CLOUD_PROJECT', 'your-gcp-project')
REGION = 'asia-south1'
BUCKET = PROJECT + '-evidencedesk'
BASE = f'projects/{PROJECT}/locations/{REGION}'
WEB = f'evidencedesk-web@{PROJECT}.iam.gserviceaccount.com'
WORKER = f'evidencedesk-worker@{PROJECT}.iam.gserviceaccount.com'
BUILD = f'evidencedesk-build@{PROJECT}.iam.gserviceaccount.com'
DB = f'projects/{PROJECT}/databases/evidencedesk'


class Verification:
    def __init__(self, args):
        self.args, self.checks = args, []
        self.url = args.url.rstrip('/')
        self.cloud = None
        self.created = []

    def check(self, label, condition):
        self.checks.append({'check': label, 'passed': bool(condition)})
        print(('PASS ' if condition else 'FAIL ') + label, flush=True)
        if not condition:
            raise RuntimeError(label)

    def api(self, method, path, token=None, expected=200, **kwargs):
        headers = {'Origin': self.url} if method != 'GET' else {}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        # A fresh HTTP connection on each request rules out cookie/session affinity.
        result = requests.request(method, self.url + path, headers=headers, timeout=65, allow_redirects=False, **kwargs)
        self.check(f'{method} {path.split("?")[0]} HTTP {expected}', result.status_code == expected)
        return result

    def cloud_get(self, url):
        if self.cloud is None:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession
            credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
            self.cloud = AuthorizedSession(credentials)
        result = self.cloud.get(url, timeout=45)
        if result.status_code != 200:
            raise RuntimeError('Cloud resource read rejected (HTTP ' + str(result.status_code) + ')')
        return result.json()

    def resources(self):
        web = self.cloud_get(f'https://run.googleapis.com/v2/{BASE}/services/evidencedesk-web')
        job = self.cloud_get(f'https://run.googleapis.com/v2/{BASE}/jobs/evidencedesk-worker')
        template, task = web['template'], job['template']['template']
        wc, jc = template['containers'][0], task['containers'][0]
        self.check('Cloud Run URL matches the inspected service', web['uri'].rstrip('/') == self.url)
        self.check('Web identity/resources/timeouts', template['serviceAccount'] == WEB and wc['resources']['limits'] == {'cpu': '1', 'memory': '512Mi'} and template['timeout'] == '60s' and template['maxInstanceRequestConcurrency'] == 8)
        scaling = template.get('scaling', {})
        self.check('Web min0 max2 and request CPU', scaling.get('minInstanceCount', 0) == 0 and scaling.get('maxInstanceCount') == 2 and wc['resources'].get('cpuIdle', True) is True)
        self.check('Web service cap/public ingress/no startup boost', web.get('scaling', {}).get('maxInstanceCount') == 2 and web.get('ingress') == 'INGRESS_TRAFFIC_ALL' and wc['resources'].get('startupCpuBoost', False) is False)
        self.check('Worker identity/resources/retries', task['serviceAccount'] == WORKER and jc['resources']['limits'] == {'cpu': '1', 'memory': '1Gi'} and task['timeout'] == '900s' and task['maxRetries'] == 1 and job['template']['taskCount'] == 1 and job['template']['parallelism'] == 1)
        self.check('Worker command and identical immutable image', jc.get('command') == ['python'] and jc.get('args') == ['-m', 'app.backend.worker'] and wc['image'] == jc['image'] and '@sha256:' in wc['image'])
        for label, container, enabled in [('web', wc, '0'), ('worker', jc, '1')]:
            env = {item['name']: item.get('value') for item in container.get('env', [])}
            self.check(label + ' named storage/shared budget configuration', env.get('GOOGLE_CLOUD_PROJECT') == PROJECT and env.get('FIRESTORE_DATABASE') == 'evidencedesk' and env.get('EVIDENCEDESK_BUCKET') == BUCKET and env.get('EVIDENCEDESK_BUDGET_BACKEND') == 'firestore' and env.get('EVIDENCEDESK_BUDGET_DOCUMENT') == 'budgets/development' and env.get('EVIDENCEDESK_ENABLE_AI') == enabled)
        database = self.cloud_get(f'https://firestore.googleapis.com/v1/{DB}')
        self.check('Named Firestore regional and delete protected', database['locationId'] == REGION and database['type'] == 'FIRESTORE_NATIVE' and database.get('deleteProtectionState') == 'DELETE_PROTECTION_ENABLED')
        default = self.cloud_get(f'https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)')
        self.check('Existing default database remains in US', default['locationId'] == 'nam5' or default['locationId'].startswith('us-'))
        bucket = self.cloud_get(f'https://storage.googleapis.com/storage/v1/b/{BUCKET}')
        self.check('Bucket regional, uniform and public prevented', bucket['location'].lower() == REGION and bucket['iamConfiguration']['uniformBucketLevelAccess']['enabled'] and bucket['iamConfiguration']['publicAccessPrevention'] == 'enforced')
        policy = self.project_policy()
        bindings = policy.get('bindings', [])
        for who, allowed in ((WEB, {'roles/datastore.user', 'roles/firebaseauth.viewer'}), (WORKER, {'roles/datastore.user', 'roles/aiplatform.user'}), (BUILD, {'roles/logging.logWriter', 'roles/serviceusage.serviceUsageConsumer'})):
            self.check(who.split('@')[0] + ' project roles stay within reviewed scope', all(b['role'] in allowed for b in bindings if 'serviceAccount:' + who in b['members']))
        for who in (WEB, WORKER):
            grants = [b for b in bindings if 'serviceAccount:' + who in b['members']]
            expected = "resource.name=='" + DB + "'"
            self.check(who.split('@')[0] + ' database IAM condition', any(b['role'] == 'roles/datastore.user' and b.get('condition', {}).get('expression', '').replace(' ', '') == expected for b in grants))
            self.check(who.split('@')[0] + ' no broad project roles', not any(b['role'] in {'roles/owner', 'roles/editor', 'roles/datastore.owner'} or (b['role'] == 'roles/datastore.user' and b.get('condition', {}).get('expression', '').replace(' ', '') != expected) for b in grants))
        self.check('Worker Vertex grant; web lacks Vertex grant', any(b['role'] == 'roles/aiplatform.user' and 'serviceAccount:' + WORKER in b['members'] for b in bindings) and not any(b['role'].startswith('roles/aiplatform.') and 'serviceAccount:' + WEB in b['members'] for b in bindings))
        self.check('Web revoked-token user lookup grant', any(b['role'] == 'roles/firebaseauth.viewer' and 'serviceAccount:' + WEB in b['members'] for b in bindings))
        bp = self.cloud_get(f'https://storage.googleapis.com/storage/v1/b/{BUCKET}/iam?optionsRequestedPolicyVersion=3')['bindings']
        self.check('Bucket scoped runtime access/private IAM', all(any(b['role'] == 'roles/storage.objectAdmin' and 'serviceAccount:' + who in b['members'] for b in bp) for who in (WEB, WORKER)) and not any(set(b['members']) & {'allUsers', 'allAuthenticatedUsers'} for b in bp))
        prefix = f"resource.name.startsWith('projects/_/buckets/{BUCKET}/objects/build-source/')"
        build_grants = [b for b in bp if 'serviceAccount:' + BUILD in b['members']]
        self.check('Build source prefix only', bool(build_grants) and all(b['role'] == 'roles/storage.objectViewer' and b.get('condition', {}).get('expression') == prefix for b in build_grants))
        jp = self.cloud_get(f'https://run.googleapis.com/v2/{BASE}/jobs/evidencedesk-worker:getIamPolicy')['bindings']
        self.check('Private job with web override executor', any(b['role'] == 'roles/run.jobsExecutorWithOverrides' and 'serviceAccount:' + WEB in b['members'] for b in jp) and not any(set(b['members']) & {'allUsers', 'allAuthenticatedUsers'} for b in jp))
        sp = self.cloud_get(f'https://run.googleapis.com/v2/{BASE}/services/evidencedesk-web:getIamPolicy')['bindings']
        self.check('Public web invocation only', any(b['role'] == 'roles/run.invoker' and 'allUsers' in b['members'] for b in sp))
        repo = self.cloud_get(f'https://artifactregistry.googleapis.com/v1/{BASE}/repositories/evidencedesk')
        self.check('Dedicated Docker registry', repo['format'] == 'DOCKER')
        rp = self.cloud_get(f'https://artifactregistry.googleapis.com/v1/{BASE}/repositories/evidencedesk:getIamPolicy')['bindings']
        self.check('Build registry writer scoped to repository', any(b['role'] == 'roles/artifactregistry.writer' and 'serviceAccount:' + BUILD in b['members'] for b in rp))
        sys.path.insert(0, str(ROOT))
        from app.backend.budget_cloud import _validate
        def decode(value):
            if 'mapValue' in value:
                return {k: decode(v) for k, v in value['mapValue'].get('fields', {}).items()}
            if 'integerValue' in value:
                return int(value['integerValue'])
            for key in ('doubleValue', 'booleanValue', 'stringValue', 'nullValue'):
                if key in value:
                    return value[key]
            raise ValueError('Unsupported ledger field encoding')
        _validate({k: decode(v) for k, v in self.ledger().items()})
        self.check('Shared budget schema/model/pricing/counters valid', True)

    def project_policy(self):
        # getIamPolicy is a read-only POST, unlike all provisioning calls.
        self.cloud_get(f'https://firestore.googleapis.com/v1/{DB}')
        response = self.cloud.post(f'https://cloudresourcemanager.googleapis.com/v1/projects/{PROJECT}:getIamPolicy', json={'options': {'requestedPolicyVersion': 3}}, timeout=45)
        if response.status_code != 200:
            raise RuntimeError('Project IAM policy read rejected')
        return response.json()

    def public(self):
        self.check('Public landing', '<html' in self.api('GET', '/').text.lower())
        health = self.api('GET', '/api/health').json()
        self.check('Cloud store health', health.get('storage') == 'cloud')
        session = self.api('GET', '/api/session').json()
        self.config = session.get('firebase_config', {})
        self.check('Dedicated Firebase config', session.get('auth_mode') == 'firebase' and self.config.get('projectId') == PROJECT and self.config.get('appId') and self.config.get('apiKey'))
        if self.args.firebase_config:
            configured = json.loads(self.args.firebase_config.read_text())
            self.check('Public config matches dedicated local app', all(self.config.get(k) == configured.get(k) for k in ('projectId', 'appId', 'apiKey')))
        self.sample = self.api('GET', '/api/sample').json()
        self.check('Actual completed synthetic read-only sample', self.sample.get('read_only') is True and self.sample.get('synthetic') is True and self.sample['status'] == 'complete' and len(self.sample['findings']) == 6)
        for doc in self.sample['documents']:
            data = self.api('GET', doc['file_url']).content
            self.check('Public sample source hash ' + doc['name'], data.startswith(b'%PDF') and hashlib.sha256(data).hexdigest() == doc['sha256'])
        self.check('Public sample PDF export', self.api('GET', '/api/reviews/sample/export?format=pdf').content.startswith(b'%PDF'))
        self.api('POST', '/api/reviews', expected=401, json={})
        self.api('POST', '/api/reviews/sample', expected=401)

    def signup(self):
        response = requests.post('https://identitytoolkit.googleapis.com/v1/accounts:signUp', params={'key': self.config['apiKey']}, json={'returnSecureToken': True}, timeout=30)
        self.check('Anonymous Firebase identity creation', response.status_code == 200)
        data = response.json()
        return data['idToken'], data['localId']

    def exercise(self):
        a, auid = self.signup()
        b, buid = self.signup()
        self.check('Distinct anonymous users', auid != buid)
        ca = self.api('POST', '/api/reviews/sample', a).json()
        cb = self.api('POST', '/api/reviews/sample', b).json()
        self.created.extend([ca['id'], cb['id']])
        self.check('Independent editable sample clones', ca['id'] != cb['id'] and not ca['read_only'] and not cb['read_only'])
        self.api('POST', '/api/reviews/sample/findings/' + self.sample['findings'][0]['id'] + '/decision', a, expected=403, json={'decision': 'unresolved', 'note': 'Synthetic read-only sample protection test.'})
        for token, own, other in ((a, ca, cb), (b, cb, ca)):
            self.api('GET', f"/api/reviews/{own['id']}", token)
            self.api('GET', f"/api/reviews/{other['id']}", token, expected=404)
            self.api('GET', f"/api/reviews/{other['id']}/export?format=json", token, expected=404)
            self.api('GET', f"/api/reviews/{other['id']}/export?format=pdf", token, expected=404)
            self.api('GET', other['documents'][0]['file_url'], token, expected=404)
            fid = other['findings'][0]['id']
            self.api('POST', f"/api/reviews/{other['id']}/findings/{fid}/decision", token, expected=404, json={'decision': 'accepted'})
        for doc in ca['documents']:
            payload = self.api('GET', doc['file_url'], a).content
            self.check('Cloned source reference hash ' + doc['name'], hashlib.sha256(payload).hexdigest() == doc['sha256'])
        self.api('GET', f"/api/reviews/{ca['id']}", expected=401)
        self.api('GET', ca['documents'][0]['file_url'], expected=401)
        finding = ca['findings'][0]['id']
        self.api('POST', f"/api/reviews/{ca['id']}/findings/{finding}/decision", a, json={'decision': 'clarification_requested', 'note': 'Synthetic deployment verification. Follow-up draft: Please confirm source scope.'})
        fresh = self.api('GET', f"/api/reviews/{ca['id']}", a).json()
        self.check('Reviewer decision persists on fresh HTTP request', fresh['findings'][0]['reviewer']['decision'] == 'clarification_requested')
        self.check('Other clone decision isolated', self.api('GET', f"/api/reviews/{cb['id']}", b).json()['findings'][0]['reviewer']['decision'] == 'unreviewed')
        self.check('Private PDF export authorized', self.api('GET', f"/api/reviews/{ca['id']}/export?format=pdf", a).content.startswith(b'%PDF'))
        firestore_url = f'https://firestore.googleapis.com/v1/{DB}/documents'
        headers = {'Authorization': 'Bearer ' + a}
        denied = requests.get(firestore_url + '/reviews/sample', headers=headers, timeout=30)
        self.check('Direct browser Firestore read denied', denied.status_code == 403)
        denied = requests.post(firestore_url + '/preflight_browser_denial', params={'documentId': uuid.uuid4().hex}, headers=headers, json={'fields': {'synthetic': {'booleanValue': True}}}, timeout=30)
        self.check('Direct browser Firestore write denied', denied.status_code == 403)
        review = self.api('POST', '/api/reviews', a, json={'name': 'Synthetic cloud durability verification', 'policy_version': '3.0'}).json()
        rid = review['id']
        self.created.append(rid)
        files = [('files', (p.name, p.read_bytes(), 'application/pdf')) for p in sorted((ROOT / 'data/compact/pdfs').glob('*.pdf'))]
        uploaded = self.api('POST', f'/api/reviews/{rid}/documents', a, files=files).json()
        self.check('Fresh synthetic upload persists', uploaded['coverage']['submitted'] == 10 and len(self.api('GET', f'/api/reviews/{rid}', a).json()['documents']) == 10)
        self.api('GET', f'/api/reviews/{rid}', b, expected=404)
        if not self.args.allow_ai:
            print('SKIP model dispatch: --allow-ai not provided. Upload remains private and incomplete.')
            return
        if not self.args.resources:
            raise RuntimeError('--allow-ai requires --resources to verify shared cloud ledger durability')
        before = self.ledger()
        self.check('Approved shared cloud ledger enabled before dispatch', before.get('enabled', {}).get('booleanValue') is True)
        queued = self.api('POST', f'/api/reviews/{rid}/analyze', a).json()  # exactly one dispatch; no automatic retry
        self.check('Fresh upload accepted for durable processing', queued['status'] in ('queued', 'processing', 'complete'))
        deadline = time.monotonic() + self.args.wait_seconds
        last = None
        while time.monotonic() < deadline:
            review = self.api('GET', f'/api/reviews/{rid}', a).json()
            progress = (review['status'], review['coverage']['processed'], review['coverage']['failed'])
            if progress != last:
                print('PROGRESS status=%s processed=%s failed=%s' % progress, flush=True)
                last = progress
            if review['status'] not in ('queued', 'processing'):
                break
            time.sleep(15)
        self.check('Fresh worker analysis completes with all sources', review['status'] == 'complete' and review['coverage']['processed'] == 10 and review['coverage']['failed'] == 0 and len(review['findings']) == 6)
        self.check('Fresh output uses current real model analysis', bool(review['analysis'].get('generated_at')) and not review['analysis'].get('stale'))
        persisted = self.cloud_get(f'https://storage.googleapis.com/storage/v1/b/{BUCKET}/o/' + quote(f'reviews/{rid}.json', safe='') + '?alt=media')
        self.check('GCS authoritative completed review and matching owner', persisted['status'] == review['status'] and persisted['_owner'] == auid and persisted['findings'] == review['findings'])
        self.check('Dispatch completed by a fenced Cloud Run execution', bool(persisted.get('_analysis_run_id')) and persisted.get('_analysis_run_id') == persisted.get('_completed_run_id') and persisted.get('_processing_lease', {}).get('owner', '').startswith('evidencedesk-worker-'))
        execution_id = persisted['_processing_lease']['owner'].split(':')[0]
        execution = self.cloud_get(f'https://run.googleapis.com/v2/{BASE}/jobs/evidencedesk-worker/executions/{execution_id}')
        self.check('Worker execution exists with private worker identity', execution['template']['serviceAccount'] == WORKER)
        indexed = self.cloud_get(f'https://firestore.googleapis.com/v1/{DB}/documents/reviews/{rid}')['fields']
        self.check('Firestore projection includes completed artifact revision', indexed['status']['stringValue'] == 'complete' and int(indexed['artifact_revision']['integerValue']) >= persisted['_revision'])
        after = self.ledger()
        number = lambda f, k: float(f[k].get('integerValue', f[k].get('doubleValue', 0)))
        self.check('Shared ledger recorded fresh work', number(after, 'calls') > number(before, 'calls') and number(after, 'cost_usd') >= number(before, 'cost_usd'))
        self.api('GET', f'/api/reviews/{rid}/export?format=json', b, expected=404)

    def ledger(self):
        return self.cloud_get(f'https://firestore.googleapis.com/v1/{DB}/documents/budgets/development')['fields']

    def receipt(self, error=None):
        out = self.args.receipt
        out.parent.mkdir(parents=True, exist_ok=True)
        receipt = {'checked_at': datetime.now(timezone.utc).isoformat(), 'url': self.url,
                   'checks': self.checks, 'passed': error is None, 'failure_type': type(error).__name__ if error else None,
                   'resources_checked': self.args.resources, 'identities_exercised': self.args.exercise,
                   'model_dispatch_requested': self.args.allow_ai, 'created_review_ids': self.created,
                   'limits': ['Fresh connections demonstrate persisted state, not a forced container restart.',
                              'Two anonymous test accounts and private synthetic reviews remain; no cleanup is automatic.',
                              'No account tokens, Firebase config values or raw cloud responses are saved.']}
        out.write_text(json.dumps(receipt, indent=2) + '\n')
        out.chmod(0o600)
        print('Sanitized receipt saved: ' + str(out))
        if self.cloud:
            self.cloud.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url')
    parser.add_argument('--firebase-config', type=Path)
    parser.add_argument('--read-only', action='store_true')
    parser.add_argument('--resources', action='store_true')
    parser.add_argument('--exercise', action='store_true')
    parser.add_argument('--allow-ai', action='store_true')
    parser.add_argument('--wait-seconds', type=int, default=1200)
    parser.add_argument('--receipt', type=Path, default=ROOT / 'infra/.local/live-verification.json')
    args = parser.parse_args()
    if not (args.read_only or args.exercise or args.resources or args.allow_ai):
        print('PLAN ONLY. Use --url HTTPS_CLOUD_RUN_URL --read-only [--resources] to read deployment. Add --exercise to create two anonymous users/private synthetic reviews; add --allow-ai --resources for one fresh analysis using the shared ledger. No network calls made.')
        return
    parsed = urlsplit(args.url or '')
    if parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith('.run.app') or parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username:
        parser.error('An exact HTTPS *.run.app service origin is required')
    if args.allow_ai and (not args.exercise or not args.resources):
        parser.error('--allow-ai requires --exercise --resources')
    if not 60 <= args.wait_seconds <= 1800:
        parser.error('--wait-seconds must be 60..1800')
    verify = Verification(args)
    failure = None
    try:
        if args.resources:
            verify.resources()
        verify.public()
        if args.exercise:
            verify.exercise()
    except Exception as exc:
        failure = exc
        print('STOP verification: ' + type(exc).__name__ + '. No automatic job retry. Inspect failed check; raw exceptions suppressed to avoid credential-bearing URLs.', file=sys.stderr)
    finally:
        verify.receipt(failure)
    if failure:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
