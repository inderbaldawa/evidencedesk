# Vendor evidence workspaces

## Workflow

1. Open Workspace and create companies, then a project with its parties, purpose, owner, dates and policy pack. One company may participate in several projects.
2. Create a scoped review for a project party, or choose one of three synthetic demo packs.
3. Add PDF evidence. In All files or the project Files tab, organize source company/type, open original PDFs and inspect extraction status.
4. Run analysis to compare supplied requirements, claims and supporting records. Record reviewer decisions independently.
5. Upload a replacement from File details. It stays staged until extraction succeeds. Originals remain accessible; unreadable replacements do not displace good evidence.
6. Compare extracted text and inspect History. Prior findings retain exact file versions and hashes. New findings never inherit an earlier approval.

## Current boundaries

- Company/project records belong to the current browser identity. They are not vendor logins, invitations or sharing grants. Only uploaded/shared evidence is visible.
- PDF limits:5MiB/file,25pages/file,20files/upload,150documents including versions/review. Daily per-identity limits:10new reviews,5analyses.
- Workspace:100companies,100projects,30parties/project,800KB metadata. The file manager shows up to500most recently updated reviews and warns if older reviews are omitted.
- Review history retains20previous analysis snapshots plus current analysis. Original document versions remain available within the150-document limit.
- Text comparison shows extracted text, not visual redlines or proof that operational remediation occurred.
- OCR is implemented but disabled until configured. It was verified with offline tests, not a live Document AI processor. Set EVIDENCEDESK_OCR_PROCESSOR to a valid asia-south1 processor path (optionally a pinned processor version), grant the worker process permission, and configure the same processor on web for accurate capability reporting. Default shared OCR limit100reservedpages/day. Uncertain requests retain quota and are not automatically retried. Never represent configuration presence as a successful reachability test.
- These packs are fictional buyer policies and evaluation examples, not legal frameworks or compliance certification.

## Validation

143 backend tests and4 frontend helper tests passed. Two new live packs required14calls and an estimated$0.104007;36quotations were checked against their original PDFs. A separate live version workflow preserved the prior clarification decision and changed retention from conflicting evidence to evidence found while keeping the new decision unreviewed. These are bounded synthetic checks, not general accuracy claims. The hosted workflow passed: three pack seeds, owner isolation, project metadata, source hashes, fresh AI analysis, staged replacement, reanalysis, exact-version history, prior reviewer decision preservation, comparison and PDF export. See [hosted verification](../evals/workspace-hosted-verification.json). An initial hosted run exposed a generation-pinned GCS read race; it was fixed, covered by three regressions and the complete hosted workflow rerun successfully.
