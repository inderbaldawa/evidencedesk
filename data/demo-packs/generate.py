"""Rebuild fictional review documents. No model calls or real-world assertions."""
import hashlib
import json
import shutil
from pathlib import Path
from xml.sax.saxutils import escape

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / 'data/demo-packs'
SYNTHETIC = 'SYNTHETIC DEMONSTRATION - ALL ENTITIES, APPROVALS AND EVENTS ARE FICTIONAL'

PACKS = {
 'security-assurance': {
  'project': 'Security assurance demo', 'vendor': 'Cedar Operations', 'service': 'Managed Support Service',
  'environment': 'production', 'period': '2026-10', 'policy_version': '1.0',
  'policy': [
   ('Privileged access', 'All privileged production accounts must have a named owner and a completed monthly access review with an approver.'),
   ('MFA enforcement', 'Every interactive privileged production account must enforce multifactor authentication. Bypass exceptions are not permitted for this review.'),
   ('Vulnerability remediation', 'Critical production vulnerabilities must be remediated and retested within seven calendar days of discovery.'),
   ('Security testing', 'Provide a scoped security test completed within the last 90 days, including its findings and follow-up evidence.'),
   ('Incident response', 'Maintain an incident-response configuration requiring buyer notification within 24 hours of discovery and a monitored buyer contact.'),
   ('Evidence currency', 'Evidence must identify this vendor, service and production environment and be dated within 90 days of 15 October 2026. Superseded records must not be used as current evidence.'),
  ],
  'questionnaire': [
   ('Privileged access', 'We completed the October privileged-account review and assigned an owner to every privileged production account.'),
   ('MFA enforcement', 'All interactive privileged production accounts enforce MFA. We have no bypass exceptions.'),
   ('Vulnerability remediation', 'All critical findings were remediated and retested within seven days of discovery.'),
   ('Security testing', 'Our scoped September security test is complete; the standalone report is not included in this submission.'),
   ('Incident response', 'Our response configuration requires buyer notification within 24 hours of discovery using a monitored buyer contact.'),
   ('Evidence currency', 'This response is issued 10 October 2026 and replaces our July 2026 questionnaire. It covers October 2026 production operations.'),
  ],
  'operational-record': [
   ('Privileged access', 'Access review AR-2026-10 completed 12 October 2026: 12 privileged production accounts, each with a named owner. Approver: Mira Rao (fictional). One departed operator account was removed.'),
   ('MFA enforcement', 'Configuration export AUTH-2026-10 dated 12 October 2026: 11 interactive privileged accounts enforce MFA; the remaining interactive privileged account breakglass-admin has MFA bypass enabled. It was used interactively on 11 October 2026. No policy exception was approved.'),
   ('Vulnerability remediation', 'Ticket VULN-41: critical finding discovered 3 October 2026, fixed 6 October and successfully retested 7 October 2026. This is the sole critical finding in the October register.'),
   ('Security testing', 'Evidence register: September security test report TEST-2026-09 was requested but is not attached to this packet. This register does not reproduce the report or its findings.'),
   ('Incident response', 'Response configuration IR-12 verified 12 October 2026: notify Aster Finance within 24 hours of discovering a customer-data incident. Monitored buyer contact: incident-contact@aster.example; monitored daily by the fictional response team.'),
   ('Evidence currency', 'This current operations register was issued 12 October 2026 and supersedes the July register. All entries above cover the named production service during October 2026.'),
  ],
 },
 'ai-vendor': {
  'project': 'AI vendor review demo', 'vendor': 'Lantern AI', 'service': 'Support Reply Assistant',
  'environment': 'production', 'period': '2026-10', 'policy_version': '1.0',
  'policy': [
   ('Training use', 'Customer prompts and outputs must not be used for model training. Provide the scoped training-use configuration.'),
   ('Data retention', 'Customer prompts, outputs and diagnostic logs containing customer content must be retained for no more than seven days. The limit includes troubleshooting logs.'),
   ('Human oversight', 'A human support agent must approve every AI-drafted reply before it is sent to a customer. Provide workflow settings and completed review records.'),
   ('Model change notice', 'Notify the buyer at least seven calendar days before a production model change and record buyer approval before deployment.'),
   ('Subprocessor disclosure', 'Provide a current register naming every downstream provider that handles customer prompts or outputs and its service role.'),
   ('Evidence currency', 'Evidence must identify this vendor, service and production environment and be dated within 90 days of 15 October 2026. Superseded records must not be used as current evidence.'),
  ],
  'questionnaire': [
   ('Training use', 'Customer prompts and outputs are excluded from model training for this production service.'),
   ('Data retention', 'All customer prompts, outputs and diagnostic logs containing customer content are deleted within seven days.'),
   ('Human oversight', 'Every AI-drafted customer reply requires human approval before sending.'),
   ('Model change notice', 'We give at least seven days of notice and obtain buyer approval before production model changes.'),
   ('Subprocessor disclosure', 'We maintain a current subprocessor register; it is not attached to this submission.'),
   ('Evidence currency', 'This response is issued 10 October 2026 and replaces our July response. It covers October 2026 production operations.'),
  ],
  'operational-record': [
   ('Training use', 'Configuration AI-CONFIG-12 verified 12 October 2026: training_use=false for customer prompts and outputs in the named production service.'),
   ('Data retention', 'Configuration AI-CONFIG-12: prompt and output stores have seven-day expiry. Diagnostic log stream diag-content retains full customer prompts for 45 days. A 1 September 2026 diagnostic record containing a customer prompt remains present on 12 October 2026.'),
   ('Human oversight', 'Workflow version 4 has auto_send=false and requires an agent approval event. Review audit 12 October 2026: all 20 drafted replies had a named agent approval timestamp before their send timestamp.'),
   ('Model change notice', 'Change MC-07: buyer notice sent 1 October 2026 for model deployment on 10 October 2026. Buyer approval recorded 3 October 2026; deployment completed 10 October 2026.'),
   ('Subprocessor disclosure', 'Evidence register: the downstream-provider register was requested but is absent from this packet. This record does not identify the providers or establish that no subprocessors exist.'),
   ('Evidence currency', 'This current register was issued 12 October 2026 and supersedes the July register. Its configuration, workflow and change records cover the named production service in October 2026.'),
  ],
 },
}


