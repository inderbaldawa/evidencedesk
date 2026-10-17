"""Policy-pack boundaries tested offline; no AI calls or credentials."""
import copy
import json
import hashlib
from pathlib import Path
from pypdf import PdfReader
import unittest
from unittest.mock import patch

from app.backend.pipeline import analyze_review, cache_key
from app.backend.policy_packs import get_policy_pack, list_policy_packs
from app.backend.schemas import CONTROL_NAMES, ExtractionBatch
from app.tests.test_pipeline import FakeAI, REVIEW, context


def review_for(pack_id):
    return {**REVIEW, "policy_pack_id": pack_id, "policy_pack_version": "1.0"}


def doc_for(review, doc_id, role, *, controls=None, quote="Literal scoped evidence exists."):
    pack = get_policy_pack(review["policy_pack_id"])
    document = {"id": doc_id, "name": doc_id + ".pdf", "sha256": doc_id, "status": "pending",
                "pages": [{"page": 1, "text": quote}]}
    data = {"document_id": doc_id, "context": context(document_type="policy" if role == "requirement" else "operational_record"),
            "suspicious_instructions": False,
            "observations": [{"control_id": control, "role": role, "page": 1, "quote": quote, "statement": quote}
                             for control in (controls if controls is not None else [c["id"] for c in pack["controls"]])]}
    document["extraction"] = {"cache_key": cache_key(document, review), "data": data}
    return document


class ExtractionAI(FakeAI):
    requested = []
    injected_control = None

    def generate(self, **kwargs):
        request = json.loads(kwargs["prompt"])
        if "documents" not in request:
            return super().generate(**kwargs)
        self.usage["calls"] += 1
        self.requested.append(request)
        documents = []
        for doc in request["documents"]:
            policy = doc["document_id"] == "policy"
            controls = [self.injected_control] if self.injected_control else list(request["controls"])
            documents.append({"document_id": doc["document_id"],
                              "context": context(document_type="policy" if policy else "operational_record"),
                              "suspicious_instructions": False,
                              "observations": [{"control_id": c, "role": "requirement" if policy else "record",
                                                "page": 1, "quote": doc["pages"][0]["text"], "statement": "Scoped statement"}
                                               for c in controls]})
        return {"documents": documents}


