"""Google Gen AI SDK with process-safe, fail-closed budget accounting."""
import contextlib
import fcntl
import json
import os
import re
import time
import uuid
from pathlib import Path

MODEL = "gemini-3.8-flash"
INPUT_RATE = 1.50 / 1_000_000
OUTPUT_RATE = 7.50 / 1_000_000
MAX_BILLABLE_OUTPUT = 65_536  # Reserve full model ceiling, including reasoning.
LIMITS = {"calls": 100, "input_tokens": 1_000_000, "output_tokens": 100_000, "cost_usd": 10.0}
DISPATCH_STOP_USD = 8.0


class AIError(RuntimeError):
    pass


class BudgetExceeded(AIError):
    pass


class BudgetLedger:
    def __init__(self, path=None):
        value = path or os.environ.get("EVIDENCEDESK_BUDGET_LEDGER")
        if not value:
            raise BudgetExceeded("AI budget ledger is not configured.")
        self.path = Path(value)

    @contextlib.contextmanager
    def locked(self):
        # Never create or reset a ledger. An operator must initialize it explicitly.
        if not self.path.is_file():
            raise BudgetExceeded("AI budget ledger has not been initialized.")
        with self.path.open("r+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                ledger = json.load(handle)
                for name in LIMITS:
                    if not isinstance(ledger.get(name), (int, float)) or ledger[name] < 0:
                        raise BudgetExceeded("AI budget ledger counters are invalid.")
                if not isinstance(ledger.get("reservations"), dict):
                    raise BudgetExceeded("AI budget ledger reservations are invalid.")
                yield ledger
                handle.seek(0)
                json.dump(ledger, handle, indent=2)
                handle.truncate()
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def reserve(self, input_bound, output_bound=MAX_BILLABLE_OUTPUT):
        reservation = {
            "calls": 1, "input_tokens": input_bound, "output_tokens": output_bound,
            "cost_usd": input_bound * INPUT_RATE + output_bound * OUTPUT_RATE,
            "created_at": time.time(),
        }
        with self.locked() as ledger:
            if ledger.get("enabled") is not True:
                raise BudgetExceeded("AI calls are disabled by the initialized ledger.")
            for name, limit in LIMITS.items():
                already = ledger[name] + sum(r[name] for r in ledger["reservations"].values())
                effective = min(limit, DISPATCH_STOP_USD) if name == "cost_usd" else limit
                if already + reservation[name] > effective:
                    raise BudgetExceeded(f"AI {name} limit would be exceeded; no request sent.")
            token = uuid.uuid4().hex
            ledger["reservations"][token] = reservation
        return token

    def settle(self, token, usage=None):
        """Uncertain failure keeps full reservation as spent; no optimistic refund."""
        with self.locked() as ledger:
            reserved = ledger["reservations"].pop(token)
            charged = {k: reserved[k] for k in LIMITS}
            if usage is not None:
                input_tokens, output_tokens = usage
                charged.update(input_tokens=input_tokens, output_tokens=output_tokens,
                               cost_usd=input_tokens * INPUT_RATE + output_tokens * OUTPUT_RATE)
                if input_tokens > reserved["input_tokens"] or output_tokens > reserved["output_tokens"]:
                    ledger["enabled"] = False
                    ledger["halt_reason"] = "Provider usage exceeded conservative reservation."
            for name in LIMITS:
                ledger[name] += charged[name]
            ledger["last_usage"] = charged
        return charged


class AIClient:
    def __init__(self):
        self.model = MODEL
        self.usage = {key: 0 for key in LIMITS}
        self.last_response_metadata = {}

    def generate(self, *, system, prompt, schema, max_output_tokens=8192):
        if os.environ.get("EVIDENCEDESK_ENABLE_AI") != "1":
            raise AIError("Live AI is disabled; explicit enablement is required.")
        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
        if not re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", project):
            raise AIError("A valid Google Cloud project ID is required.")
        if os.environ.get("GOOGLE_CLOUD_LOCATION", "global") != "global":
            raise AIError("This validated model configuration uses the global endpoint.")
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json", "responseSchema": schema,
                "maxOutputTokens": min(max_output_tokens, 8192),
                "thinkingConfig": {"thinkingLevel": "LOW"},
            },
        }
        # UTF-8 byte count bounds text tokenizer tokens; reserve framing/schema headroom.
        input_bound = len(json.dumps(body, ensure_ascii=False).encode("utf-8")) + 2048
        if input_bound > 80_000:
            raise AIError("Document batch is too large for the bounded analysis request.")
        from google import genai
        from google.genai import types
        sdk = genai.Client(
            enterprise=True, project=project, location="global",
            http_options=types.HttpOptions(
                api_version="v1", timeout=180_000,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        config = types.GenerateContentConfig(
            system_instruction=system, response_mime_type="application/json", response_schema=schema,
            max_output_tokens=min(max_output_tokens, 8192),
            thinking_config=types.ThinkingConfig(thinking_level="LOW"),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            automatic_continuation=False,
        )
        if os.environ.get('EVIDENCEDESK_BUDGET_BACKEND') == 'firestore':
            from .budget_cloud import FirestoreBudgetLedger
            ledger = FirestoreBudgetLedger()
        else:
            ledger = BudgetLedger()
        # The configured cap covers visible output plus thinking tokens.
        # https://ai.google.dev/gemini-api/docs/generate-content/thinking
        token = ledger.reserve(input_bound, output_bound=min(max_output_tokens, 8192))
        settled = False
        try:
            response = sdk.models.generate_content(model=MODEL, contents=prompt, config=config)
            payload = response.model_dump(mode="json", by_alias=True, exclude_none=True)
            metadata = payload.get("usageMetadata", {})
            self.last_response_metadata = {
                "requested_model": MODEL, "response_model_version": payload.get("modelVersion"),
                "usage": metadata, "response_id": payload.get("responseId"),
            }
            expected = ("promptTokenCount", "candidatesTokenCount")
            if all(isinstance(metadata.get(k), int) and metadata[k] >= 0 for k in expected):
                output = metadata["candidatesTokenCount"] + metadata.get("thoughtsTokenCount", 0)
                if isinstance(metadata.get("totalTokenCount"), int):
                    output = max(output, metadata["totalTokenCount"] - metadata["promptTokenCount"])
                charged = ledger.settle(token, (metadata["promptTokenCount"], output))
            else:
                charged = ledger.settle(token)
            settled = True
            for key in self.usage:
                self.usage[key] += charged[key]
            candidates = payload.get("candidates", [])
            if not candidates or candidates[0].get("finishReason") != "STOP":
                raise AIError("Model did not finish a complete structured response.")
            text = "".join(part.get("text", "") for part in candidates[0].get("content", {}).get("parts", []) if not part.get("thought"))
            try:
                return json.loads(text)
            except (ValueError, TypeError) as exc:
                raise AIError("Model returned invalid JSON.") from exc
        except Exception as exc:
            if not settled:
                charged = ledger.settle(token)
                for key in self.usage:
                    self.usage[key] += charged[key]
            if isinstance(exc, AIError):
                raise
            message = str(getattr(exc, "message", str(exc)))
            message = re.sub(r"(?i)(bearer\s+|access_token[=:]\s*|api_key[=:]\s*)[^\s,\"']+", r"\1[redacted]", message)[:600]
            code = getattr(exc, "code", None)
            self.last_response_metadata["error"] = {"class": type(exc).__name__, "status_code": code, "message": message}
            raise AIError(f"Google SDK {type(exc).__name__} ({code if code is not None else 'no HTTP status'}): {message}") from exc
        finally:
            sdk.close()