def make_pdf(path, title, scope, role, rows):
 style = ParagraphStyle('body', fontName='Helvetica', fontSize=10, leading=14, textColor=colors.HexColor('#243043'), spaceAfter=8)
 heading = ParagraphStyle('heading', parent=style, fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=colors.HexColor('#1557a0'), spaceBefore=5, spaceAfter=3)
 title_style = ParagraphStyle('title', parent=style, fontName='Helvetica-Bold', fontSize=19, leading=23, spaceAfter=13)
 small = ParagraphStyle('small', parent=style, fontSize=8, leading=11)
 issued = '2026-10-01' if role == 'policy' else ('2026-10-10' if role == 'questionnaire' else '2026-10-12')
 text = [Paragraph(escape(title), title_style), Paragraph('Buyer: Aster Finance (fictional).', style),
         Paragraph(escape(f"Vendor: {scope['vendor']} | Service: {scope['service']} | Environment: production"), style),
         Paragraph(escape(f"Coverage: October 2026 (2026-10). Issued: {issued}. Version: 1.0. Review as of: 15 October 2026."), style)]
 if role == 'policy':
  text.append(Paragraph('Approved internal buyer policy v1.0, effective 1 October 2026. Approver: Aster Finance Risk Committee (fictional). These are demonstration buyer requirements, not a legal framework or a claim of regulatory compliance.', style))
 else:
  text.append(Paragraph('Vendor questionnaire assertions are claims; operational records describe only the supplied fictional records. Neither independently verifies real-world infrastructure.', small))
 for label, paragraph in rows:
  text.extend([Paragraph(escape(label), heading), Paragraph(escape(paragraph), style)])
 def page(canvas, doc):
  canvas.saveState(); canvas.setFont('Helvetica-Bold', 7); canvas.setFillColor(colors.HexColor('#1557a0'))
  canvas.drawString(42, 815, SYNTHETIC)
  canvas.setFont('Helvetica', 8); canvas.setFillColor(colors.HexColor('#5b6470'))
  canvas.drawString(42, 24, 'Fictional internal evidence. No real organization, legal opinion or endorsement.')
  canvas.drawRightString(553, 24, f'Page {doc.page}')
  canvas.restoreState()
 SimpleDocTemplate(str(path), pagesize=(595,842), rightMargin=42, leftMargin=42, topMargin=48, bottomMargin=42).build(text, onFirstPage=page, onLaterPages=page)


def file_entry(path, role):
 reader = PdfReader(path)
 return {'name': path.name, 'path': path.relative_to(ROOT).as_posix(), 'role': role,
         'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'pages': len(reader.pages), 'synthetic': True}


def main():
 manifest = {'schema_version': '1.0', 'synthetic': True,
             'description': 'Fictional buyer-policy review packs. Not legal frameworks. No expected model findings are embedded.', 'packs': {}}
 folder = DEST/'data-handling'; folder.mkdir(parents=True, exist_ok=True)
 base = json.loads((ROOT/'data/compact/manifest.json').read_text())
 files=[]
 for stem,role in [('policy-v3','policy'),('questionnaire-202610','questionnaire'),('backup-inventory-202610','operational-record')]:
  source=ROOT/f'data/compact/pdfs/{stem}.pdf'; target=folder/source.name
  shutil.copyfile(source,target); files.append(file_entry(target,role))
 scope={k:base['review_scope'][k] for k in ('vendor','service','environment','period','policy_version')}
 manifest['packs']['data-handling']={'project':'Data handling demo','policy_pack_id':'data-handling','policy_pack_version':'1.0',**scope,'files':files}
 for pack_id, config in PACKS.items():
  folder=DEST/pack_id;folder.mkdir(parents=True,exist_ok=True);files=[]
  for role in ('policy','questionnaire','operational-record'):
   target=folder/f'{role}.pdf'
   title={'policy':'Approved buyer internal policy v1.0','questionnaire':'Vendor questionnaire - October 2026','operational-record':'Current operational evidence register'}[role]
   make_pdf(target,title,config,role,config[role]);files.append(file_entry(target,role))
  manifest['packs'][pack_id]={k:config[k] for k in ('project','vendor','service','environment','period','policy_version')}
  manifest['packs'][pack_id].update(policy_pack_id=pack_id,policy_pack_version='1.0',files=files)
 (DEST/'demo_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
 print(json.dumps({k:{'documents':len(p['files']),'pages':sum(f['pages'] for f in p['files'])} for k,p in manifest['packs'].items()}))

if __name__=='__main__':main()
