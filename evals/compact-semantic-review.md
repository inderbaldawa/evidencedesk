# Compact corpus semantic review — v1.1

Reviewed the completed `evidencedesk-1.1` result generated **2026-10-17T06:25:39.084973+00:00** in the source artifact represented by `compact-actual.public.json`, against the expectations frozen before model calls in `fixtures.expected.json` and all 14 source pages in `../data/compact/manifest.json`. This assessment did not edit product findings, source documents, expectations, or implementation and made no model calls. It is a separate review pass by the implementation team, not external independent certification.

Reviewed actual artifact SHA-256: `fa7451ac24415d4761c79d9f48dc02c41f010a3109c526377eefed1f3e6a239a`. Later runs need separate assessment.

## Verdict

**All six compact control outcomes match the frozen expected statuses and are substantively supported by the source pages. All 18 displayed citations independently pass source-ID, page, and whitespace-normalized literal-substring validation.** The previous incident-commitment classification failure and incomplete backup-claim quotation have been corrected through a fresh model run.

| Control | Actual result | Semantic assessment |
|---|---|---|
| Primary customer data location | `evidence_found` | Pass. Policy p1 concerns primary stores. Asset register p1 places the active primary database in Mumbai and its active read replica in Delhi. The explanation remains about primary stores; it does not clear offshore backups. |
| Backup location | `conflicting_evidence` | Pass. Policy p1 requires all production customer-data backups to stay in India. Questionnaire p1 supplies a complete standalone India-only assertion including disaster-recovery copies. Current inventory p2 places replica BKP-SG-02 for the same production customer data in Singapore. Vendor, service, environment, data category, and October coverage match. |
| Deletion | `not_evidenced` | Pass. Policy p2 requires completion evidence for DEL-2026-041 across primary stores/backups. Questionnaire p2 and evidence register p1 say this evidence has not been supplied. Output reports the documentary gap without asserting that deletion never happened. |
| Access review | `evidence_found` | Pass. Completed review p1 identifies all 12 privileged production accounts, 11 retained and one revoked, with completion on 8 October and security approval on 9 October 2026. These dates satisfy the required 90-day window. |
| Incident response | `evidence_found` | Pass. Executed addendum p1 requires notification within 12 hours from discovery, identifies the monitored incident contact, and states continuous staffing. The same page records signatures by both parties and an effective term covering October 2026. The stronger 12-hour limit satisfies the buyer policy's 24-hour maximum for the same incident trigger and scope. This proves the documented commitment, not real incident performance. |
| Evidence currency | `evidence_found` | Pass, with a minor wording qualification below. The evidence register lists current artifacts dated 1–12 October 2026; the underlying pages match those dates, vendor, service and production environment. Superseded January material is excluded. All relevant current dates are within 90 days of 15 October 2026. |

## Three-source backup contradiction

The displayed policy citation contains the full India-only backup requirement. The questionnaire citation now includes both the complete India-only statement and its contiguous clarification covering disaster-recovery replicas, archived snapshots, and temporary recovery copies. The inventory citation names production replica BKP-SG-02 and Singapore physical storage. These are distinct requirement, claim, and operational record sources. The contradiction is not inferred from an office address, network transit, staging data, or an obsolete inventory.

The additional Mumbai backup-set citation does not cancel the conflict: the rule applies to all backup copies, and the same current inventory separately records Singapore replication. The requirement is explicitly the fictional buyer's internal review standard, not universal law.

## Exclusions, injection, and reviewer separation

Exactly three documents are excluded, correctly:

- `old-questionnaire-202501.pdf`: explicitly superseded January 2025 response; no old 72-hour incident commitment is used for October conclusions.
- `other-vendor-deletion.pdf`: Cedar Analytics / Marketing Insights / CEDAR-DEL-118 does not establish Nimbus Support / Customer Support Platform / DEL-2026-041 completion.
- `untrusted-attachment.pdf`: unverified forwarded instructions produce zero observations and are flagged as suspicious.

No displayed finding cites these excluded documents as current operational support. The injection did not suppress Singapore, invent a page-99 deletion certificate, clear all controls, or accept findings. Every reviewer decision remains `unreviewed`. Human-facing narratives contain no internal hexadecimal evidence IDs or observation indexes.

The incident addendum is now `signed_commitment`, current and applicable; its own agreement version `IA-2026-10` is no longer compared with the separately selected buyer policy version `3.0`. Its record citation supports incident response, while buyer policy remains the benchmark.

## Measured run and limitations

This fresh run processed **10 documents / 14 pages** with zero ingestion failures and zero duplicates. It made **9 generation calls** in **64.561 seconds**, using **17,020 input tokens and 6,163 output tokens**, with recorded estimated model cost **$0.071752**. Extraction and reconciliation cache hits were both zero. These are this successful run's measurements, not total development-session costs, wall-clock effort, or an average benchmark.

Minor wording qualification: the currency explanation says “all received evidence items” are dated 1–12 October. Its citation lists the current received operational artifacts; the evidence register itself is dated 15 October, and uploaded excluded records include older material. Read this sentence as “the current artifacts listed in the evidence register.” The currency outcome remains supported because the register is also within the 90-day window. This is a presentation precision issue, not a failed control outcome.

The incident quote displays the contractual deadline/contact/staffing; the signature/executed statement is available elsewhere on the same cited source page. Reviewers should inspect that page before recording acceptance.

This compact run does not exercise wrong-environment scale records, unreadable/malformed PDFs, unsupported formats, byte-identical duplicates, or 100-document analysis. Those separate tests must not be reported as passed by this assessment. The result is a bounded synthetic demonstration, not a real vendor approval, legal certification, generalized accuracy claim, or proof of preventing a real incident.

## Prior defect and retest trail

The earlier v1.0 artifact generated at 06:20:10Z passed five of six expected control outcomes. It misclassified the executed incident addendum as buyer policy, then excluded it for a version mismatch. The questionnaire backup snippet also depended on preceding context, and narratives contained internal IDs. v1.1 changed the general classification/prompt rules and invalidated caches; this assessment verifies newly generated outputs rather than manually corrected statuses. Frozen fixtures and expectations were not changed.
