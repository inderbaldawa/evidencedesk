# Evaluation status

## Verified corpus preparation

The compact pack contains 10 synthetic PDFs and 14 pages. The scale pack contains 106 distinct synthetic PDFs and 110 pages across 13 categories including the core set. The generator verifies every source paragraph on its expected page, 13 frozen citation passages, the duplicate hash and the no-text-layer fixture. The expected manifest was frozen before model tuning. These are generation checks, not AI accuracy measurements.

## Offline tests

`python -m pytest app/tests -q` exercises citation validation, scope exclusions, signed-commitment classification, untrusted inputs, coverage failures, reviewer/API state and budget accounting with synthetic inputs and model doubles. Run it against the exact source revision you intend to use. Offline tests do not establish deployed cloud behavior.

## Actual AI evaluation

A completed real Gemini compact run using `evidencedesk-1.1` is included in `compact-actual.public.json`. It was generated at 2026-10-17T06:25:39.084973+00:00 and processed coverage is recorded in that artifact. Run metrics: 9 calls, 17020 input tokens, 6163 output tokens, 64.561 seconds and $0.071752 estimated model cost. Reused extraction count: 0. These describe this run, not cumulative development usage or generic throughput.

This sanitized artifact removes owner/session, blob paths, model caches and raw provider payloads while preserving actual findings and citations. The separate implementation-team semantic review matched all 6 control statuses to frozen expectations and validated all 18 displayed citations against source IDs, pages and literal text. See `compact-semantic-review.md` for its bounded scope and wording qualification. This is not external certification or a general accuracy estimate.

## Fresh local HTTP workflow

`local-http-summary.json` records a real HTTP upload-to-worker test with 7 submissions: 3 processed documents, 3 failed inputs (malformed PDF, image-only PDF and unsupported format), and 1 byte-identical duplicate. The review correctly remains `incomplete` because failed inputs must stay unresolved. The run made 6 real generation calls, identified the backup conflict, denied a second local identity access to three private routes, returned exact original PDF bytes, preserved a reviewer decision in JSON export, and returned a PDF export. This is a local cookie-session check, not deployed Firebase isolation validation. The summary does not expose its internal review identifier.

To repeat this billable test, first run the local API with the same data directory and explicitly configured AI environment used by the worker, create `evals/artifacts/`, and run `python evals/run_local_http.py --run`. It creates a new review and launches one worker pass; do not run it as an offline unit test.

The 106-document / 110-page scale evaluation completed after an initial incomplete attempt and a targeted retry of two failed control reconciliations. Total attributable usage across those attempts was 35 calls, 110125 input tokens, 39104 output tokens and $0.458467 estimated model cost. Combined active wall time was 318.836 seconds; this excludes debugging and elapsed time between attempts.

The initial attempt extracted all 106 documents but two reconciliation responses exceeded the evidence-ID count schema limit. The targeted retry reused all 106 extractions and four prior control results and made two new model calls. Its isolated 10.724-second duration must not be represented as full-corpus throughput. `scale-actual.public.json` preserves the final findings and scope exclusions; `scale-metrics.public.json` makes both attempts explicit. Per-run usage is used because an unrelated local HTTP test overlapped on the shared budget ledger.

The separate semantic review matched all six control statuses to the frozen expectations, validated all 33 displayed citations against literal text on the cited PDF pages, and confirmed 35 correct scope exclusions with none cited. Four currency quotations require full-page context to confirm vendor, service, environment and date; their snippets alone provide weak scope context. See `scale-semantic-review.md`. These bounded synthetic checks are not a 100% general-accuracy claim or external certification.

## Separate reviewer cross-check

An additional reviewer who did not author the extraction/reconciliation pipeline read the saved results, frozen expectations and actual PDF pages independently. [The cross-review](independent-cross-review.md) confirms all 51 displayed citations against literal PDF text after whitespace-only normalization, all 116 compact/scale PDF-instance hashes, and the critical control outcomes. It discloses limitations in currency wording and citation breadth, primary-location narrative support and retry attribution. This is a qualified review of two synthetic saved runs by another project contributor, not external certification or a general accuracy claim.

## Still separate verification work

Cloud deployment, real identity isolation, fresh deployed analysis, final public links require their own recorded checks. Adversarial files exist, but fixture generation does not prove their behavior through the deployed API. Do not infer a legal-compliance score or real-world time savings from these results.
