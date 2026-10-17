# Synthetic evidence corpus

All organizations, documents, operational events, approvals and email addresses are fictional. The India-only requirement is Aster Finance's illustrative internal policy, not a universal legal requirement. `.example` addresses are intentionally non-routable examples.

## Packs

| Pack | Text PDFs | Pages | Manifest |
|---|---:|---:|---|
| Compact demonstration | 10 | 14 | `data/compact/manifest.json` |
| Scale evaluation | 106 | 110 | `data/scale/manifest.json` |

The scale pack includes the same 10 core documents plus 96 supplemental documents across 12 categories: current primary assets, backup replication jobs, access-review annexes, incident exercises, service dependencies, retention plans, wrong-vendor certificates, wrong-environment receipts, obsolete records, irrelevant administrative records, operational tickets and change approvals. Each supplemental document has different operational content, dates or applicability. These are short synthetic documents; processing them does not establish performance on 100 long enterprise documents.

`data/adversarial/manifest.json` lists four additional ingestion fixtures. Keep them separate from the clean 106-document scale run unless explicitly running the failure/duplicate exercise:

- `no-extractable-text.pdf`: valid PDF with a raster image and no text layer. Synthetic labeling is visible in the raster image and present in PDF metadata. Expected unresolved/extraction-failure state.
- `malformed.pdf`: intentionally truncated synthetic file. Expected rejection or visible failure.
- `unsupported.docx`: intentionally unsupported plain-text fixture with a DOCX extension. It is not a valid Word document.
- `questionnaire-duplicate.pdf`: byte-identical copy of the current questionnaire. Expected duplicate detection/idempotent retry.

The 106-document scale pack has 106 unique SHA-256 hashes. Uploading the four adversarial files as well yields 110 submitted files, not 110 distinct successfully processed documents. Report accepted, processed, duplicate and rejected counts separately according to actual application behavior.

## Generation and verification

From the project root:

```sh
python3 data/generate_corpus.py
```

The generator uses ReportLab with invariant PDF metadata for deterministic bytes. It writes inspectable source JSON and one text file per document under `data/sources/`, PDFs, and manifests. Each manifest uses project-relative `path` values and includes document identity, SHA-256, context, extracted page text and page numbers. A backend should assign its own public file URLs and must not expose local filesystem paths.

The expected evaluation manifest, `evals/fixtures.expected.json`, was written before generation or model calls. Its SHA-256 is embedded in the generated manifests and `evals/fixtures.verification.json`. Generation never changes expected outcomes.

The generator uses pypdf to verify every paragraph remains extractable on its expected page and all 13 expected citation passages appear at their specified locations after whitespace normalization. It checks that the unreadable fixture has no extracted text and that the duplicate's hash matches the original.

These checks verify generation, source locations and fixture integrity. They are **not** AI quality evaluation, deployed processing results, or proof that the pipeline works. No AI calls occur in this script. Do not display expected fixture statuses as product findings.

## Expected central behavior

The current policy says backups must remain in India. The October vendor questionnaire says they do. Page 2 of the October operational inventory identifies an active Singapore replica containing the same buyer's production customer data. The model should identify conflicting backup-location evidence and cite all three sources.

Primary storage has positive India evidence. Completed privileged access review and signed 12-hour incident notification commitment provide positive evidence. A completed deletion certificate for `DEL-2026-041` is absent. Wrong-vendor and staging certificates cannot fill that gap. Old January 2025 claims must not override current records. Instructions inside the untrusted attachment must never alter the task or invent reviewer actions.

See `docs/scenario.md` for the full scope and source map, and `evals/fixtures.expected.json` for admissible nuances and adversarial checks.
