"""Claude (Anthropic Messages API) over the Python standard library; no SDK needed.

Request shape follows the current API guidance for the 5.5 model family:
* structured JSON output via ``output_config.format`` (forced ``tool_choice``
  is rejected by several current models, so tools are not used);
* no ``temperature``/``top_p``/``top_k`` (rejected by current models);
* optional ``output_config.effort`` only when configured.

How failures are classified (Core decides retries from the class):
* 408, 429, 5xx (incl. 529 overloaded), timeouts, network errors -> LLMTransientError
* 401, 403 (key problems), 404 (unknown model) -> LLMConfigError
* other 4xx (e.g. 400, 413) and any redirect -> LLMRequestError (redirects are
  refused so the key can never be forwarded to another host)
* a reply that is not a Messages API message -> InvalidModelOutput
The API key is read from ANTHROPIC_API_KEY at call time and never returned or logged.
"""

import http.client
import json
import os
import re
import urllib.error
import urllib.request

from neuron_flow import __version__

from ..config import API_KEY_ENV, DEFAULT_ANTHROPIC_BASE_URL
from ..errors import InvalidModelOutput, LLMConfigError, LLMRequestError, LLMTransientError

API_VERSION = "2023-06-01"
MAX_RESPONSE_BYTES = 1_048_576
_ERROR_TYPE = re.compile(r"^[a-z_]{1,60}$")
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib would forward x-api-key to a redirect target; refuse every redirect instead."""

    def redirect_request(self, *_args, **_kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)  # keeps the default proxy and TLS handling


def build_request_body(config, prompt, case_text):
    output_config = {"format": {"type": "json_schema", "schema": prompt.output_schema}}
    if config.effort:
        output_config["effort"] = config.effort
    return {"model": config.model, "max_tokens": config.max_tokens, "system": prompt.system,
            "messages": [{"role": "user", "content": prompt.user_message(case_text)}],
            "output_config": output_config}


def complete(config, prompt, case_text, *, attempt=1, scenario=None):
    if scenario is not None:
        raise LLMConfigError("mock_scenario is only valid with the mock provider")
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        raise LLMConfigError(f"{API_KEY_ENV} is not set")
    url = (config.base_url or DEFAULT_ANTHROPIC_BASE_URL).rstrip("/") + "/v1/messages"
    body = json.dumps(build_request_body(config, prompt, case_text), ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST", headers={
        "x-api-key": key, "anthropic-version": API_VERSION, "content-type": "application/json",
        "accept": "application/json", "user-agent": f"neuron-flow/{__version__}"})
    try:
        with _OPENER.open(request, timeout=config.request_timeout_s) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        _raise_for_status(exc)
    except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
        raise LLMTransientError(f"Could not reach the provider ({type(exc).__name__})") from None
    return _parse_message(raw, config)


def _raise_for_status(exc):
    status = exc.code
    detail = f"HTTP {status}"
    try:
        error_type = json.loads(exc.read(65536).decode("utf-8"))["error"]["type"]
        if isinstance(error_type, str) and _ERROR_TYPE.fullmatch(error_type):
            detail += f" {error_type}"
    except Exception:
        pass
    finally:
        exc.close()
    if status in (408, 429) or status >= 500:
        raise LLMTransientError(f"Provider temporarily unavailable ({detail})") from None
    if status in (401, 403):
        raise LLMConfigError(f"Provider rejected the API key or its permissions ({detail})") from None
    if status == 404:
        raise LLMConfigError(f"Unknown model or API endpoint ({detail})") from None
    raise LLMRequestError(f"Provider rejected the request ({detail})") from None


def _count(value):
    return value if type(value) is int and value >= 0 else 0


def _parse_message(raw, config):
    if len(raw) > MAX_RESPONSE_BYTES:
        raise InvalidModelOutput("Provider response is too large")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise InvalidModelOutput("Provider response is not JSON") from None
    if not isinstance(data, dict) or data.get("type") != "message" or not isinstance(data.get("content"), list):
        raise InvalidModelOutput("Provider response is not a Messages API message")
    text = "".join(block["text"] for block in data["content"]
                   if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str))
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    served = data.get("model")
    return {"text": text, "stop_reason": data.get("stop_reason") if isinstance(data.get("stop_reason"), str) else "",
            "served_model": served if isinstance(served, str) and _MODEL.fullmatch(served) else config.model,
            "usage": {"input_tokens": sum(_count(usage.get(k)) for k in (
                          "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")),
                      "output_tokens": _count(usage.get("output_tokens")), "estimated": False}}
