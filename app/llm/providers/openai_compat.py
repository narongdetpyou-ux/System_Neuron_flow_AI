"""Providers that speak the OpenAI chat-completions format, over the Python standard library (ADR-021).

Today that is:
* Typhoon (``typhoon``), SCB 10X's Thai-first model family. Its hosted API is free (a research showcase in
  beta, rate-limited, no card) at ``https://api.opentyphoon.ai/v1``. The key is read from
  ``TYPHOON_API_KEY`` at call time and never returned or logged.
* A server we run ourselves (``local``, ADR-026), by default llama.cpp's ``llama-server`` on this machine at
  ``http://127.0.0.1:8080/v1``, serving an open-weight model file. It needs no key on this machine; when
  ``NEURON_FLOW_LOCAL_API_KEY`` is set, it is sent like any other key, and when it is not, the request has no
  Authorization header.

Another service in the same format needs one entry in ``config.py`` (provider name, default model, key
variable, endpoint) and in the gateway's table.

Request shape (kept as close as possible to the Claude path):
* ``POST {base_url}/chat/completions`` with the model id;
* the prompt's system text, then an answer-format instruction (below), as the system message, and the masked
  case text (a JSON string) as the user message;
* structured JSON output through ``response_format`` (``json_schema``, strict), built from the prompt's own
  answer schema, for services that enforce it;
* ``max_tokens`` from the frozen configuration; no sampling parameters, tools or effort.

The answer format in words (ADR-022). Typhoon's API ignores ``response_format``: on its first live run
(2026-11-06) it answered ``category: upload`` / ``confidence: high`` / ``rationale: …`` as plain lines, so not
one of 5 cases had a usable answer. The client therefore also tells the model, after the prompt, to reply
with one JSON object, and lists the keys and their allowed values from the answer schema
(:func:`format_instruction`). That text is versioned as ``config.ANSWER_FORMATS`` and is part of the agent
version. When a reply wraps the object in a Markdown code fence or puts a sentence around it, only the
outermost ``{…}`` is passed on (:func:`answer_text`); the gateway still parses it strictly and checks every
field against the schema, so nothing looser than before is accepted. A local llama.cpp server does enforce
``response_format`` (it turns the schema into a grammar for the sampler) and gets the same words as well,
because small models follow the format better with them (ADR-026).

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

from ..config import ANSWER_FORMATS, DEFAULT_BASE_URLS, KEY_ENVS, OPTIONAL_KEY_PROVIDERS
from ..errors import InvalidModelOutput, LLMConfigError, LLMRequestError, LLMTransientError
from ._http import MAX_RESPONSE_BYTES, OPENER

CONTENT_FILTER_CODES = {"content_filter", "ResponsibleAIPolicyViolation"}
_ERROR_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,59}$")
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}$")
_SCHEMA_NAME = re.compile(r"[^A-Za-z0-9_-]")
_STOP_REASONS = {"stop": "end_turn", "length": "max_tokens", "content_filter": "refusal"}
_FENCE = re.compile(r"\A```[A-Za-z0-9_-]*[ \t]*\r?\n(.*?)\r?\n?[ \t]*```\Z", re.DOTALL)
FORMAT_VERSION = "json-instruction-v1"  # the text of format_instruction below; config.ANSWER_FORMATS names it


def endpoint(config):
    return (config.base_url or DEFAULT_BASE_URLS[config.provider]).rstrip("/") + "/chat/completions"


def request_headers(config, key):
    """The request's headers. Without a key (allowed only for ``config.OPTIONAL_KEY_PROVIDERS``) there is no
    Authorization header, rather than an empty one."""
    headers = {"content-type": "application/json", "accept": "application/json",
               "user-agent": f"neuron-flow/{__version__}"}
    if key:
        headers["authorization"] = f"Bearer {key}"
    return headers


def format_instruction(schema):
    """The answer format in words, built from the (possibly specialized) answer schema. Version
    ``FORMAT_VERSION``: change it, and ``config.ANSWER_FORMATS``, whenever this text changes."""
    lines = ["Answer format: reply with one JSON object and nothing else. No Markdown, no code fence, and no text "
             "before or after the object.",
             "The object has exactly these keys, in this order, and every value is a JSON string:"]
    for name, spec in schema["properties"].items():
        if "enum" in spec:
            rule = "exactly one of " + ", ".join(json.dumps(value, ensure_ascii=False) for value in spec["enum"])
        else:
            rule = "free text"
        description = (spec.get("description") or "").strip()
        lines.append(f"- {json.dumps(name)}: {rule}." + (f" {description}" if description else ""))
    lines.append("Use no other keys.")
    return "\n".join(lines)


def system_text(config, prompt):
    """The system message: the prompt file's text, then the answer-format instruction for providers that
    ignore ``response_format`` (``config.ANSWER_FORMATS``)."""
    if ANSWER_FORMATS.get(config.provider) != FORMAT_VERSION:
        raise LLMConfigError(f"No answer-format instruction for provider {config.provider}")
    return f"{prompt.system}\n\n{format_instruction(prompt.output_schema)}"


def build_request_body(config, prompt, case_text):
    name = _SCHEMA_NAME.sub("_", prompt.id)[:64] or "answer"
    return {"model": config.model, "max_tokens": config.max_tokens,
            "messages": [{"role": "system", "content": system_text(config, prompt)},
                         {"role": "user", "content": prompt.user_message(case_text)}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": name, "strict": True, "schema": prompt.output_schema}}}


def complete(config, prompt, case_text, *, attempt=1, scenario=None):
    if scenario is not None:
        raise LLMConfigError("mock_scenario is only valid with the mock provider")
    key_env = KEY_ENVS[config.provider]
    key = os.environ.get(key_env, "").strip()
    if not key and config.provider not in OPTIONAL_KEY_PROVIDERS:
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


def answer_text(content):
    """The JSON object in a reply, for services that do not enforce ``response_format``: a Markdown code fence
    around it is removed, and so is any text before the first ``{`` or after the last ``}``. Anything else is
    left as it is, so a reply without an object (such as ``category: upload``) still fails the gateway's
    strict parse."""
    text = content.strip().lstrip("\ufeff").strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        text = text[start:end + 1]
    return text


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
    return {"text": answer_text(content) if isinstance(content, str) else "", "stop_reason": stop_reason,
            "served_model": served if isinstance(served, str) and _MODEL.fullmatch(served) else config.model,
            "usage": {"input_tokens": _count(usage.get("prompt_tokens")),
                      "output_tokens": _count(usage.get("completion_tokens")), "estimated": False}}
