# EvidenceDesk synthetic demonstration scenario

The buyer is **Aster Finance**, the vendor is **Nimbus Support**, and the reviewed service is **Customer Support Platform**, **production**, during **October 2026**. The policy version is **3.0**, effective 1 October 2026, and the review evidence cutoff is 15 October 2026. All entities and operational events are fictional.

The internal policy explicitly requires India-only primary storage and India-only customer-data backups for that same service and period. This requirement is illustrative company policy, not a claim about universal law.

## Demonstration story

The analyst opens an evidence review containing 10 documents and 14 pages. The questionnaire claims that all customer data and backups are in India. The current inventory's second page lists a disaster-recovery replica in Singapore. Both documents explicitly identify Aster Finance's production customer data, the same service and October 2026. The inventory states that Singapore is the physical storage location, and that the data is identifiable production customer data, preventing staging, transit and office-location ambiguity.

The analyst compares the policy, vendor claim and operational record, records a clarification request, reviews a grounded follow-up question and exports the review. The export must retain the AI finding separately from the later human action. This scenario describes intended behavior, not completed implementation or model output.

## Core source map

| Document ID | Pages | Main role |
|---|---:|---|
| `policy-v3` | 3 | Six approved internal requirements; backups explicitly in scope |
| `questionnaire-202610` | 2 | Current India-only vendor claim and open deletion evidence request |
| `backup-inventory-202610` | 2 | Current production inventory; Singapore replica on page 2 |
| `primary-assets-202610` | 1 | Primary production customer stores in Mumbai and Delhi |
| `access-review-202610` | 1 | Completed review of 12 privileged accounts, one removal, dated approval |
| `incident-addendum-202610` | 1 | Signed 12-hour notice commitment and monitored contact |
| `evidence-register-202610` | 1 | Current evidence dates and missing deletion certificate |
| `old-questionnaire-202501` | 1 | Superseded historical answer, excluded from current conclusions |
| `other-vendor-deletion` | 1 | Current but unrelated Cedar Analytics certificate |
| `untrusted-attachment` | 1 | Embedded prompt-injection text that must be ignored |

## Expected six-control interpretation

- **Primary data location:** evidence found for active primary stores in India. This does not mean all customer-data copies are in India.
- **Backup location:** conflicting evidence. Policy page 1, questionnaire page 1 and inventory page 2 establish the three-source discrepancy.
- **Deletion:** the required completed certificate for `DEL-2026-041` is not evidenced. A qualified partial-evidence outcome is acceptable if it clearly says no completed execution evidence exists. Lack of a certificate does not prove deletion never occurred.
- **Access review:** evidence found in the completed, approved current privileged-access review.
- **Incident response:** evidence found in the signed 12-hour commitment, which meets the policy's maximum of 24 hours. Tabletop exercises support operational context but do not replace the contract.
- **Evidence currency:** current operational evidence is within 90 days of the cutoff. Archived records must be explicitly excluded. A qualified partial/review status can be defensible if the explanation accurately distinguishes current, excluded and missing evidence.

Expected outcomes live only in evaluation fixtures. The application must derive actual results through its analysis pipeline.

## Scale and adversarial coverage

The 106-document clean scale pack includes 96 additional PDFs across 12 document categories with meaningful differences in operational record type, component, date, vendor, environment and period. Repeated fictional names and templates preserve a coherent review, while distinct content creates retrieval and applicability challenges. The documents are deliberately short; no claim about long-document enterprise throughput is justified by this pack alone.

Separate adverse fixtures test malformed input, a valid PDF with no text layer, unsupported format and a byte-identical duplicate. The frozen expectation manifest also contains invalid citation examples for a nonexistent quote, out-of-range page and unknown document. A real quotation must additionally support its assigned conclusion: substring validation alone is insufficient.

The fixture manifest predates generation/model calls. Generated manifests record its checksum. `evals/fixtures.verification.json` reports only deterministic generation and extraction checks, with zero model calls. Actual pipeline and deployed evaluation results must be saved separately separately by the evaluator.

## Suggested follow-up question

"Your October questionnaire says all production customer-data backups are stored only in India, while inventory INV-2026-10 lists replica BKP-SG-02 in Singapore. Please confirm the replica's current location and data scope, explain the discrepancy, and provide a dated corrected inventory or remediation evidence. Please also provide the completed deletion certificate for request DEL-2026-041."

This is a draft for analyst review. Sending it to a real vendor is outside the demonstration workflow.
