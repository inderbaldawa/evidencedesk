"""Cloud ledger tests are entirely offline: no Firestore or model requests."""
import copy
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from app.backend.ai_client import BudgetExceeded
from app.backend.budget_cloud import (
    FirestoreBudgetLedger, development_ledger_example, reserve_state, settle_state,
)


def approved():
    value = development_ledger_example("test-only; not a deployment approval")
    value["enabled"] = True
    return value


class FakeSnapshot:
    def __init__(self, data):
        self.exists = data is not None
        self.data = data

    def to_dict(self):
        return copy.deepcopy(self.data)


class FakeReference:
    def __init__(self, data):
        self.data = data

    def get(self, *, transaction):
        return FakeSnapshot(self.data)


class FakeTransaction:
    def __init__(self):
        self.updates = 0

    def update(self, reference, value):
        self.updates += 1
        reference.data = copy.deepcopy(value)


class FakeClient:
    def __init__(self, data):
        self.reference = FakeReference(data)
        self.tx = FakeTransaction()
        self.transaction_count = 0

    def document(self, path):
        self.path = path
        return self.reference

    def transaction(self):
        self.transaction_count += 1
        return self.tx


class StateTests(unittest.TestCase):
    def test_missing_explicit_approval_and_limits_fail_closed(self):
        for key in ["approval_reference", "approved_limits", "approved_dispatch_stop_usd", "model"]:
            ledger = approved()
            ledger.pop(key)
            with self.assertRaises(BudgetExceeded):
                reserve_state(ledger, 100, 8192, "a", 1)

    def test_pending_reservations_count_and_original_state_is_immutable(self):
        ledger = approved()
        ledger["approved_limits"]["output_tokens"] = 10_000
        changed = reserve_state(ledger, 100, 8192, "a", 1)
        self.assertEqual(ledger["reservations"], {})
        with self.assertRaises(BudgetExceeded):
            reserve_state(changed, 100, 8192, "b", 2)

    def test_unknown_failure_and_idempotent_settlement(self):
        reserved = reserve_state(approved(), 100, 8192, "a", 1)
        settled, charge = settle_state(reserved, "a", None, 2)
        self.assertEqual(charge["output_tokens"], 8192)
        repeated, same_charge = settle_state(settled, "a", (0, 0), 3)
        self.assertEqual(repeated, settled)
        self.assertEqual(same_charge, charge)
        self.assertEqual(settled["calls"], 1)

    def test_verified_usage_releases_unused_reservation(self):
        reserved = reserve_state(approved(), 1000, 8192, "a", 1)
        settled, charge = settle_state(reserved, "a", (80, 25), 2)
        self.assertEqual(settled["output_tokens"], 25)
        self.assertEqual(settled["reservations"], {})
        self.assertAlmostEqual(charge["cost_usd"], 0.0003075)

    def test_provider_overrun_disables_new_dispatch(self):
        reserved = reserve_state(approved(), 100, 8192, "a", 1)
        settled, charge = settle_state(reserved, "a", (101, 8193), 2)
        self.assertFalse(settled["enabled"])
        self.assertEqual(charge["output_tokens"], 8193)
        with self.assertRaises(BudgetExceeded):
            reserve_state(settled, 100, 8192, "b", 3)

    def test_explicit_config_controls_dispatch_and_no_default_limits_are_inferred(self):
        ledger = approved()
        ledger["approved_limits"]["calls"] = 1
        first = reserve_state(ledger, 100, 8192, "a", 1)
        first, _ = settle_state(first, "a", (1, 1), 2)
        with self.assertRaises(BudgetExceeded):
            reserve_state(first, 100, 8192, "b", 3)
        ledger = approved()
        ledger["approved_dispatch_stop_usd"] = 0.01
        with self.assertRaises(BudgetExceeded):
            reserve_state(ledger, 100, 8192, "a", 1)

    def test_nan_negative_and_boolean_counters_are_rejected(self):
        for invalid in (float("nan"), -1, True):
            ledger = approved()
            ledger["cost_usd"] = invalid
            with self.assertRaises(BudgetExceeded):
                reserve_state(ledger, 100, 8192, "a", 1)


@patch.dict("os.environ", {"GOOGLE_CLOUD_PROJECT": "test-project-123", "FIRESTORE_DATABASE": "test-named-db",
                           "EVIDENCEDESK_BUDGET_DOCUMENT": "internal_budgets/test-only"})
class AdapterTests(unittest.TestCase):
    @patch("google.cloud.firestore.transactional", lambda function: function)
    def test_adapter_uses_existing_document_and_transaction_update(self):
        client = FakeClient(approved())
        ledger = FirestoreBudgetLedger(client=client)
        self.assertEqual(client.transaction_count, 0)  # Constructor performs no cloud operation.
        token = ledger.reserve(100, 8192)
        charged = ledger.settle(token, (50, 30))
        self.assertEqual(client.transaction_count, 2)
        self.assertEqual(client.tx.updates, 2)
        self.assertEqual(client.reference.data["calls"], 1)
        self.assertEqual(charged["output_tokens"], 30)

    @patch("google.cloud.firestore.transactional", lambda function: function)
    def test_missing_document_never_bootstraps(self):
        client = FakeClient(None)
        ledger = FirestoreBudgetLedger(client=client)
        with self.assertRaises(BudgetExceeded):
            ledger.reserve(100, 8192)
        self.assertIsNone(client.reference.data)
        self.assertEqual(client.tx.updates, 0)

    def test_serialized_transaction_callbacks_prevent_competing_overreservation(self):
        client = FakeClient(approved())
        client.reference.data["approved_limits"]["output_tokens"] = 10_000
        lock = threading.Lock()

        def transactional(function):
            def execute(transaction):
                with lock:
                    return function(transaction)
            return execute

        ledger = FirestoreBudgetLedger(client=client)

        def attempt(_):
            try:
                return ledger.reserve(100, 8192)
            except BudgetExceeded:
                return None

        with patch("google.cloud.firestore.transactional", transactional), ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(8)))
        self.assertEqual(sum(value is not None for value in results), 1)
        self.assertEqual(len(client.reference.data["reservations"]), 1)


if __name__ == "__main__":
    unittest.main()
