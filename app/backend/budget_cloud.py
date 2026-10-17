"""Explicitly provisioned, transaction-backed shared Google AI budget.

No document is ever created/reset by this module. A deployment operator must
initialize an approved ledger in the selected named Firestore database first.
Neither construction nor the pure state helpers dispatch model requests.
"""
import copy
import math
import os
import re
import time
import uuid

from .ai_client import (
    BudgetExceeded, DISPATCH_STOP_USD, INPUT_RATE, LIMITS, MAX_BILLABLE_OUTPUT,
    MODEL, OUTPUT_RATE,
)


def _number(value, *, integral=False):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and value >= 0 and (not integral or isinstance(value, int)))


def _validate(ledger):
    if not isinstance(ledger, dict):
        raise BudgetExceeded("Cloud AI budget ledger is invalid.")
    if not isinstance(ledger.get("approval_reference"), str) or not ledger["approval_reference"].strip():
        raise BudgetExceeded("Cloud AI budget requires an explicit approval reference.")
    if ledger.get("model") != MODEL:
        raise BudgetExceeded("Cloud AI budget does not approve this model.")
    if (ledger.get("input_rate_usd_per_million") != INPUT_RATE * 1_000_000
            or ledger.get("output_rate_usd_per_million") != OUTPUT_RATE * 1_000_000):
        raise BudgetExceeded("Cloud AI budget pricing does not match the reviewed implementation.")
    limits = ledger.get("approved_limits")
    if not isinstance(limits, dict) or set(limits) != set(LIMITS):
        raise BudgetExceeded("All cloud AI budget limits must be explicitly approved.")
    for key in LIMITS:
        integral = key != "cost_usd"
        if not _number(limits[key], integral=integral) or limits[key] <= 0:
            raise BudgetExceeded("Cloud AI approved limits are invalid.")
        if not _number(ledger.get(key), integral=integral):
            raise BudgetExceeded("Cloud AI budget usage counters are invalid.")
    dispatch = ledger.get("approved_dispatch_stop_usd")
    if not _number(dispatch) or not 0 < dispatch <= limits["cost_usd"]:
        raise BudgetExceeded("Cloud AI dispatch stop must be explicitly approved within its cost limit.")
    if not isinstance(ledger.get("reservations"), dict) or not isinstance(ledger.get("settlements"), dict):
        raise BudgetExceeded("Cloud AI budget reservation/settlement maps are invalid.")
    for reservation in ledger["reservations"].values():
        if not isinstance(reservation, dict) or reservation.get("calls") != 1:
            raise BudgetExceeded("Cloud AI budget contains an invalid reservation.")
        for key in LIMITS:
            if not _number(reservation.get(key), integral=key != "cost_usd"):
                raise BudgetExceeded("Cloud AI budget contains an invalid reservation counter.")
    return limits, dispatch


def reserve_state(ledger, input_bound, output_bound, token, timestamp):
    """Pure transition; Firestore retries rerun against a fresh document snapshot."""
    limits, dispatch = _validate(ledger)
    if ledger.get("enabled") is not True:
        raise BudgetExceeded("Cloud AI calls are disabled in the approved ledger.")
    if not _number(input_bound, integral=True) or input_bound <= 0:
        raise BudgetExceeded("Input reservation must be a positive token count.")
    if not _number(output_bound, integral=True) or not 0 < output_bound <= MAX_BILLABLE_OUTPUT:
        raise BudgetExceeded("Output reservation must be a positive configured cap within the model ceiling.")
    if token in ledger["reservations"] or token in ledger["settlements"]:
        raise BudgetExceeded("Reservation identifier has already been used.")
    reserved = {"calls": 1, "input_tokens": input_bound, "output_tokens": output_bound,
                "cost_usd": input_bound * INPUT_RATE + output_bound * OUTPUT_RATE,
                "created_at": timestamp}
    for key, maximum in limits.items():
        used = ledger[key] + sum(item[key] for item in ledger["reservations"].values())
        ceiling = min(maximum, dispatch) if key == "cost_usd" else maximum
        if used + reserved[key] > ceiling:
            raise BudgetExceeded(f"Cloud AI {key} limit would be exceeded; no model request sent.")
    updated = copy.deepcopy(ledger)
    updated["reservations"][token] = reserved
    updated["updated_at"] = timestamp
    return updated


