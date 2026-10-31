"""The single place that asks an AI provider a question and checks the answer's shape.

Flow for one call:
1. pick the provider named in the frozen job configuration (mock or anthropic);
2. send the versioned prompt plus the untrusted case text (as a JSON string);
3. treat a refusal as ``ModelDeclined`` and a cut-off answer as ``InvalidModelOutput``;
4. parse the JSON answer and check it against the prompt's answer schema
   (every field present, no extra fields, fixed choices respected);
5. clean free-text fields (no control characters, at most 200 characters).
"""

import re
import time

from neuron_flow.model import decode

from .errors import InvalidModelOutput, ModelDeclined
from .providers import anthropic, mock

TEXT_LIMIT = 200
_CUT_OFF = {"max_tokens", "model_context_window_exceeded"}
_CONTROL = re.compile(r"[\x00-\x1f\x7f  ]+")
_PROVIDERS = {"mock": mock, "anthropic": anthropic}


def structured_answer(config, prompt, case_text, *, attempt=1, scenario=None):
    provider = _PROVIDERS[config.provider]
    started = time.monotonic()
    raw = provider.complete(config, prompt, case_text, attempt=attempt, scenario=scenario)
    latency_ms = round((time.monotonic() - started) * 1000, 3)
    if raw["stop_reason"] == "refusal":
        raise ModelDeclined("The model declined to answer")
    if raw["stop_reason"] in _CUT_OFF:
        raise InvalidModelOutput(f"The answer was cut off ({raw['stop_reason']})")
    return {"answer": parse_answer(raw["text"], prompt.output_schema), "usage": raw["usage"],
            "latency_ms": latency_ms, "served_model": raw["served_model"]}


def parse_answer(text, schema):
    if not isinstance(text, str) or not text.strip():
        raise InvalidModelOutput("The model returned no answer text")
    try:
        value = decode(text.strip())
    except ValueError:
        raise InvalidModelOutput("The model answer is not valid JSON") from None
    properties = schema["properties"]
    if not isinstance(value, dict) or set(value) != set(properties):
        raise InvalidModelOutput("The model answer has missing or unexpected fields")
    result = {}
    for name, spec in properties.items():
        item = value[name]
        if not isinstance(item, str):
            raise InvalidModelOutput(f"The model answer field {name} is not text")
        if "enum" in spec:
            if item not in spec["enum"]:
                raise InvalidModelOutput(f"The model answer has an unknown {name} value")
        else:
            item = " ".join(_CONTROL.sub(" ", item).split())[:TEXT_LIMIT]
        result[name] = item
    return result
