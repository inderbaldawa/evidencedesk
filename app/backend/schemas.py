"""Small structured-output contracts; source text is always untrusted data."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

CONTROL_NAMES = {
    "data_location": "Customer data location",
    "backup_location": "Backup location",
    "deletion": "Deletion evidence",
    "access_review": "Access reviews",
    "incident_response": "Incident response",
    "evidence_currency": "Evidence currency",
}
Control = Literal["data_location", "backup_location", "deletion", "access_review", "incident_response", "evidence_currency"]
Status = Literal["evidence_found", "partial_evidence", "conflicting_evidence", "not_evidenced", "needs_human_review"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Context(StrictModel):
    vendor: str = ""
    service: str = ""
    environment: str = ""
    period: str = ""
    version: str = ""
    document_type: Literal["policy", "signed_commitment", "questionnaire", "inventory", "operational_record", "other"]
    currency: Literal["current", "superseded", "unknown"]
    scope_status: Literal["applicable", "out_of_scope", "unclear"]
    scope_reason: str


class Observation(StrictModel):
    control_id: Control
    role: Literal["requirement", "claim", "record", "support"]
    page: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=2200)
    statement: str = Field(max_length=1600)


class ExtractedDocument(StrictModel):
    document_id: str
    context: Context
    observations: list[Observation] = Field(max_length=24)
    suspicious_instructions: bool


class ExtractionBatch(StrictModel):
    documents: list[ExtractedDocument] = Field(max_length=4)


class Reconciliation(StrictModel):
    control_id: Control
    status: Status
    requirement: str
    explanation: str
    next_action: str
    follow_up_question: str
    evidence_ids: list[str] = Field(max_length=12)


def response_schema(model):
    """Resolve Pydantic refs to the Google responseSchema subset."""
    raw = model.model_json_schema()
    definitions = raw.get("$defs", {})

    def convert(value):
        if isinstance(value, list):
            return [convert(item) for item in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            return convert(definitions[value["$ref"].split("/")[-1]])
        result = {}
        for key, item in value.items():
            # Keep provider grammar small. Full enum/size/range validation still
            # happens with Pydantic after generation; it is not relaxed here.
            if key in {"title", "$defs", "additionalProperties", "default", "maxLength", "minLength",
                       "enum", "const", "minimum", "maximum", "minItems", "maxItems",
                       "minProperties", "maxProperties", "pattern", "format"}:
                continue
            if key == "type":
                result[key] = item.upper()
            else:
                result[key] = convert(item)
        return result

    schema = convert(raw)
    if model is Reconciliation:
        # This small schema has one bounded reference list. Avoid the combinatorial
        # enum/range constraints that made the extraction schema fail at provider.
        schema["properties"]["evidence_ids"]["maxItems"] = 12
    return schema