def settle_state(ledger, token, usage, timestamp):
    """Unknown outcome charges full reservation; repeated settlement is idempotent."""
    _validate(ledger)
    if token in ledger["settlements"]:
        return copy.deepcopy(ledger), copy.deepcopy(ledger["settlements"][token]["charged"])
    if token not in ledger["reservations"]:
        raise BudgetExceeded("Cloud AI reservation is unknown; accounting was not modified.")
    updated = copy.deepcopy(ledger)
    reserved = updated["reservations"].pop(token)
    charged = {key: reserved[key] for key in LIMITS}
    valid_usage = (isinstance(usage, (tuple, list)) and len(usage) == 2
                   and all(_number(value, integral=True) for value in usage))
    if valid_usage:
        input_tokens, output_tokens = usage
        charged.update(input_tokens=input_tokens, output_tokens=output_tokens,
                       cost_usd=input_tokens * INPUT_RATE + output_tokens * OUTPUT_RATE)
        if input_tokens > reserved["input_tokens"] or output_tokens > reserved["output_tokens"]:
            updated["enabled"] = False
            updated["halt_reason"] = "Provider usage exceeded conservative reservation."
    for key in LIMITS:
        updated[key] += charged[key]
    updated["last_usage"] = charged
    updated["settlements"][token] = {"charged": charged, "settled_at": timestamp,
                                      "usage_verified": valid_usage}
    # Keep bounded idempotency receipts. An older repeated token fails closed.
    receipts = updated["settlements"]
    if len(receipts) > 512:
        for old_token in sorted(receipts, key=lambda value: receipts[value]["settled_at"])[:-512]:
            del receipts[old_token]
    updated["updated_at"] = timestamp
    return updated, charged


class FirestoreBudgetLedger:
    """Drop-in reserve/settle ledger interface for a Cloud Run worker.

    Required environment:
      GOOGLE_CLOUD_PROJECT, FIRESTORE_DATABASE, EVIDENCEDESK_BUDGET_DOCUMENT
    Example document path: internal_budgets/ai-builder-cp2 (never inferred).
    Constructor does not read or write Firestore. `client` permits offline mocks.
    """
    def __init__(self, *, client=None, document_path=None):
        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
        database = os.environ.get("FIRESTORE_DATABASE", "")
        path = document_path or os.environ.get("EVIDENCEDESK_BUDGET_DOCUMENT", "")
        if not re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", project) or not database:
            raise BudgetExceeded("Explicit cloud project and Firestore database are required.")
        pieces = path.split("/")
        if (not path or len(pieces) % 2 or any(not item or item in {".", ".."} for item in pieces)
                or any(len(item.encode()) > 1500 for item in pieces)):
            raise BudgetExceeded("An explicit valid Firestore budget document path is required.")
        if client is None:
            from google.cloud import firestore
            client = firestore.Client(project=project, database=database)
        self.client = client
        self.reference = client.document(path)

    def _transaction(self, operation):
        from google.cloud import firestore

        @firestore.transactional
        def apply(transaction):
            snapshot = self.reference.get(transaction=transaction)
            if not snapshot.exists:
                raise BudgetExceeded("Cloud AI budget ledger has not been initialized; no request sent.")
            updated, result = operation(snapshot.to_dict())
            # update, never set: the existing approved document is mandatory.
            transaction.update(self.reference, updated)
            return result

        return apply(self.client.transaction())

    def reserve(self, input_bound, output_bound=MAX_BILLABLE_OUTPUT):
        token = uuid.uuid4().hex
        timestamp = time.time()

        def operation(ledger):
            return reserve_state(ledger, input_bound, output_bound, token, timestamp), token

        return self._transaction(operation)

    def settle(self, token, usage=None):
        return self._transaction(lambda ledger: settle_state(ledger, token, usage, time.time()))


def development_ledger_example(approval_reference):
    """Return a reviewable template, never provision it or presume CP2 approval.

    Deployment initialization must supply its actual explicit approved values;
    this example retains the earlier development scope and defaults disabled.
    """
    return {
        "enabled": False, "approval_reference": approval_reference, "model": MODEL,
        "approved_limits": dict(LIMITS), "approved_dispatch_stop_usd": DISPATCH_STOP_USD,
        "input_rate_usd_per_million": INPUT_RATE * 1_000_000,
        "output_rate_usd_per_million": OUTPUT_RATE * 1_000_000,
        "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
        "reservations": {}, "settlements": {},
    }
