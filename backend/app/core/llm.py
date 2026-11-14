"""The one way to call the language model.

With USE_MOCK_LLM unset or true, answers are replayed from mocks/llm/<key>.json, so tests run the real
prompts and parsing without a network call. With USE_MOCK_LLM=false the real model is called, and
LLM_RECORD=true saves each answer as a replay file. A missing replay file is an error, never a guess.

A call may carry one JPEG image and a model id. The image travels as a base64 data URL, the documented way for
this API; the model id overrides LLM_MODEL for a vision model. Both are part of the replay key, so a recording
made for one photo or one model is never replayed for another.

A live call gets two attempts of LLM_TIMEOUT_S. A hang, a dropped connection, a 429 or a 5xx is retried
once; any other HTTP error, and an answer that is not JSON, fails at once. An answer that reaches MAX_TOKENS
raises LLMCutOff and is not retried here either: the caller decides whether to ask differently.
"""
import base64
import hashlib
import json
import logging
import os
import urllib.error
import urllib.request
from enum import StrEnum

from . import config

# Short enough that two attempts cannot freeze one ingest request for a minute.
LLM_TIMEOUT_S = 15
MAX_ATTEMPTS = 2
# 429 and every 5xx ask for another try; any other 4xx is our request's fault and retrying cannot help.
RETRY_STATUS = {429} | set(range(500, 600))
# A strict schema does not stop a list from repeating its entries: one extraction answer wrote the same units
# back and forth and never finished, so both attempts timed out. Without a cap such an answer never returns.
# The largest recorded answer is about 1,550 characters (some 600 tokens), and a translation is cut to fit
# 3,900 characters together with its original. 2000 tokens leave room for both and still end a runaway answer
# within a few seconds, well inside LLM_TIMEOUT_S.
MAX_TOKENS = 2000
REPLAY_DIR = config.ROOT / "mocks" / "llm"

log = logging.getLogger(__name__)


class FailureCategory(StrEnum):
    """Fixed words for a failed model call. Only these reach a log or the record."""

    TRANSPORT_TIMEOUT = "transport_timeout"
    HTTP_STATUS = "http_status"
    INVALID_JSON = "invalid_json"
    CUT_OFF = "cut_off"
    MISSING_CONFIG = "missing_config"
    # Internal, never a live provider cause: a replay file is missing, or an error was raised by hand.
    MISSING_RECORDING = "missing_recording"
    UNKNOWN = "unknown"


class LLMError(RuntimeError):
    def __init__(self, message: str, category: FailureCategory | str = FailureCategory.UNKNOWN):
        super().__init__(message)
        self.category = FailureCategory(category)


class LLMCutOff(LLMError):
    """The answer stopped at MAX_TOKENS. The same request would run into the cap again, so it is not retried."""

    def __init__(self, message: str, category: FailureCategory | str = FailureCategory.CUT_OFF):
        super().__init__(message, category)


class _Retryable(LLMError):
    """A transport failure worth one more attempt; it never leaves this module."""


def _key(system: str, user: str, schema: dict, image: bytes | None = None, model: str | None = None) -> str:
    """The replay key. An image and a model override are part of it; a text-only call keys exactly as before."""
    parts: list = [system, user, schema]
    if image is not None:
        parts.append({"image_sha256": hashlib.sha256(image).hexdigest()})
    if model:
        parts.append({"model": model})
    raw = json.dumps(parts, sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()[:20]


def _request(system: str, user: str, schema: dict, image: bytes | None = None,
             model: str | None = None, *, max_tokens: int | None = None) -> urllib.request.Request:
    base = (os.environ.get("LLM_BASE_URL") or "https://api.mistral.ai/v1").rstrip("/")
    key = os.environ.get("MISTRAL_API_KEY")
    chosen = model or os.environ.get("LLM_MODEL")
    if not key or not chosen:
        raise LLMError(
            "MISTRAL_API_KEY and LLM_MODEL must be set for a real model call",
            category=FailureCategory.MISSING_CONFIG,
        )
    content: object = user
    if image is not None:
        data_url = f"data:image/jpeg;base64,{base64.b64encode(image).decode()}"
        content = [{"type": "text", "text": user}, {"type": "image_url", "image_url": {"url": data_url}}]
    body = {
        "model": chosen,
        "temperature": 0,
        "max_tokens": MAX_TOKENS if max_tokens is None else max_tokens,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
        # json_object mode garbled key names in a probe on 2026-11-13; strict json_schema did not.
        "response_format": {"type": "json_schema", "json_schema": {"name": "answer", "schema": schema, "strict": True}},
    }
    return urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )


def _attempt(request: urllib.request.Request, *, timeout_s: float | None = None) -> dict:
    try:
        with urllib.request.urlopen(request, timeout=LLM_TIMEOUT_S if timeout_s is None else timeout_s) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        message = f"model call failed with HTTP {error.code}"
        if error.code in RETRY_STATUS:
            raise _Retryable(message, category=FailureCategory.HTTP_STATUS) from None
        raise LLMError(message, category=FailureCategory.HTTP_STATUS) from None
    except (urllib.error.URLError, OSError):
        # The reason can quote the URL or the provider's text, so only the fixed category leaves here.
        raise _Retryable("model unreachable", category=FailureCategory.TRANSPORT_TIMEOUT) from None
    try:
        choice = payload["choices"][0]
        finish = choice.get("finish_reason")
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError, AttributeError):
        raise LLMError(
            "model answer was not the requested JSON", category=FailureCategory.INVALID_JSON
        ) from None
    if finish == "length":
        # Checked before parsing: a cut-off answer is broken JSON too, but its cause is the cap, not the model.
        raise LLMCutOff("model answer cut off at the requested token limit")
    try:
        return json.loads(content)
    except (TypeError, json.JSONDecodeError):
        raise LLMError(
            "model answer was not the requested JSON", category=FailureCategory.INVALID_JSON
        ) from None


def _call(system: str, user: str, schema: dict, image: bytes | None = None,
          model: str | None = None, *, max_tokens: int | None = None, timeout_s: float | None = None) -> dict:
    try:
        request = _request(system, user, schema, image, model) if max_tokens is None else _request(system, user, schema, image, model, max_tokens=max_tokens)
    except LLMError as error:
        log.warning("model call failed: %s", error.category)
        raise
    message = "model call failed"
    category = FailureCategory.UNKNOWN
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return _attempt(request) if timeout_s is None else _attempt(request, timeout_s=timeout_s)
        except _Retryable as error:
            message, category = str(error), error.category
            if attempt < MAX_ATTEMPTS:
                log.warning("model call failed (attempt %d of %d): %s", attempt, MAX_ATTEMPTS, category)
        except LLMError as error:
            log.warning("model call failed: %s", error.category)
            raise
    log.warning("model call failed after %d attempts: %s", MAX_ATTEMPTS, category)
    raise LLMError(message, category=category)


def complete_json(*, system: str, user: str, schema: dict, image: bytes | None = None,
                  model: str | None = None, record: bool = True,
                  max_tokens: int | None = None, timeout_s: float | None = None) -> dict:
    """Return the model's answer as a dict that follows `schema` (a JSON Schema with additionalProperties false).

    `image` is one JPEG, sent as a base64 data URL, and `model` overrides LLM_MODEL for a vision model. Both
    are part of the replay key, so a recorded answer is reused only for the same photo and the same model.
    record=False keeps the answer out of the replay files even with LLM_RECORD set, for a request that replay
    never asks, such as a second ask after a cut-off answer.
    """
    if max_tokens is not None and (type(max_tokens) is not int or not 1 <= max_tokens <= 16384):
        raise ValueError("Model output budget must be between 1 and 16384 tokens")
    if timeout_s is not None and (not isinstance(timeout_s, (int, float)) or not 0 < timeout_s <= 120):
        raise ValueError("Model timeout must be between 0 and 120 seconds")
    key = _key(system, user, schema, image, model)
    path = REPLAY_DIR / f"{key}.json"
    if config.external_is_mock("llm"):
        if not path.is_file():
            raise LLMError(
                f"no recorded model answer {path.name}. Record it once with USE_MOCK_LLM=false LLM_RECORD=true",
                category=FailureCategory.MISSING_RECORDING,
            )
        return json.loads(path.read_text(encoding="utf-8"))["answer"]
    answer = (_call(system, user, schema, image, model) if max_tokens is None and timeout_s is None else
              _call(system, user, schema, image, model, max_tokens=max_tokens, timeout_s=timeout_s))
    if record and config.flag("LLM_RECORD"):
        REPLAY_DIR.mkdir(parents=True, exist_ok=True)
        recorded = {"system": system, "user": user, "answer": answer}
        if model:
            recorded["model"] = model
        path.write_text(json.dumps(recorded, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return answer
