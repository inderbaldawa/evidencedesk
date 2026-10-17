# Local workflow verification — 17 October 2026

Real Gemini model analysis, not fixture-generated findings. The sample preserves the compact v1.1 run; the fresh HTTP test creates a separate review.

## Browser exercise

- Opened the real previously processed synthetic sample and selected Backup location.
- Inspected the displayed buyer requirement, complete vendor claim and Singapore inventory quotation side by side.
- Open PDF page2 created an original inventory PDF tab with `#page=2`. Browser automation cannot inspect blob URLs; the built-in PDF viewer was not visually inspected.
- Made an editable copy, selected Request clarification, saved a scope-check note and retained the drafted follow-up question.
- Reloaded and verified decision, note, follow-up draft, one decision-history entry and the 1/6 reviewed count.
- Exported the actual stored reviewed record. PDF text contains the decision and note; all five rendered pages were visually inspected. Corrected an orphan section heading and replaced raw history dictionaries with readable entries.

Screenshots: `docs/screenshots/local-three-source-comparison.png` and `docs/screenshots/local-saved-reviewer-decision.png`.

## Fresh HTTP + separate durable worker

Executed `evals/run_local_http.py --run` against localhost:8080 with an explicitly enabled model ledger. Seven uploads comprised three valid scenario PDFs, one duplicate, one PDF without text, one malformed PDF and one unsupported file. The upload API stored evidence; a separate worker process claimed the persisted job and performed extraction and real analysis.

Result: three processed, three failed, one duplicate; review correctly **incomplete**. The supported backup contradiction remained visible; unreadable evidence did not become a passing review. The source API returned exactly the original PDF bytes. Another session was denied access to review data, JSON export and source PDF. Saved clarification appeared in JSON and the PDF export succeeded. Results and usage are in `local-http-summary.json`.

## Remaining hosted checks

Cloud IAM, Firebase identity/revocation checks, Linux image startup, GCS/Firestore persistence and live Cloud Run job dispatch require provisioning approval and are not yet verified. Local success does not establish deployed success.
