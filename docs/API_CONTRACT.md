# EvidenceDesk API contract

All API responses JSON, snake_case. Same-origin /api. Session uses HttpOnly cookie locally; cloud Firebase bearer token; API authorizes every private review. Public GET /api/sample returns immutable, genuinely preprocessed review if available; never fabricate results. POST /api/reviews/sample clones sample into private writable review. GET /api/session returns session state. POST /api/reviews creates empty private review {name,vendor,service,environment,period,policy_version}. POST /api/reviews/{id}/documents multipart `files` accepts text PDFs; POST /api/reviews/{id}/analyze queues durable processing; GET /api/reviews/{id} polls; POST /api/reviews/{id}/findings/{finding_id}/decision {decision,note}; GET /api/reviews/{id}/export?format=json|pdf; GET /api/reviews/{id}/documents/{document_id}/file streams PDF. GET /api/health.

Review shape:
{id,name,vendor,service,environment,period,policy_version,status:'empty'|'queued'|'processing'|'complete'|'incomplete'|'failed',created_at,updated_at,synthetic:true,read_only:boolean,analysis:{model,version,generated_at,duration_seconds,calls,input_tokens,output_tokens,estimated_cost_usd,label},coverage:{submitted,processed,failed,duplicates,pages},documents:Document[],findings:Finding[],events:Event[]}

Document: {id,name,sha256,status:'pending'|'processing'|'processed'|'failed'|'duplicate',page_count,error,duplicate_of?,pages:[{page:1,text}],context?:{vendor,service,environment,period,version,document_type},file_url?}. Pages are numbered from 1. No private local paths exposed by API.

Finding: {id,control_id,control_name,status:'evidence_found'|'partial_evidence'|'conflicting_evidence'|'not_evidenced'|'needs_human_review',requirement,policy_version,explanation,next_action,follow_up_question,citations:Citation[],reviewer:{decision:'unreviewed'|'accepted'|'clarification_requested'|'unresolved',note,at} ,history?:[]}

Citation: {document_id,document_name,page,quote,role:'requirement'|'claim'|'record'|'support',valid:true}. Citation quote must be literal substring of page after whitespace normalization; record validation failure separately and downgrade finding. Every material conclusion needs evidence; missing evidence conclusion references policy and coverage.

Event: {at,type,message}. Six control IDs: data_location, backup_location, deletion, access_review, incident_response, evidence_currency.

Pipeline interface: `analyze_review(review: dict, documents: list[dict], *, progress=None) -> dict` returns {findings,analysis,documents}; documents input includes pages extracted by API backend. Pipeline does per-document structured extraction then small per-control reconciliation. Can batch small documents but never dump full corpus in one prompt. Persist artifacts through progress callback if supplied (storage integration may adapt this interface). All Gemini calls in ai_client must share the configured aggregate budget ledger (file-lock locally, transactional Firestore in cloud); enforce explicit aggregate limits across processes and worst-case reservation before every call. Live calls require an explicitly initialized budget ledger.

Frontend: show explanatory landing, Explore sample review, upload/review workspace, six-control matrix, large side-by-side citation panes and original PDF page links, coverage/processing/errors, reviewer decision + note, follow-up editable draft, export. Poll until terminal. Never invent sample findings or mask incomplete status. Friendly API errors. Responsive, accessible Material-inspired light UI. Show synthetic label and actual analysis model/date.

Corpus: use fictional buyer Aster Finance and vendor Nimbus Support, service Customer Support Platform, production, review period 2026-10, policy v3.0. Policy explicitly covers India-only customer data AND backups. Current questionnaire claims both India; current inventory Singapore customer backups. Include positive controls, missing deletion evidence, obsolete versions, wrong vendor/environment, duplicate, unreadable, injection. Manifest written before model tuning. Generator must run using bundled reportlab. All files under project.


Upload acceptance stores PDF bytes and metadata; it does not parse in the web request. The durable worker parses each PDF in a bounded subprocess, then performs AI analysis. A pending document has no page count until extraction. Failed inputs and duplicates remain visible. Cloud workers fence each write using an expiring lease and distinct dispatch/attempt identities; GCS is authoritative and Firestore stores a repairable revisioned index.
