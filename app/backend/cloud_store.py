"""Authoritative GCS review CAS with fenced worker leases and a repairable index.

Firestore is a monotonic projection of the GCS artifact, not a separate lease
lock: checking a Firestore lock before writing GCS would leave a fencing race.
"""
import json
import hashlib
import logging
import os
import time
import uuid
from google.cloud import firestore, storage
from google.api_core.exceptions import NotFound, PreconditionFailed
from .store import now

logger = logging.getLogger(__name__)
LEASE_SECONDS = 90
QUEUE_TIMEOUT_SECONDS = 900


class ReviewLeaseLost(RuntimeError):
    pass


class ReviewRunObsolete(RuntimeError):
    """The dispatch was superseded or has already completed successfully."""


class DispatchUncertain(RuntimeError):
    """The job may have started; retain its run ID and never resend automatically."""

    def __init__(self, run_id):
        self.run_id = run_id
        super().__init__('Processing dispatch could not be confirmed. Waiting for worker status; dispatch will not be automatically repeated.')


class _NoMutation(Exception):
    def __init__(self, result=None):
        self.result = result


class CloudStore:
    def __init__(self):
        self.project = os.environ['GOOGLE_CLOUD_PROJECT']
        self.region = os.environ.get('EVIDENCEDESK_REGION', 'asia-south1')
        self.db = firestore.Client(project=self.project, database=os.environ['FIRESTORE_DATABASE'])
        self.bucket = storage.Client(project=self.project).bucket(os.environ['EVIDENCEDESK_BUCKET'])

    def _ref(self, review_id):
        return self.db.collection('reviews').document(review_id)

    def _blob(self, review_id):
        return self.bucket.blob(f'reviews/{review_id}.json')

    def _index(self, review, generation):
        """A delayed older artifact can never replace a newer Firestore view."""
        ref = self._ref(review['id'])
        generation = int(generation)
        revision = int(review.get('_revision', 0))
        metadata = {k: review[k] for k in ('id', 'name', 'vendor', 'service', 'environment', 'period', 'policy_version', 'status', 'created_at', 'updated_at', 'coverage')}
        metadata.update(owner=review['_owner'], artifact=f'reviews/{review["id"]}.json', artifact_generation=generation, artifact_revision=revision)
        metadata['analysis'] = {k: v for k, v in review.get('analysis', {}).items() if k != 'reconciliation_cache'}
        findings = review.get('findings', [])
        documents = review.get('documents', [])
        metadata['finding_ids'] = [f['id'] for f in findings]
        metadata['document_ids'] = [d['id'] for d in documents]
        metadata['processing_execution'] = review.get('_processing_lease', {}).get('owner')
        metadata['processing_lease'] = review.get('_processing_lease', {}).get('expires_at', 0)
        metadata['analysis_run_id'] = review.get('_analysis_run_id')

        records = {d['id']: {k: v for k, v in d.items() if k not in ('pages', 'extraction') and not k.startswith('_')} for d in documents}
        finding_records = {f['id']: f for f in findings}
        hashes = lambda values: {key: hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest() for key, value in values.items()}
        metadata['finding_hashes'] = hashes(finding_records)
        metadata['document_hashes'] = hashes(records)

        @firestore.transactional
        def publish(transaction):
            previous = ref.get(transaction=transaction).to_dict() or {}
            # GCS generations are opaque unique IDs, NOT ordered version counters.
            # _revision increments inside the same successful artifact CAS.
            if int(previous.get('artifact_revision', -1)) >= revision:
                return False
            transaction.set(ref, metadata, merge=True)
            for kind, values, hash_key in (('findings', finding_records, 'finding_hashes'), ('documents', records, 'document_hashes')):
                for identity, record in values.items():
                    if previous.get(hash_key, {}).get(identity) != metadata[hash_key][identity]:
                        transaction.set(ref.collection(kind).document(identity), {**record, 'artifact_generation': generation})
            for kind, current in (('findings', metadata['finding_ids']), ('documents', metadata['document_ids'])):
                old_key = 'finding_ids' if kind == 'findings' else 'document_ids'
                for removed in set(previous.get(old_key, [])) - set(current):
                    transaction.delete(ref.collection(kind).document(removed))
            return True
        return publish(self.db.transaction())

    def _sync_index(self, review, generation):
        try:
            self._index(review, generation)
        except Exception:
            # The GCS commit already succeeded. Never rerun the user mutation.
            # Next get/update repairs this projection from the actual artifact.
            logger.exception('Review index synchronization failed for %s at generation %s; read repair pending', review['id'], generation)

    def _read(self, review_id):
        # A generation-pinned download prevents mixing metadata and another body.
        for _ in range(6):
            blob = self._blob(review_id)
            try:
                blob.reload()
                generation = int(blob.generation)
                return json.loads(blob.download_as_bytes(if_generation_match=generation)), generation
            except PreconditionFailed:
                continue
            except NotFound:
                return None, None
        raise RuntimeError('Review changed repeatedly while reading; retry.')

    def get(self, review_id):
        review, generation = self._read(review_id)
        if review is None:
            return None
        lease = review.get('_processing_lease', {})
        expired = review.get('status') == 'processing' and lease and lease.get('expires_at', 0) <= time.time()
        queued_too_long = review.get('status') == 'queued' and lease.get('expires_at', 0) <= time.time() and review.get('_queued_at', time.time()) + QUEUE_TIMEOUT_SECONDS <= time.time()
        if expired or queued_too_long:
            def recover(current):
                active = current.get('_processing_lease', {})
                stale = current.get('status') == 'processing' and active and active.get('expires_at', 0) <= time.time()
                stalled = current.get('status') == 'queued' and active.get('expires_at', 0) <= time.time() and current.get('_queued_at', time.time()) + QUEUE_TIMEOUT_SECONDS <= time.time()
                if not (stale or stalled):
                    raise _NoMutation()
                current['status'] = 'failed'
                current['events'].append({'at': now(), 'type': 'worker_interrupted', 'message': 'Processing stopped before completion. Saved progress is retained; retry analysis to continue.'})
            self._mutate(review_id, recover, lease_management=True)
            review, generation = self._read(review_id)
        self._sync_index(review, generation)
        return review

    def put(self, review):
        # A clone must not inherit another review's lease or dispatch identity.
        for key in ('_processing_lease', '_analysis_run_id', '_completed_run_id', '_queued_at', '_job_operation'):
            review.pop(key, None)
        review['_revision'] = 1
        blob = self._blob(review['id'])
        blob.upload_from_string(json.dumps(review), content_type='application/json', if_generation_match=0)
        self._sync_index(review, blob.generation)

    def update(self, review_id, fn, *, lease_token=None):
        return self._mutate(review_id, fn, lease_token=lease_token)

    @staticmethod
    def assert_lease(review, token):
        lease = review.get('_processing_lease', {})
        if lease.get('owner') != token or lease.get('expires_at', 0) <= time.time():
            raise ReviewLeaseLost('Processing lease expired or belongs to another attempt; stale writes are rejected.')

    def _mutate(self, review_id, fn, *, lease_token=None, lease_management=False):
        for _ in range(8):
            review, generation = self._read(review_id)
            if review is None:
                raise KeyError(review_id)
            lease = review.get('_processing_lease', {})
            if not lease_management:
                if lease_token is not None:
                    self.assert_lease(review, lease_token)
                elif lease.get('expires_at', 0) > time.time():
                    raise ReviewLeaseLost('Review is still owned by a processing attempt; retry after it finishes.')
            next_revision = int(review.get('_revision', 0)) + 1
            prior_status = review.get('status')
            try:
                result = fn(review)
            except _NoMutation as skip:
                return skip.result
            if review.get('status') == 'queued' and prior_status != 'queued':
                review['_queued_at'] = time.time()
            review['updated_at'] = now()
            review['_revision'] = next_revision
            blob = self._blob(review_id)
            if lease_token is not None:
                self.assert_lease(review, lease_token)
            try:
                blob.upload_from_string(json.dumps(review), content_type='application/json', if_generation_match=generation)
            except PreconditionFailed:
                continue
            # Deliberately outside the CAS retry block: failure here must not
            # replay a successful decision, audit append or upload mutation.
            self._sync_index(review, blob.generation)
            return result if result is not None else review
        raise RuntimeError('Review changed concurrently; retry the operation.')

    def save_blob(self, key, data):
        self.bucket.blob(key).upload_from_string(data, content_type='application/pdf', if_generation_match=0)

    def read_blob(self, key):
        return self.bucket.blob(key).download_as_bytes()

    def enqueue(self, review_id):
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
        from google.auth.exceptions import TransportError
        from requests.exceptions import ConnectionError, Timeout
        if not self.take_limit('__global_jobs__', 20):
            raise RuntimeError('Daily processing capacity reached.')
        run_id = uuid.uuid4().hex
        def dispatch(review):
            review['_analysis_run_id'] = run_id
            review['_queued_at'] = time.time()
        self.update(review_id, dispatch)
        credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
        session = AuthorizedSession(credentials)
        job = os.environ.get('EVIDENCEDESK_JOB', 'evidencedesk-worker')
        url = f'https://run.googleapis.com/v2/projects/{self.project}/locations/{self.region}/jobs/{job}:run'
        try:
            try:
                result = session.post(url, json={'overrides': {'containerOverrides': [{'env': [{'name': 'EVIDENCEDESK_REVIEW_ID', 'value': review_id}, {'name': 'EVIDENCEDESK_RUN_ID', 'value': run_id}]}]}}, timeout=30, allow_redirects=False)
            except (Timeout, ConnectionError, TransportError) as exc:
                # A lost response does not imply a lost request. Cloud Run may
                # already be executing this run; do not retry this POST.
                raise DispatchUncertain(run_id) from exc
            if 400 <= result.status_code < 500:
                result.raise_for_status()  # Explicit rejection: known failure.
            if not 200 <= result.status_code < 300:
                raise DispatchUncertain(run_id)
            try:
                # Acceptance is final even if this auxiliary projection fails.
                operation = result.json()['name']
                if not isinstance(operation, str) or not operation:
                    raise ValueError('Accepted dispatch has no operation name')
                self._ref(review_id).set({'last_dispatched_operation': operation}, merge=True)
            except Exception:
                logger.exception('Job dispatch accepted for review %s run %s; operation metadata unavailable', review_id, run_id)
        finally:
            try:
                session.close()
            except Exception:
                logger.exception('Dispatch session cleanup failed for review %s run %s', review_id, run_id)

    def take_limit(self, owner, maximum=5):
        import hashlib
        key = hashlib.sha256(owner.encode()).hexdigest() + '-' + now()[:10]
        ref = self.db.collection('limits').document(key)
        @firestore.transactional
        def take(transaction):
            snap = ref.get(transaction=transaction)
            count = (snap.to_dict() or {}).get('count', 0)
            if count >= maximum:
                return False
            transaction.set(ref, {'count': count + 1, 'day': now()[:10]})
            return True
        return take(self.db.transaction())

    def acquire_review(self, review_id, attempt_token, run_id=None):
        def acquire(review):
            if run_id and (review.get('_analysis_run_id') != run_id or review.get('_completed_run_id') == run_id):
                raise ReviewRunObsolete('Dispatch was superseded or already completed.')
            lease = review.get('_processing_lease', {})
            if lease.get('expires_at', 0) > time.time():
                raise _NoMutation(False)
            review['_processing_lease'] = {'owner': attempt_token, 'expires_at': time.time() + LEASE_SECONDS}
            return True
        return self._mutate(review_id, acquire, lease_management=True)

    def heartbeat_review(self, review_id, attempt_token):
        def renew(review):
            self.assert_lease(review, attempt_token)
            review['_processing_lease']['expires_at'] = time.time() + LEASE_SECONDS
        self._mutate(review_id, renew, lease_management=True)
        return True

    def release_review(self, review_id, attempt_token):
        def release(review):
            if review.get('_processing_lease', {}).get('owner') != attempt_token:
                raise _NoMutation(False)
            review['_processing_lease']['expires_at'] = 0
            return True
        return self._mutate(review_id, release, lease_management=True)
