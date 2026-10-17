import hashlib
import io
import uuid
import json
import subprocess
import sys
from pypdf import PdfReader

MAX_BYTES=5*1024*1024
MAX_PAGES=25

def ingest_pdf(name,data,store,review_id,known_hashes):
    digest=hashlib.sha256(data).hexdigest()
    doc={'id':uuid.uuid4().hex,'name':name[:180],'sha256':digest,'status':'pending','page_count':0,'error':None,'pages':[]}
    if digest in known_hashes:
        doc.update(status='duplicate',duplicate_of=known_hashes[digest],error='Identical content already uploaded; excluded from analysis.')
        return doc
    if len(data)>MAX_BYTES:
        doc.update(status='failed',error='File exceeds the 5 MB document limit.');return doc
    if not name.lower().endswith('.pdf') or not data.startswith(b'%PDF-'):
        doc.update(status='failed',error='Only text-based PDF files are supported.');return doc
    key=f'documents/{review_id}/{doc["id"]}.pdf'
    store.save_blob(key,data)
    doc['_blob']=key
    return doc

def extract_document(doc,store):
    """Parse hostile PDFs outside the web process with a strict wall-clock bound."""
    if not doc.get('_blob') or doc['status'] in ('failed','duplicate') or doc.get('pages'):return doc
    try:
        result=subprocess.run([sys.executable,'-m','app.backend.pdf_parser'],input=store.read_blob(doc['_blob']),capture_output=True,timeout=15)
        if result.returncode!=0:raise ValueError('PDF parser exceeded a resource limit or could not read this file.')
        parsed=json.loads(result.stdout)
        if parsed.get('error'):raise ValueError(parsed['error'])
        doc.update(pages=parsed['pages'],page_count=len(parsed['pages']),status='pending',extraction_version='pypdf-isolated-v1')
    except subprocess.TimeoutExpired:doc.update(status='failed',error='PDF parsing exceeded 15 seconds; this document remains unresolved.')
    except Exception as exc:doc.update(status='failed',error=str(exc)[:400])
    return doc

def parse_pdf(data):
    try:
        reader=PdfReader(io.BytesIO(data))
        if reader.is_encrypted:raise ValueError('Password-protected PDFs are not supported.')
        if len(reader.pages)>MAX_PAGES:raise ValueError(f'PDF exceeds {MAX_PAGES} pages.')
        pages=[{'page':i+1,'text':p.extract_text() or ''} for i,p in enumerate(reader.pages)]
        if not pages or any(len(p['text'].strip())<20 for p in pages):
            raise ValueError('One or more pages have no readable text. OCR is not supported; review remains incomplete.')
        if sum(len(p['text']) for p in pages)>150000:raise ValueError('Extracted text exceeds the document limit.')
        return {'pages':pages}
    except Exception as exc:
        return {'error':str(exc)[:400]}

def coverage(review):
    docs=review['documents']
    return {'submitted':len(docs),'processed':sum(d['status']=='processed' for d in docs),
            'failed':sum(d['status']=='failed' for d in docs),'duplicates':sum(d['status']=='duplicate' for d in docs),
            'pages':sum(d.get('page_count',0) for d in docs if d['status']!='duplicate')}
