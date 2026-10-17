"""One real 106-PDF scale run. Expected findings never enter the product pipeline."""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.backend.documents import coverage, ingest_pdf
from app.backend.store import get_store, new_review, now
from app.backend.worker import process


def main():
    started = time.monotonic()
    manifest_path = ROOT / "data/scale/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    ledger_path = Path(os.environ["EVIDENCEDESK_BUDGET_LEDGER"])
    before = json.loads(ledger_path.read_text())
    store = get_store()
    if store.get("local-scale"):
        raise RuntimeError("local-scale already exists; this runner refuses automatic retries or overwrites.")
    scope = {key: value for key, value in manifest["review_scope"].items()
             if key in ("vendor", "service", "environment", "period", "policy_version")}
    review = new_review("evaluation", name="Nimbus Support | 106-document scale evaluation", **scope)
    review["id"] = "local-scale"
    known = {}
    for source in manifest["documents"]:
        path = (ROOT / source["path"]).resolve()
        if not path.is_relative_to(ROOT):
            raise RuntimeError("Manifest source is outside the project.")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != source["sha256"]:
            raise RuntimeError(f"Source hash does not match manifest: {source['name']}")
        document = ingest_pdf(source["name"], data, store, review["id"], known)
        if document["status"] not in ("failed", "duplicate"):
            known[document["sha256"]] = document["id"]
        review["documents"].append(document)
    review["coverage"] = coverage(review)
    store.put(review)
    ingestion_seconds = time.monotonic() - started
    print(json.dumps({"event": "ingested", "at": now(), "coverage": review["coverage"],
                      "ingestion_seconds": round(ingestion_seconds, 3)}), flush=True)
    error = None
    try:
        process(review["id"], store)
    except Exception as exc:
        error = f"{type(exc).__name__}: {str(exc)[:600]}"
    finally:
        actual = store.get(review["id"])
        (ROOT / "evals/scale-actual.json").write_text(json.dumps(actual, indent=2))
        after = json.loads(ledger_path.read_text())
        metrics = {
            "review_id": review["id"], "generated_at": now(), "manifest": "data/scale/manifest.json",
            "manifest_document_count": len(manifest["documents"]), "manifest_page_count": manifest.get("page_count"),
            "status": actual["status"], "coverage": actual["coverage"],
            "ingestion_seconds": round(ingestion_seconds, 3), "wall_seconds": round(time.monotonic() - started, 3),
            "analysis": {k: v for k, v in actual.get("analysis", {}).items() if k != "reconciliation_cache"},
            "ledger_delta": {k: after[k] - before[k] for k in ("calls", "input_tokens", "output_tokens", "cost_usd")},
            "ledger_totals_after": {k: after[k] for k in ("calls", "input_tokens", "output_tokens", "cost_usd")},
            "runner_error": error, "sample_modified": False,
        }
        (ROOT / "evals/scale-metrics.json").write_text(json.dumps(metrics, indent=2))
        print(json.dumps(metrics, indent=2), flush=True)
    if error:
        raise RuntimeError(error)


if __name__ == "__main__":
    main()
