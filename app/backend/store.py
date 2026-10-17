"""Durable local store. Cloud adapter keeps documents in GCS and bounded indexes in Firestore."""
import copy
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(os.environ.get('EVIDENCEDESK_DATA_DIR', str(Path(__file__).resolve().parents[2] / '.local' / 'runtime')))
ROOT.mkdir(parents=True, exist_ok=True)

def now():
    return datetime.now(timezone.utc).isoformat()

class LocalStore:
    def __init__(self):
        self.path = ROOT / 'reviews.sqlite3'
        with self.connect() as db:
            db.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS reviews(id TEXT PRIMARY KEY, owner TEXT NOT NULL, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, review_id TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER DEFAULT 0, lease REAL DEFAULT 0, error TEXT);
            CREATE TABLE IF NOT EXISTS limits(owner TEXT, day TEXT, count INTEGER, PRIMARY KEY(owner,day));''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def get(self, review_id):
        with self.connect() as db:
            row = db.execute('SELECT body FROM reviews WHERE id=?', (review_id,)).fetchone()
        return json.loads(row['body']) if row else None

    def put(self, review):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO reviews VALUES(?,?,?)', (review['id'],review['_owner'],json.dumps(review)))

    def update(self, review_id, fn):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT body FROM reviews WHERE id=?',(review_id,)).fetchone()
            if not row: raise KeyError(review_id)
            review=json.loads(row['body'])
            result=fn(review)
            review['updated_at']=now()
            db.execute('UPDATE reviews SET body=? WHERE id=?',(json.dumps(review),review_id))
        return result if result is not None else review

    def save_blob(self, key, data):
        path=ROOT / 'blobs' / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def read_blob(self,key):
        return (ROOT / 'blobs' / key).read_bytes()

    def enqueue(self, review_id):
        with self.connect() as db:
            db.execute('INSERT INTO jobs(id,review_id,status) VALUES(?,?,?)',(uuid.uuid4().hex,review_id,'queued'))

    def claim(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT * FROM jobs WHERE status='queued' OR (status='running' AND lease < ?) ORDER BY rowid LIMIT 1",(time.time(),)).fetchone()
            if not row:return None
            db.execute("UPDATE jobs SET status='running',attempts=attempts+1,lease=? WHERE id=?",(time.time()+180,row['id']))
            return dict(row)

    def heartbeat(self,job_id):
        with self.connect() as db:db.execute('UPDATE jobs SET lease=? WHERE id=?',(time.time()+180,job_id))

    def finish(self,job_id,error=None):
        with self.connect() as db:db.execute('UPDATE jobs SET status=?,error=? WHERE id=?',('failed' if error else 'complete',error,job_id))

    def take_limit(self,owner,maximum=5):
        day=now()[:10]
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT count FROM limits WHERE owner=? AND day=?',(owner,day)).fetchone()
            if row and row['count']>=maximum:return False
            db.execute('INSERT INTO limits VALUES(?,?,1) ON CONFLICT(owner,day) DO UPDATE SET count=count+1',(owner,day))
        return True

def get_store():
    # Cloud storage requires explicit configuration and separately verified deployment.
    if os.environ.get('EVIDENCEDESK_STORAGE','local') != 'local':
        from .cloud_store import CloudStore
        return CloudStore()
    return LocalStore()

def new_review(owner, **fields):
    return {'id':uuid.uuid4().hex,'_owner':owner,'name':fields.get('name','Vendor evidence review'),
      'vendor':fields.get('vendor','Nimbus Support'),'service':fields.get('service','Customer Support Platform'),
      'environment':fields.get('environment','production'),'period':fields.get('period','2026-10'),
      'policy_version':fields.get('policy_version','v3.0'),'status':'empty','created_at':now(),'updated_at':now(),
      'synthetic':True,'read_only':False,'analysis':{},'coverage':{'submitted':0,'processed':0,'failed':0,'duplicates':0,'pages':0},
      'documents':[],'findings':[],'events':[]}

def public_review(review,read_only=False):
    data=copy.deepcopy(review)
    if data.get('_analysis_history'):data['analysis_history']=data['_analysis_history']
    for key in list(data):
        if key.startswith('_'):data.pop(key,None)
    data['read_only']=read_only
    data.get('analysis',{}).pop('reconciliation_cache',None)
    for past in data.get('analysis_history',[]):past.get('analysis',{}).pop('reconciliation_cache',None)
    for doc in data.get('documents',[]):
        for key in list(doc):
            if key.startswith('_') or key in ('extraction','path','file_path'):doc.pop(key,None)
        doc['file_url']=f"/api/reviews/{data['id']}/documents/{doc['id']}/file"
    return data
