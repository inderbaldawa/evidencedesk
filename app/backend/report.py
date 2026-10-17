import io
from html import escape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
from .store import now

def export_pdf(review):
    stream=io.BytesIO()
    styles=getSampleStyleSheet()
    styles['Heading2'].keepWithNext=True
    styles.add(ParagraphStyle(name='Evidence',fontName='Helvetica',fontSize=9,leading=13,textColor=colors.HexColor('#28384d'),spaceAfter=7))
    styles.add(ParagraphStyle(name='Label',fontName='Helvetica-Bold',fontSize=10,leading=14,textColor=colors.HexColor('#174ea6'),spaceAfter=6,keepWithNext=True))
    def p(text,style='Evidence'):return Paragraph(escape(str(text)).replace('\n','<br/>'),styles[style])
    story=[p('EvidenceDesk | Evidence review pack','Title'),Spacer(1,10),p(review['name'],'Heading2'),
      p('SYNTHETIC DEMONSTRATION DATA - Analyst evidence review, not legal certification.'),
      p(f"Vendor: {review['vendor']} | Service: {review['service']} | Environment: {review['environment']}"),
      p(f"Review period: {review['period']} | Policy: {review['policy_version']} | State: {review['status']}"),
      p(f"Generated: {now()} | Review ID: {review['id']}"),Spacer(1,8)]
    cov=review['coverage']
    story += [p('Processing coverage','Heading2'),p(f"{cov['processed']} of {cov['submitted']} documents processed; {cov['failed']} failed; {cov['duplicates']} duplicates; {cov['pages']} pages submitted."),
      p('Missing evidence means not found in this supplied scope. Failed or unreadable files remain unresolved. AI findings and reviewer decisions are recorded separately.')]
    analysis=review.get('analysis',{})
    story += [p(f"Analysis model: {analysis.get('model','Not run')} | Version: {analysis.get('version','n/a')} | Analysis time: {analysis.get('generated_at','n/a')}")]
    for f in review['findings']:
        story.extend([Spacer(1,10),p(f['control_name'],'Heading2'),p(f['status'].replace('_',' ').upper(),'Label'),
          p('Requirement: '+f['requirement']),p(f['explanation']),p('Next action: '+f.get('next_action',''))])
        if f.get('follow_up_question'):story.append(p('Suggested question: '+f['follow_up_question']))
        for c in f.get('citations',[]):
            story.extend([p(f"{c.get('role','source').title()} - {c['document_name']}, page {c['page']}",'Label'),p(c['quote'])])
        r=f.get('reviewer',{})
        story.extend([p('Reviewer decision: '+r.get('decision','unreviewed').replace('_',' '),'Label'),p('Note: '+(r.get('note') or 'No note recorded.')),p('Decision time: '+str(r.get('at') or 'Not reviewed'))])
        for action in f.get('history',[]):
            story.extend([p('Decision history: '+str(action.get('at',''))+' | '+action.get('decision','').replace('_',' '),'Label'),p(action.get('note') or 'No note recorded.')])
    story.extend([Spacer(1,12),p('Document manifest and unresolved items','Heading2')])
    for d in review['documents']:
        story.extend([p(f"{d['name']} | {d['status']} | {d['page_count']} pages",'Label'),p('SHA-256: '+d['sha256'])])
        if d.get('error'):story.append(p('Unresolved: '+d['error']))
    def footer(canvas,doc):
        canvas.setFont('Helvetica',8);canvas.setFillColor(colors.HexColor('#526175'))
        canvas.drawString(42,26,'EvidenceDesk | Synthetic demonstration | Source-linked evidence review')
        canvas.drawRightString(A4[0]-42,26,f'Page {doc.page}')
    SimpleDocTemplate(stream,pagesize=A4,rightMargin=42,leftMargin=42,topMargin=38,bottomMargin=45,title='EvidenceDesk evidence pack').build(story,onFirstPage=footer,onLaterPages=footer)
    return stream.getvalue()
