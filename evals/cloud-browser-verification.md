# Independent deployed browser workflow verification

The first deployed four-document browser workflow is verified for source integrity, decision persistence, exports, cloud storage/index durability and completed job execution. **Five findings are appropriate to this limited upload; the evidence-currency finding has a semantic false negative and must not be counted as a 6/6 accuracy pass.** This audit made read-only cloud requests and no model calls or mutations.

## Actual scope and findings

The upload contains policy-v3.pdf (3 pages), questionnaire-202610.pdf (2), backup-inventory-202610.pdf (2) and evidence-register-202610.pdf (1): four processed documents, eight pages, no failed or duplicate documents. It does not contain the primary asset register, completed access review, signed incident addendum, archived questionnaire or adversarial attachment.

| Control | Actual outcome | Independent assessment |
|---|---|---|
| Primary data location | partial_evidence | Appropriate: India-only questionnaire claim is present, but the primary-store operational artifact is absent. |
| Backup location | conflicting_evidence | Appropriate: current policy and questionnaire say India-only; current production inventory records Singapore replica BKP-SG-02. Same vendor, service, environment and October period. |
| Deletion | not_evidenced | Appropriate: the questionnaire/register say completion evidence for DEL-2026-041 remains missing. This does not prove deletion never occurred. |
| Access review | partial_evidence | Appropriate: questionnaire/register refer to a completed review, but the underlying approved review is not uploaded. |
| Incident response | partial_evidence | Appropriate: questionnaire mentions a 12-hour signed addendum, but the executed addendum and monitored contact are absent. A reference to another document is not that document. |
| Evidence currency | not_evidenced | Defect: the explanation says no applicable support was located even though uploaded inventory/register provide explicit current October dates and matching scope. This appears to be an extraction/routing fallback limitation, not missing source evidence. |

All 14 final citations were independently resolved to actual source PDF pages and matched literally after whitespace-only normalization. All four local original PDFs and their private cloud source objects match the recorded SHA256 values. The backup conflict is supported by the actual three documents, not inferred from expected outcomes.

## Decision and export integrity

The backup finding retains `clarification_requested`, the reviewer note, the edited follow-up draft and its decision timestamp. Its single history entry equals its current reviewer decision. The other five decisions remain unreviewed. The five-page exported PDF preserves all six actual statuses and explanations, plus the backup note, follow-up text, decision timestamp and history. The PDF therefore faithfully preserves the currency defect as well; successful export is not evidence that every finding is correct.

The authoritative private review artifact matches the exported JSON findings, coverage and events. The Firestore index is complete and its revision equals the authoritative artifact revision. The completed dispatch ID matches the recorded run ID. The referenced Cloud Run execution reports its Completed condition succeeded, one successful task, zero failed tasks and a completion timestamp. No identity UID, project/bucket identifiers or private execution/review IDs are included in this report.

## Shared budget verification

Read-only comparison to the approved carried-forward initialization shows an increase of **6 model calls, 10,991 input tokens, 3,903 output tokens and $0.045759 estimated usage**. Those increases exactly match this saved review's actual analysis accounting within floating-point tolerance. The saved analysis reports 40.509 seconds of analysis time; this is not total upload-to-export browser time. See the JSON receipt for current aggregate counters and outstanding reservation count.

## Limits and provenance

This proves a completed deployed job and persisted state, not forced restart/crash recovery. The audit checks PDF text/content rather than repeating visual QA of every page. It concerns fictional labeled evidence and this one four-document run; it does not generalize to arbitrary customer documents or injection resistance. The original artifacts must remain unchanged if a corrected pipeline is later evaluated.

Detailed checks and SHA256 fingerprints of both exported artifacts are in `evals/cloud-browser-verification.json`. The receipt deliberately contains no credentials, Firebase UIDs, project/bucket names or private job/review identifiers. Cloud reads used operator ADC and returned only sanitized check results.
