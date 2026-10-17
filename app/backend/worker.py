"""Separate durable worker; every cloud attempt uses a fenced, renewable lease."""
import argparse
import copy
import logging
import os
import threading
import time
import uuid
from .store import get_store, now
from .documents import coverage, extract_document

logger = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 20


def process(review_id, store=None):
    from .pipeline import analyze_review
    store = store or get_store()
    review = store.get(review_id)
    if not review:
        raise ValueError('Unknown review')

    def progress(event):
        def save(r):
            if event.get('type') == 'document_extracted':
                d = next((d for d in r['documents'] if d['id'] == event.get('document_id')), None)
                if d is not None:
                    d.update(extraction=event.get('extraction'), status='processed')
            elif event.get('type') == 'document_failed':
                d = next((d for d in r['documents'] if d['id'] == event.get('document_id')), None)
                if d is not None:
                    d.update(status='failed', error=event.get('message', 'Extraction failed.'))
            elif event.get('type') == 'finding_ready' and event.get('reconciliation_cache'):
                f = event['finding']
                r.setdefault('analysis', {}).setdefault('reconciliation_cache', {})[f['control_id']] = event['reconciliation_cache']
            r['coverage'] = coverage(r)
            r['events'].append({'at': now(), 'type': event.get('type', 'progress'), 'message': event.get('message', 'Source extraction progress saved.')})
            r['events'] = r['events'][-200:]
        store.update(review_id, save)

    try:
        def start(r):
            r['status'] = 'processing'
            r['events'].append({'at': now(), 'type': 'processing', 'message': 'Gemini is extracting and reconciling source evidence.'})
        store.update(review_id, start)
        for source in review['documents']:
            if source.get('_blob') and not source.get('pages') and source['status'] == 'pending':
                extracted = extract_document(copy.deepcopy(source), store)
                def save_source(r):
                    for i, document in enumerate(r['documents']):
                        if document['id'] == extracted['id']:
                            r['documents'][i] = extracted
                            break
                    r['coverage'] = coverage(r)
                    r['events'].append({'at': now(), 'type': 'pdf_extracted', 'message': f"{extracted['name']}: {'text extracted' if extracted['pages'] else extracted.get('error', 'unreadable')}"})
                store.update(review_id, save_source)
        current = store.get(review_id)
        result = analyze_review(current, current['documents'], progress=progress)
        def finish(r):
            if r.get('findings'):
                r.setdefault('_analysis_history', []).append({'analysis': r.get('analysis'), 'findings': copy.deepcopy(r['findings'])})
            r['findings'] = result['findings']
            r['analysis'] = result['analysis']
            r['analysis']['stale'] = False
            r['documents'] = result.get('documents', r['documents'])
            r['coverage'] = coverage(r)
            r['status'] = 'incomplete' if not result['analysis'].get('complete', False) or r['coverage']['failed'] or any(d['status'] in ('pending', 'processing') for d in r['documents']) else 'complete'
            if r.get('_analysis_run_id'):
                r['_completed_run_id'] = r['_analysis_run_id']
            r['events'].append({'at': now(), 'type': 'completed', 'message': 'Analysis completed. Review the evidence and record your decision.'})
        store.update(review_id, finish)
    except Exception as exc:
        def fail(r):
            r['status'] = 'failed'
            r['coverage'] = coverage(r)
            r['events'].append({'at': now(), 'type': 'error', 'message': str(exc)[:400]})
        try:
            store.update(review_id, fail)
        except Exception:
            # In particular, a stale attempt cannot mark its successor failed.
            logger.warning('Could not persist failure for %s; lease may belong to another attempt', review_id)
        raise


class LeaseBoundStore:
    """Bind every worker mutation to the owner token in the same GCS CAS."""
    def __init__(self, store, review_id, token, lost):
        self.store, self.review_id, self.token, self.lost = store, review_id, token, lost

    def _check(self):
        if self.lost.is_set():
            from .cloud_store import ReviewLeaseLost
            raise ReviewLeaseLost('Lease heartbeat failed; this attempt has stopped writing.')

    def get(self, review_id):
        self._check()
        if review_id != self.review_id:
            raise ValueError('Worker can access only its assigned review.')
        review = self.store.get(review_id)
        if review is None:
            raise ValueError('Unknown review')
        self.store.assert_lease(review, self.token)
        return review

    def update(self, review_id, fn):
        self._check()
        if review_id != self.review_id:
            raise ValueError('Worker can update only its assigned review.')
        return self.store.update(review_id, fn, lease_token=self.token)

    def read_blob(self, key):
        self._check()
        return self.store.read_blob(key)


def attempt_identity():
    """Cloud Run retries share execution name; task attempt and nonce distinguish them."""
    return ':'.join((os.environ.get('CLOUD_RUN_EXECUTION', 'manual'), os.environ.get('CLOUD_RUN_TASK_INDEX', '0'), os.environ.get('CLOUD_RUN_TASK_ATTEMPT', '0'), uuid.uuid4().hex))


def run_cloud_review(store, review_id, *, run_id=None, process_fn=None):
    from .cloud_store import LEASE_SECONDS, ReviewRunObsolete
    process_fn = process_fn or process
    token = attempt_identity()
    deadline = time.monotonic() + LEASE_SECONDS + 10
    while True:
        try:
            if store.acquire_review(review_id, token, run_id):
                break
        except ReviewRunObsolete:
            return False
        if time.monotonic() >= deadline:
            raise RuntimeError('Another attempt still owns this review; no work was duplicated.')
        # A retry after a hard-killed attempt waits only for the short lease,
        # instead of immediately consuming its sole retry while a 900s lock lives.
        time.sleep(2)
    stop, lost = threading.Event(), threading.Event()
    def renew():
        while not stop.wait(HEARTBEAT_SECONDS):
            try:
                store.heartbeat_review(review_id, token)
            except Exception:
                lost.set()
                logger.exception('Review heartbeat failed for %s; further writes are fenced', review_id)
                return
    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    try:
        process_fn(review_id, LeaseBoundStore(store, review_id, token, lost))
        return True
    finally:
        stop.set()
        thread.join(timeout=2)
        try:
            store.release_review(review_id, token)
        except Exception:
            logger.exception('Lease release failed for %s; short lease expires automatically', review_id)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--review-id')
    args = parser.parse_args()
    store = get_store()
    review_id = args.review_id or os.environ.get('EVIDENCEDESK_REVIEW_ID')
    if review_id:
        if hasattr(store, 'acquire_review'):
            run_id = os.environ.get('EVIDENCEDESK_RUN_ID')
            if os.environ.get('CLOUD_RUN_EXECUTION') and not run_id:
                raise RuntimeError('Cloud jobs require an explicit queued analysis run ID.')
            run_cloud_review(store, review_id, run_id=run_id)
        else:
            process(review_id, store)
        return
    if hasattr(store, 'acquire_review'):
        raise RuntimeError('Cloud worker requires an explicit review ID; no local-queue fallback.')
    while True:
        job = store.claim()
        if not job:
            if args.once:
                return
            time.sleep(1)
            continue
        stop = threading.Event()
        def heartbeat():
            while not stop.wait(30):
                store.heartbeat(job['id'])
        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            process(job['review_id'], store)
            store.finish(job['id'])
        except Exception as exc:
            store.finish(job['id'], str(exc)[:400])
        finally:
            stop.set()
        if args.once:
            return


if __name__ == '__main__':
    main()
