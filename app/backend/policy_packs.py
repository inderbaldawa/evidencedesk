"""Versioned review questions, not legal frameworks or implied requirements.

Pack definitions guide extraction. Only uploaded applicable buyer policies can
supply requirements. Released definitions are immutable: changes need a version.
"""
from copy import deepcopy

DEFAULT_POLICY_PACK_ID = "data-handling"


def _control(id, name, description, expected_evidence):
    return {"id": id, "name": name, "description": description, "expected_evidence": expected_evidence}


_PACKS = {
    "data-handling": {
        "id": "data-handling", "name": "Data handling", "version": "1.0",
        "description": "Compare buyer requirements with vendor claims and records for customer-data handling.",
        "controls": [
            _control("data_location", "Customer data location", "Location of primary customer-data stores.", "Current primary-store inventory and location records."),
            _control("backup_location", "Backup location", "Location of backups and replicas containing customer data.", "Current backup inventory identifying data scope and region."),
            _control("deletion", "Deletion evidence", "Evidence of completed deletion against the buyer requirement.", "Scoped deletion completion records; retention plans alone are insufficient."),
            _control("access_review", "Access reviews", "Review of access to the in-scope customer-data service.", "Dated access review with reviewer, scope and completion record."),
            _control("incident_response", "Incident response", "Incident notification commitments and required response contacts.", "Executed commitments and maintained contact details required by the buyer."),
            _control("evidence_currency", "Evidence currency", "Dates, effective terms and supersession of evidence.", "Issue/effective dates, scope and current document versions."),
        ],
    },
    "security-assurance": {
        "id": "security-assurance", "name": "Security assurance", "version": "1.0",
        "description": "Review a vendor's security assurances against the buyer's internal requirements.",
        "controls": [
            _control("privileged_access", "Privileged access", "Authorization and review of privileged service access.", "Dated privileged-account inventory and approved access review."),
            _control("mfa_enforcement", "MFA enforcement", "Enforcement of multifactor authentication for required accounts.", "Scoped authentication configuration and exception records."),
            _control("vulnerability_remediation", "Vulnerability remediation", "Remediation against the buyer's severity and timing requirements.", "Dated findings and remediation/verification tickets."),
            _control("security_testing", "Security testing", "Required security testing and follow-up coverage.", "Dated scoped test report and remediation evidence."),
            _control("incident_response", "Incident response", "Required incident notification commitments and contacts.", "Executed commitments and maintained response contact record."),
            _control("evidence_currency", "Evidence currency", "Dates, effective terms and supersession of security records.", "Current dated records identifying service and environment."),
        ],
    },
    "ai-vendor": {
        "id": "ai-vendor", "name": "AI vendor review", "version": "1.0",
        "description": "Compare AI-service assurances with records under a buyer's internal AI-use policy.",
        "controls": [
            _control("training_use", "Training use", "Use of customer inputs and outputs for model training.", "Executed training-use terms and scoped configuration records."),
            _control("data_retention", "Data retention", "Retention of AI-service inputs, outputs and diagnostic logs.", "Scoped retention configuration and retention/deletion records."),
            _control("human_oversight", "Human oversight", "Required human review of AI-assisted decisions or outputs.", "Workflow settings and completed human-review records."),
            _control("model_change_notice", "Model change notice", "Required notification and approval of model changes.", "Versioned model register, dated notices and approval records."),
            _control("subprocessor_disclosure", "Subprocessor disclosure", "Disclosure of downstream providers handling in-scope data.", "Current scoped subprocessor register and required notices."),
            _control("evidence_currency", "Evidence currency", "Dates, effective terms and supersession of AI-service records.", "Current dated records identifying service and environment."),
        ],
    },
}


def get_policy_pack(pack_id=DEFAULT_POLICY_PACK_ID):
    """Return a copy; reject unknown packs rather than silently substituting one."""
    if not isinstance(pack_id, str) or pack_id not in _PACKS:
        raise ValueError("Unknown policy pack.")
    return deepcopy(_PACKS[pack_id])


def list_policy_packs():
    return [get_policy_pack(pack_id) for pack_id in _PACKS]


def review_policy_pack(review):
    pack = get_policy_pack(review.get("policy_pack_id", DEFAULT_POLICY_PACK_ID))
    if review.get("policy_pack_version", pack["version"]) != pack["version"]:
        raise ValueError("Unsupported policy pack version.")
    return pack


ALL_CONTROL_IDS = frozenset(c["id"] for p in _PACKS.values() for c in p["controls"])
