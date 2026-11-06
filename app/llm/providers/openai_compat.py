"""Providers that speak the OpenAI chat-completions format, over the Python standard library (ADR-021).

Today that is Typhoon (``typhoon``), SCB 10X's Thai-first model family. Its hosted API is free (a research
showcase in beta, rate-limited, no card) at ``https://api.opentyphoon.ai/v1``. The key is read from
``TYPHOON_API_KEY`` at call time and never returned or logged. Another service in the same format needs one
entry in ``config.py`` (provider name, default model, key variable, endpoint) and in the gateway's table.

Request shape (kept as close as possible to the Claude path):
* ``POST {base_url}/chat/completions`` with the model id;
* the prompt's system text as the system message and the masked case text (a JSON string) as the user message;
* structured JSON output through ``response_format`` (``json_schema``, strict), built from the prompt's own
  answer schema, so the answer is limited to the same fixed choices before our validators check it again;
* ``max_tokens`` from the frozen configuration; no sampling parameters, tools or effort.

How failures are classified (Core decides retries from the class), the same as for Claude:
* 408, 429, 5xx, timeouts, network errors -> LLMTransientError
* 401, 403 (key missing or rejected), 404 (unknown model) -> LLMConfigError
* other 4xx and any redirect -> LLMRequestError (redirects are refused so the key never travels)
* a reply that is not a chat completion -> InvalidModelOutput
* an HTTP 400 whose error code says a content filter blocked this case's text -> a refusal (the case reaches
  review with ``model_declined``), because it says something about one case, not about the setup.

How the reply maps onto the gateway's stop reasons: ``stop`` -> ``end_turn``; ``length`` -> ``max_tokens``
(cut off); ``content_filter`` or a ``refusal`` message -> ``refusal``.
"""

import http.client
import json
import os
import re
import urllib.error
import urllib.request

from neuron_flow import __version__

from ..config import DEFAULT_BASE_URLS, KEY_ENVS
from ..errors import InvalidModelOutput, LLMConfigError, LLMRequestError, LLMTransientError
from ._http import MAX_RESPONSE_BYTES, OPENER

CONTENT_FILTER_CODES = {"content_filter", "ResponsibleAIPolicyViolation"}
_ERROR_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,59}$")
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}$")
_SCHEMA_NAME = re.compile(r"[^A-Za-z0-9_-]")
_STOP_REASONS = {"stop": "end_turn", "length": "max_tokens", "content_filter": "refusal"}


def endpoint(config):
    return (config.base_url or DEFAULT_BASE_URLS[config.provider]).rstrip("/") + "/chat/completions"


def request_headers(config, key):
    return {"authorization": f"Bearer {key}", "content-type": "application/json",
            "accept": "application/json", "user-agent": f"neuron-flow/{__version__}"}


def build_request_body(config, prompt, case_text):
    name = _SCHEMA_NAME.sub("_", prompt.id)[:64] or "answer"
    return {"model": config.model, "max_tokens": config.max_tokens,
            "messages": [{"role": "system", "content": prompt.system},
                         {"role": "user", "content": prompt.user_message(case_text)}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": name, "strict": True, "schema": prompt.output_schema}}}


def complete(config, prompt, case_text, *, attempt=1, scenario=None):
    if scenario is not None:
        raise LLMConfigError("mock_scenario is only valid with the mock provider")
    key_env = KEY_ENVS[config.provider]
    key = os.environ.get(key_env, "").strip()
    if not key:
        raise LLMConfigError(f"{key_env} is not set")
    body = json.dumps(build_request_body(config, prompt, case_text), ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(endpoint(config), data=body, method="POST",
                                     headers=request_headers(config, key))
    try:
        with OPENER.open(request, timeout=config.request_timeout_s) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return for_status(exc, config)
    except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
        raise LLMTransientError(f"Could not reach the provider ({type(exc).__name__})") from None
    return parse_completion(raw, config)


def _error_codes(exc):
    """The error's code words (``error.code``, ``error.type``, ``error.innererror.code``); never its message."""
    codes = []
    try:
        error = json.loads(exc.read(65536).decode("utf-8-sig")).get("error")
        if isinstance(error, dict):
            inner = error.get("innererror") if isinstance(error.get("innererror"), dict) else {}
            codes = [value for value in (error.get("code"), error.get("type"), inner.get("code"))
                     if isinstance(value, str) and _ERROR_CODE.fullmatch(value)]
    except Exception:
        pass
    finally:
        exc.close()
    return list(dict.fromkeys(codes))


def for_status(exc, config):
    status = exc.code
    codes = _error_codes(exc)
    detail = " ".join([f"HTTP {status}", *codes[:2]])
    if status == 400 and CONTENT_FILTER_CODES.intersection(codes):
        return _declined(config)  # a content filter blocked this case's text: one case, not the setup
    if status in (408, 429) or status >= 500:
        raise LLMTransientError(f"Provider temporarily unavailable ({detail})") from None
    if status in (401, 403):
        raise LLMConfigError(f"Provider rejected the API key or its permissions ({detail}); "
                             f"check {KEY_ENVS[config.provider]}") from None
    if status == 404:
        raise LLMConfigError(f"Unknown model or API endpoint ({detail})") from None
    raise LLMRequestError(f"Provider rejected the request ({detail})") from None


def _declined(config):
    return {"text": "", "stop_reason": "refusal", "served_model": config.model,
            "usage": {"input_tokens": 0, "output_tokens": 0, "estimated": False}}


def _count(value):
    return value if type(value) is int and value >= 0 else 0


def parse_completion(raw, config):
    if len(raw) > MAX_RESPONSE_BYTES:
        raise InvalidModelOutput("Provider response is too large")
    try:
        data = json.loads(raw.decode("utf-8-sig"))  # tolerate a leading byte-order mark
    except (UnicodeDecodeError, ValueError):
        raise InvalidModelOutput(f"Provider response is not JSON ({len(raw)} bytes)") from None
    choices = data.get("choices") if isinstance(data, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict) \
            or not isinstance(choices[0].get("message"), dict):
        raise InvalidModelOutput("Provider response is not a chat completion")
    choice, message = choices[0], choices[0]["message"]
    content = message.get("content")
    if isinstance(content, list):  # some services return text parts
        content = "".join(part["text"] for part in content
                          if isinstance(part, dict) and isinstance(part.get("text"), str))
    finish = choice.get("finish_reason")
    if isinstance(message.get("refusal"), str) and message["refusal"].strip():
        stop_reason = "refusal"
    elif isinstance(finish, str):
        stop_reason = _STOP_REASONS.get(finish, finish)
    else:
        stop_reason = "end_turn"
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    served = data.get("model")
    return {"text": content if isinstance(content, str) else "", "stop_reason": stop_reason,
            "served_model": served if isinstance(served, str) and _MODEL.fullmatch(served) else config.model,
            "usage": {"input_tokens": _count(usage.get("prompt_tokens")),
                      "output_tokens": _count(usage.get("completion_tokens")), "estimated": False}}
