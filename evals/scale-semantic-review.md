# Scale evidence review — actual 106-PDF run

Reviewed 17 October 2026 against the frozen `fixtures.expected.json` and `data/scale/manifest.json`. This is a separate semantic inspection by the implementation team, not an external audit or certification. All organizations and evidence are synthetic.

**Result: all six final statuses match the frozen expectations, and all 33 displayed citations resolve literally to their stated source page.** The final review is complete after a bounded repair and two targeted reconciliation calls; the first run was incomplete, not a clean first-pass success.

## Actual artifact and coverage

- Final artifact: `scale-actual.public.json`, analysis generated `2026-10-17T06:35:32.785399+00:00`.
- SHA-256: `df5548a467da05d85a2e98f26ca6256907432427f5bcd7b805d3fb4af4850d7f`.
- Submitted and processed: **106 PDFs / 110 pages**, zero failed files, zero duplicates. All 106 documents underwent real structured model extraction during the initial run.
- Extraction version `evidencedesk-1.1`; model `gemini-3.8-flash` through Google Gen AI SDK / Google Cloud global endpoint.
- Final analysis has no processing errors or citation-validation failures. All six reviewer decisions remain **unreviewed**; the AI has not recorded a human approval.
- Expected fixtures were consulted after the run for evaluation, not supplied as model findings or served as product output. The packaged sample was not modified by these runners.

## Semantic inspection

| Control | Actual status | Source-level assessment |
|---|---|---|
| Customer data location | `evidence_found` | Policy v3 p1 requires India for primary stores. Primary inventory p1 locates CST-PROD-01 in Mumbai and CST-PROD-02 in Delhi; current component inspections support India locations. This finding does not establish backup location. Its quoted vendor claim includes backups, but the operational support and requirement concern primary storage, with the backup conflict separately explicit. |
| Backup location | `conflicting_evidence` | Complete three-source contradiction: policy v3 p1 requires India; current questionnaire p1 claims India-only, expressly including disaster-recovery replicas; current backup inventory p2 identifies customer-data replica BKP-SG-02 in Singapore. Eight current production job logs corroborate Mumbai-to-Singapore replication. The contradiction is not caused by staging, an older inventory, another vendor, or a legal assumption. |
| Deletion evidence | `not_evidenced` | Policy v3 p2 requires the completed DEL-2026-041 certificate with date, primary/backup scope and approver. Questionnaire p2 says the request remains open; evidence register p1 says no completion record was supplied. A retention plan explicitly lacks completed execution evidence; a change record explicitly covers a configuration change only. The output describes missing supplied evidence, not proof that deletion never happened. |
| Access reviews | `evidence_found` | Policy v3 p2 requires an approved recent review of all privileged production accounts. Access review p1 records all 12 accounts checked on 8 October, 11 retained, one revoked, and approval on 9 October. Scope and date satisfy the stated requirement. |
| Incident response | `evidence_found` | Policy v3 p3 requires a signed commitment within 24 hours and a monitored contact. Executed addendum p1 supplies a 12-hour requirement and continuously staffed incident desk; its full page states signatures and 1 October 2026–30 September 2027 effective period. Agreement IA-2026-10 is correctly treated as signed contractual support, not an obsolete buyer policy version. Tabletop drills do not substitute for the contract. |
| Evidence currency | `evidence_found` | Cited backup job pages identify Nimbus Support, Customer Support Platform, production, October 2026, and dated completed jobs. They are current and not superseded. The final narrative is narrowly about these operational records rather than an assertion that every uploaded document is current. The filtering audit below confirms obsolete and wrong-scope documents are excluded. |

## Citation and scope checks

Independently checked the 33 displayed quotations against `documents[].pages[]` using only whitespace normalization; **33/33 match**, all page numbers and document IDs resolve, and no cited document was excluded. Citation counts by control are 7, 12, 5, 2, 2 and 5 respectively; none exceeds the 12-item validation cap. Human-facing requirement, explanation, action and follow-up fields contain no internal hexadecimal evidence IDs.

Compared every document's extracted applicability with the scale manifest: **zero mismatches**. The 71 current documents remain applicable; 35 exclusions comprise 9 obsolete, 9 wrong-vendor, 8 wrong-environment, 8 irrelevant and 1 untrusted attachment. None appears in any final citation. The untrusted attachment is flagged `suspicious_instructions: true`, has zero observations, and does not alter reviewer decisions.

Full-page checks distinguish production customer-data backups from synthetic staging payloads; completed deletion evidence from a future retention plan; operational configuration completion from DEL-2026-041 completion; and signed notification obligations from tabletop exercise results.

### Presentation limitations

The evidence-currency snippets are literal but short: “This record covers the current October 2026 service; it is not a staging export or an earlier inventory.” A reader must open the source page to see the exact vendor, service, environment and job date. Thus the source pages support the status, but these snippets are weaker standalone citations than the backup contradiction. Similarly, the incident citation includes the notification obligation and contact, while signature/effective-period details are on the same source page outside the displayed quote. The primary-location explanation mentions archives supported elsewhere in the processed component records, outside its selected representative citation set. These are citation-completeness limitations, not fabricated quotations or changed control outcomes. Do not claim every displayed snippet independently proves every detail in its narrative.

## First-run failure and bounded recovery

The initial serial run processed all 106 PDFs but returned 19 evidence IDs for data location and 23 for deletion, exceeding the unchanged maximum of 12. Validation safely left those controls for human review and marked the run incomplete. The initial attempt summary is retained in `scale-metrics.public.json`; raw internal diagnostic artifacts are excluded from this public package.

A general reconciliation instruction now requires at most 12 unique representative citations, preserving policy, claims, contradictory records and uncertainty; the small provider schema also declares `maxItems: 12`. The cap was not increased. Offline tests verified both provider schema and Pydantic rejection of oversized results. Extraction remained v1.1. Only data location and deletion were retried, under reconciliation prompt v1.2: **2 calls**, **106 extraction cache hits**, **4 successful reconciliation cache hits**, zero re-extraction. The other four controls retain their recorded v1.1 reconciliation provenance. No broad full rerun occurred.

## Attributed measurement

| Phase | Calls | Input tokens | Billable output tokens | Estimated model cost | Active wall time |
|---|---:|---:|---:|---:|---:|
| Initial run | 33 | 97,023 | 38,217 | $0.432162 | 308.098 s |
| Two-control retry | 2 | 13,102 | 887 | $0.026305 | 10.738 s |
| Total scale work | **35** | **110,125** | **39,104** | **$0.458467** | **318.836 s** |

These are per-run AIClient usage totals, with output including thought tokens and estimated cost using the configured conservative input/output rates. Active wall time is the sum of the two processing phases, not elapsed calendar time including diagnosis and repair. The shared local ledger was also used by a concurrent separate HTTP test; its retry-window delta of four calls includes two unrelated calls and was global/concurrent usage, so the public metrics omit that shared-ledger delta. It is not attributed to this scale run. This is local processing/model cost, not a deployed infrastructure invoice or a production latency guarantee.

## Scope limits

This run contains the 106 files declared in the scale manifest, including wrong-vendor, wrong-environment, obsolete and injection examples. Separate malformed/unreadable/unsupported-format/duplicate adversarial fixtures are not in this manifest and were not tested by this scale run. It is one synthetic corpus and one final recovered execution, not an accuracy benchmark across real vendors or a claim of legal compliance. Human review remains required.
