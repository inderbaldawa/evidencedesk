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
        doc.update(status='failed',error='Only PDF files are supported.');return doc
    key=f'documents/{review_id}/{doc["id"]}.pdf'
    store.save_blob(key,data)
    doc['_blob']=key
    return doc

def extract_document(doc,store):
    """Parse hostile PDFs in isolation; use opt-in OCR only for unreadable text."""
    if not doc.get('_blob') or doc['status'] in ('failed','duplicate') or doc.get('pages'):return doc
    try:
        data=store.read_blob(doc['_blob'])
        result=subprocess.run([sys.executable,'-m','app.backend.pdf_parser'],input=data,capture_output=True,timeout=15)
        if result.returncode!=0:raise ValueError('PDF parser exceeded a resource limit or could not read this file.')
        parsed=json.loads(result.stdout)
        if parsed.get('error'):
            if parsed.get('error_code') != 'no_readable_text' or not parsed.get('ocr_eligible'):
                raise ValueError(parsed['error'])
            from .document_ocr import extract_ocr
            # Only the bounded parser can positively authorize this fallback.
            parsed=extract_ocr(data,doc,parsed,store)
        doc.update(pages=parsed['pages'],page_count=len(parsed['pages']),status='pending',error=None,
                   extraction_method=parsed.get('extraction_method','native_pdf'),
                   extraction_version=parsed.get('extraction_version','pypdf-isolated-v1'))
        if parsed.get('ocr'):doc['ocr']=parsed['ocr']
    except subprocess.TimeoutExpired:doc.update(status='failed',error='PDF parsing exceeded 15 seconds; this document remains unresolved.')
    except Exception as exc:doc.update(status='failed',error=str(exc)[:400])
    return doc

def parse_pdf(data):
    """No network. Only a valid, bounded PDF with missing text is OCR-eligible."""
    if len(data)>MAX_BYTES:return {'error':'PDF exceeds 5 MB.','error_code':'size_limit'}
    if not data.startswith(b'%PDF-'):return {'error':'Only PDF files are supported.','error_code':'invalid_pdf'}
    try:
        reader=PdfReader(io.BytesIO(data))
        if reader.is_encrypted:return {'error':'Password-protected PDFs are not supported.','error_code':'encrypted'}
        if not 1<=len(reader.pages)<=MAX_PAGES:
            return {'error':f'PDF must contain between 1 and {MAX_PAGES} pages.','error_code':'page_limit'}
        pages=[{'page':i+1,'text':p.extract_text() or ''} for i,p in enumerate(reader.pages)]
        if sum(len(p['text']) for p in pages)>150000:
            return {'error':'Extracted text exceeds the document limit.','error_code':'text_limit'}
        unreadable=[p['page'] for p in pages if len(p['text'].strip())<20]
        if unreadable:
            return {'pages':pages,'unreadable_pages':unreadable,'ocr_eligible':True,
                    'error_code':'no_readable_text','error':'One or more pages have no readable text; OCR is required.'}
        return {'pages':pages}
    except Exception:
        return {'error':'PDF could not be read or is malformed.','error_code':'invalid_pdf'}

def coverage(review):
    docs=[d for d in review['documents'] if d.get('is_current',True)]
    return {'submitted':len(docs),'processed':sum(d['status']=='processed' for d in docs),
            'failed':sum(d['status']=='failed' for d in docs),'duplicates':sum(d['status']=='duplicate' for d in docs),
            'pages':sum(d.get('page_count',0) for d in docs if d['status']!='duplicate')}