class PolicyPackTests(unittest.TestCase):
    def test_registry_is_bounded_versioned_and_defensive(self):
        packs = list_policy_packs()
        self.assertEqual([p["id"] for p in packs], ["data-handling", "security-assurance", "ai-vendor"])
        self.assertEqual({c["id"]: c["name"] for c in packs[0]["controls"]}, CONTROL_NAMES)
        self.assertTrue(all(p["version"] == "1.0" and len(p["controls"]) == 6 for p in packs))
        packs[0]["controls"][0]["id"] = "mutated"
        self.assertEqual(get_policy_pack("data-handling")["controls"][0]["id"], "data_location")
        for invalid in ("invented", None, [], ""):
            with self.assertRaises(ValueError):
                get_policy_pack(invalid)

    @patch("app.backend.pipeline.AIClient", FakeAI)
    def test_each_pack_reconciles_exactly_its_controls_and_reuses_own_cache(self):
        for pack in list_policy_packs():
            review = review_for(pack["id"])
            result = analyze_review(review, [doc_for(review, "policy", "requirement"), doc_for(review, "record", "record")])
            self.assertEqual([f["control_id"] for f in result["findings"]], [c["id"] for c in pack["controls"]])
            self.assertTrue(all(f["status"] == "evidence_found" for f in result["findings"]))
            self.assertEqual(result["analysis"]["calls"], 6)
            self.assertEqual(result["analysis"]["policy_pack_id"], pack["id"])
            repeated = analyze_review({**review, "analysis": result["analysis"]}, result["documents"])
            self.assertEqual(repeated["analysis"]["calls"], 0)
            self.assertEqual(repeated["analysis"]["reconciliation_cache_hits"], 6)

    @patch("app.backend.pipeline.AIClient", ExtractionAI)
    def test_switching_pack_invalidates_extraction_and_shared_control_reconciliation(self):
        old_review = review_for("data-handling")
        old = analyze_review(old_review, [doc_for(old_review, "policy", "requirement"), doc_for(old_review, "record", "record")])
        review = {**review_for("security-assurance"), "analysis": old["analysis"]}
        result = analyze_review(review, old["documents"])
        self.assertEqual(result["analysis"]["cache_hits"], 0)
        self.assertEqual(result["analysis"]["reconciliation_cache_hits"], 0)
        self.assertEqual(result["analysis"]["calls"], 7)
        self.assertEqual(ExtractionAI.requested[-1]["review_scope"]["policy_pack_version"], "1.0")
        self.assertEqual(len(ExtractionAI.requested[-1]["control_guidance"]), 6)

    def test_unsupported_pack_and_version_fail_before_client_initialization(self):
        for review in ({**REVIEW, "policy_pack_id": "invented"},
                       {**review_for("ai-vendor"), "policy_pack_version": "2.0"}):
            with patch("app.backend.pipeline.AIClient") as client:
                with self.assertRaises(ValueError):
                    analyze_review(review, [])
                client.assert_not_called()

    @patch("app.backend.pipeline.AIClient", FakeAI)
    def test_inactive_versions_are_preserved_but_never_counted_used_or_deduplicated(self):
        review = review_for("ai-vendor")
        policy, record = doc_for(review, "policy", "requirement"), doc_for(review, "record", "record")
        old = copy.deepcopy(record)
        old.update(id="old-record", is_current=False, status="failed", error="Old failure")
        result = analyze_review(review, [old, policy, record])
        self.assertEqual(result["documents"][0], old)
        self.assertEqual(result["analysis"]["coverage"], {"submitted": 2, "processed": 2, "failed": 0,
                                                          "duplicates": 0, "excluded_scope": 0, "superseded": 1, "pages": 2})
        self.assertTrue(all(f["status"] == "evidence_found" for f in result["findings"]))
        self.assertFalse(any(c["document_id"] == "old-record" for f in result["findings"] for c in f["citations"]))

    @patch("app.backend.pipeline.AIClient", ExtractionAI)
    def test_registered_but_wrong_pack_control_fails_extraction_even_from_cache(self):
        review = review_for("ai-vendor")
        document = doc_for(review, "policy", "requirement", controls=["backup_location"])
        with patch.object(ExtractionAI, "injected_control", "backup_location"):
            result = analyze_review(review, [document])
        self.assertEqual(result["analysis"]["cache_hits"], 0)
        self.assertEqual(result["analysis"]["coverage"]["failed"], 1)
        self.assertFalse(result["analysis"]["complete"])
        self.assertTrue(all(not f["citations"] for f in result["findings"]))

    @patch("app.backend.pipeline.AIClient", FakeAI)
    def test_new_pack_preserves_literal_quote_and_scope_guards(self):
        review = review_for("security-assurance")
        policy, record = doc_for(review, "policy", "requirement"), doc_for(review, "record", "record")
        record["extraction"]["data"]["observations"][0]["quote"] = "Invented evidence."
        result = analyze_review(review, [policy, record])
        self.assertEqual(result["findings"][0]["status"], "needs_human_review")
        self.assertEqual(len(result["analysis"]["citation_validation_failures"]), 1)
        record = doc_for(review, "record", "record")
        record["extraction"]["data"]["context"]["vendor"] = "Wrong vendor"
        result = analyze_review(review, [policy, record])
        self.assertEqual(result["analysis"]["coverage"]["excluded_scope"], 1)
        self.assertTrue(all(f["status"] == "not_evidenced" for f in result["findings"]))

    @patch("app.backend.pipeline.AIClient", FakeAI)
    def test_reconciliation_cannot_switch_to_another_pack_control(self):
        review = review_for("ai-vendor")
        original = FakeAI.generate
        def wrong_control(client, **kwargs):
            answer = original(client, **kwargs)
            answer["control_id"] = "backup_location"
            return answer
        with patch.object(FakeAI, "generate", wrong_control):
            result = analyze_review(review, [doc_for(review, "policy", "requirement"), doc_for(review, "record", "record")])
        self.assertFalse(result["analysis"]["complete"])
        self.assertTrue(all(f["status"] == "needs_human_review" for f in result["findings"]))
        self.assertTrue(all(f["control_id"] != "backup_location" for f in result["findings"]))

    def test_cache_identity_contains_resolved_version_even_with_same_control_set(self):
        review = review_for("ai-vendor")
        document = doc_for(review, "record", "record")
        key = cache_key(document, review)
        newer_pack = get_policy_pack("ai-vendor")
        newer_pack["version"] = "2.0"
        with patch("app.backend.pipeline.review_policy_pack", return_value=newer_pack):
            self.assertNotEqual(cache_key(document, review), key)

    def test_demo_manifest_has_three_hashed_readable_synthetic_files_per_pack(self):
        root = Path(__file__).resolve().parents[2]
        manifest = json.loads((root / "data/demo-packs/demo_manifest.json").read_text())
        self.assertEqual(set(manifest["packs"]), {p["id"] for p in list_policy_packs()})
        for pack_id, demo in manifest["packs"].items():
            self.assertEqual(demo["policy_pack_id"], pack_id)
            self.assertEqual(demo["policy_pack_version"], get_policy_pack(pack_id)["version"])
            self.assertEqual(len(demo["files"]), 3)
            for field in ("project", "vendor", "service", "environment", "period", "policy_version"):
                self.assertTrue(demo[field])
            for entry in demo["files"]:
                path = root / entry["path"]
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry["sha256"])
                reader = PdfReader(path)
                self.assertEqual(len(reader.pages), entry["pages"])
                self.assertTrue(all("SYNTHETIC" in page.extract_text() for page in reader.pages))

    def test_unregistered_control_is_rejected_by_schema(self):
        review = review_for("ai-vendor")
        doc = doc_for(review, "record", "record", controls=["unregistered"])
        with self.assertRaises(ValueError):
            ExtractionBatch.model_validate({"documents": [doc["extraction"]["data"]]})


if __name__ == "__main__":
    unittest.main()
