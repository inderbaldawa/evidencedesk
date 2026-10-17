"""Offline safety invariants. No Google credentials or network calls required."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.backend.ai_client import BudgetExceeded, BudgetLedger
from app.backend.pipeline import analyze_review, cache_key, scope_exclusion, validate_quote, RECONCILE_SYSTEM
from app.backend.schemas import CONTROL_NAMES, ExtractionBatch, Reconciliation, response_schema


def context(**changes):
    return {"vendor": "Example Vendor", "service": "Service A", "environment": "production", "period": "2026-10",
            "version": "1.0", "document_type": "operational_record", "currency": "current", "scope_status": "applicable",
            "scope_reason": "Matching scope stated in header", **changes}


REVIEW = {"vendor": "Example Vendor", "service": "Service A", "environment": "production", "period": "2026-10", "policy_version": "1.0"}


def cached_document(doc_id, document_type, role, *, quote="Literal evidence exists.", bad_quote=False):
    document = {"id": doc_id, "name": doc_id + ".pdf", "sha256": doc_id, "status": "pending", "pages": [{"page": 1, "text": quote}]}
    data = {"document_id": doc_id, "context": context(document_type=document_type), "suspicious_instructions": False,
            "observations": [{"control_id": control, "role": role, "page": 1,
                              "quote": "Invented quotation." if bad_quote else quote, "statement": quote} for control in CONTROL_NAMES]}
    document["extraction"] = {"cache_key": cache_key(document, REVIEW), "data": data}
    return document


class FakeAI:
    def __init__(self):
        self.model = "offline-test-double"
        self.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0}

    def generate(self, **kwargs):
        self.usage["calls"] += 1
        request = json.loads(kwargs["prompt"])
        return {"control_id": request["control_id"], "status": "evidence_found", "requirement": "Literal evidence exists.",
                "explanation": "The supplied record supports the requirement.", "next_action": "Review this source.",
                "follow_up_question": "Is this source current?", "evidence_ids": [e["evidence_id"] for e in request["evidence"]]}


class PipelineTests(unittest.TestCase):
    def test_reconciliation_bounded_citations_are_requested_and_enforced(self):
        self.assertEqual(response_schema(Reconciliation)["properties"]["evidence_ids"]["maxItems"], 12)
        self.assertIn("at most 12 unique evidence_ids", RECONCILE_SYSTEM)
        value = {"control_id": "data_location", "status": "evidence_found", "requirement": "A requirement",
                 "explanation": "A conclusion", "next_action": "Review", "follow_up_question": "Confirm?",
                 "evidence_ids": [f"doc:{i}" for i in range(13)]}
        with self.assertRaises(ValueError):
            Reconciliation.model_validate(value)
        value["evidence_ids"] = value["evidence_ids"][:12]
        self.assertEqual(len(Reconciliation.model_validate(value).evidence_ids), 12)

    def test_provider_schema_is_small_but_post_generation_literals_remain_strict(self):
        schema_text = json.dumps(response_schema(ExtractionBatch))
        for key in ('"enum"', '"minimum"', '"maximum"', '"maxItems"', '"minItems"', '"$ref"'):
            self.assertNotIn(key, schema_text)
        document = cached_document("doc", "policy", "requirement")["extraction"]["data"]
        document["context"]["document_type"] = "invented_kind"
        with self.assertRaises(ValueError):
            ExtractionBatch.model_validate({"documents": [document]})

    def test_quote_validation_is_page_specific_and_whitespace_tolerant(self):
        doc = {"pages": [{"page": 1, "text": "alpha\n  beta"}, {"page": 2, "text": "gamma"}]}
        self.assertTrue(validate_quote(doc, 1, "alpha beta"))
        self.assertFalse(validate_quote(doc, 2, "alpha beta"))
        self.assertFalse(validate_quote(doc, 1, ""))

    def test_scope_mismatch_superseded_and_old_policy_are_excluded(self):
        self.assertIsNotNone(scope_exclusion(context(vendor="Other Vendor"), REVIEW))
        self.assertIsNotNone(scope_exclusion(context(environment="test"), REVIEW))
        self.assertIsNotNone(scope_exclusion(context(period="2026-09"), REVIEW))
        self.assertIsNotNone(scope_exclusion(context(currency="superseded"), REVIEW))
        self.assertIsNotNone(scope_exclusion(context(document_type="policy", version="0.9"), REVIEW))
        self.assertIsNone(scope_exclusion(context(environment="prod"), REVIEW))

    @patch("app.backend.pipeline.AIClient", FakeAI)
    def test_signed_commitment_version_is_not_compared_with_buyer_policy_version(self):
        commitment_context = context(document_type="signed_commitment", version="AGREEMENT-77",
                                     period="2026-10-01 through 2027-09-30")
        self.assertIsNone(scope_exclusion(commitment_context, REVIEW))
        # The same version mismatch must still reject a competing buyer policy.
        self.assertIsNotNone(scope_exclusion({**commitment_context, "document_type": "policy"}, REVIEW))
        policy = cached_document("policy", "policy", "requirement")
        commitment = cached_document("contract", "signed_commitment", "requirement")
        data = commitment["extraction"]["data"]
        data["context"] = commitment_context
        data["observations"] = [o for o in data["observations"] if o["control_id"] == "incident_response"]
        result = analyze_review(REVIEW, [policy, commitment])
        finding = next(f for f in result["findings"] if f["control_id"] == "incident_response")
        self.assertEqual(finding["status"], "evidence_found")
        contract_citations = [c for c in finding["citations"] if c["document_id"] == "contract"]
        self.assertEqual(len(contract_citations), 1)
        self.assertEqual(contract_citations[0]["role"], "support")

    def test_cache_changes_when_review_scope_or_page_changes(self):
        document = cached_document("doc", "policy", "requirement")
        self.assertNotEqual(cache_key(document, REVIEW), cache_key(document, {**REVIEW, "period": "2026-11"}))
        document["pages"][0]["text"] += " changed"
        self.assertNotEqual(document["extraction"]["cache_key"], cache_key(document, REVIEW))

    @patch("app.backend.pipeline.AIClient", FakeAI)
    def test_cached_extraction_is_revalidated_and_bad_quotes_cannot_support_findings(self):
        policy = cached_document("policy", "policy", "requirement")
        record = cached_document("record", "operational_record", "record", bad_quote=True)
        result = analyze_review(REVIEW, [policy, record])
        self.assertEqual(result["analysis"]["calls"], 0)
        self.assertEqual(len(result["analysis"]["citation_validation_failures"]), 6)
        self.assertTrue(all(f["status"] == "needs_human_review" for f in result["findings"]))
        self.assertTrue(all(c["document_id"] == "policy" for f in result["findings"] for c in f["citations"]))

    @patch("app.backend.pipeline.AIClient", FakeAI)
    def test_claims_cannot_be_promoted_to_operational_proof(self):
        policy = cached_document("policy", "policy", "requirement")
        questionnaire = cached_document("questionnaire", "questionnaire", "record")
        result = analyze_review(REVIEW, [policy, questionnaire])
        self.assertTrue(all(f["status"] != "evidence_found" for f in result["findings"]))
        self.assertTrue(all(c["role"] != "record" for f in result["findings"] for c in f["citations"]))

    @patch("app.backend.pipeline.AIClient", FakeAI)
    def test_unreadable_coverage_prevents_false_clearance_and_duplicate_is_counted(self):
        policy = cached_document("policy", "policy", "requirement")
        record = cached_document("record", "operational_record", "record")
        duplicate = {**record, "id": "copy"}
        broken = {"id": "broken", "name": "broken.pdf", "pages": [], "status": "failed", "error": "Unreadable PDF"}
        result = analyze_review(REVIEW, [policy, record, duplicate, broken])
        self.assertEqual(result["analysis"]["coverage"]["duplicates"], 1)
        self.assertEqual(result["analysis"]["coverage"]["failed"], 1)
        self.assertTrue(all(f["status"] == "needs_human_review" for f in result["findings"]))

    @patch("app.backend.pipeline.AIClient", FakeAI)
    def test_absent_evidence_is_limited_to_processed_document_set(self):
        result = analyze_review(REVIEW, [cached_document("policy", "policy", "requirement")])
        self.assertEqual(result["analysis"]["calls"], 0)
        self.assertTrue(all(f["status"] == "not_evidenced" for f in result["findings"]))
        self.assertTrue(all("not proof" in f["explanation"] for f in result["findings"]))

    @patch("app.backend.pipeline.AIClient", FakeAI)
    def test_unchanged_review_reuses_reconciliation_but_revalidates_citations(self):
        result = analyze_review(REVIEW, [cached_document("policy", "policy", "requirement"), cached_document("record", "operational_record", "record")])
        self.assertEqual(result["analysis"]["calls"], 6)
        repeated = analyze_review({**REVIEW, "analysis": result["analysis"]}, result["documents"])
        self.assertEqual(repeated["analysis"]["calls"], 0)
        self.assertEqual(repeated["analysis"]["reconciliation_cache_hits"], 6)
        self.assertEqual(repeated["findings"], result["findings"])


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ledger.json"
        self.path.write_text(json.dumps({"enabled": True, "calls": 0, "input_tokens": 0, "output_tokens": 0,
                                         "cost_usd": 0, "reservations": {}}))
        self.ledger = BudgetLedger(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_outstanding_reservations_count_toward_limits(self):
        reservation = self.ledger.reserve(1000)
        with self.assertRaises(BudgetExceeded):
            self.ledger.reserve(1000)
        self.ledger.settle(reservation, (100, 200))
        self.assertTrue(self.ledger.reserve(1000))

    def test_unknown_failure_charges_full_reservation(self):
        reservation = self.ledger.reserve(1000)
        charged = self.ledger.settle(reservation)
        self.assertEqual(charged["output_tokens"], 65536)
        self.assertEqual(json.loads(self.path.read_text())["calls"], 1)

    def test_usage_overrun_disables_ledger(self):
        reservation = self.ledger.reserve(1000)
        self.ledger.settle(reservation, (1001, 100))
        self.assertFalse(json.loads(self.path.read_text())["enabled"])
        with self.assertRaises(BudgetExceeded):
            self.ledger.reserve(1000)

    def test_missing_ledger_never_creates_one(self):
        self.path.unlink()
        with self.assertRaises(BudgetExceeded):
            self.ledger.reserve(1000)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
