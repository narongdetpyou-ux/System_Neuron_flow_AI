"""The single place that asks an AI provider a question and checks the answer's shape.

Flow for one call:
1. refuse text that did not go through ``redaction.mask`` (personal data is masked before every AI call). Three
   checks, so the rule holds here and not only because every agent remembers it:
   - the value must be a ``MaskedText`` that ``mask`` made under the current rules (``TypeError`` otherwise;
     ``MaskedText(...)`` cannot be called directly);
   - the text is read once, and that same string is checked and sent;
   - the gateway masks it again itself (``redaction.leftover``): if the rules would still change anything, the
     call fails with ``UnmaskedText`` and nothing leaves. Masked text never trips it, because masking masked text
     again changes nothing;
2. pick the provider named in the frozen job configuration (mock, anthropic, typhoon or local), and send the
   versioned prompt plus the masked case text (as a JSON string);
3. treat a refusal as ``ModelDeclined`` and a cut-off answer as ``InvalidModelOutput``;
4. parse the JSON answer and check it against the prompt's answer schema
   (every field present, no extra fields, fixed choices respected);
5. clean free-text fields: no control characters, at most 200 characters, and no lone surrogates (half of an
   emoji, written by the model as an escape such as ``\\ud800``). They become U+FFFD, because Core cannot store
   them: before this, one such character failed the whole case instead of reaching review (robustness
   benchmark, SYN-E2E-029).
"""

import re
import time

from neuron_flow.model import decode

from .errors import InvalidModelOutput, ModelDeclined, UnmaskedText
from .providers import anthropic, mock, openai_compat
from .redaction import REDACTION_VERSION, is_sealed, leftover

TEXT_LIMIT = 200
_CUT_OFF = {"max_tokens", "model_context_window_exceeded"}
_CONTROL = re.compile(r"[\x00-\x1f\x7f  ]+")
_LONE_SURROGATE = re.compile(r"[\ud800-\udfff]")  # json.loads joins valid pairs, so any surrogate left is alone
_PROVIDERS = {"mock": mock, "anthropic": anthropic, "typhoon": openai_compat, "local": openai_compat}


def structured_answer(config, prompt, case_text, *, attempt=1, scenario=None):
    """Ask the provider. ``case_text`` must be a :class:`MaskedText` from ``redaction.mask``."""
    text = checked_text(case_text)
    provider = _PROVIDERS[config.provider]
    started = time.monotonic()
    raw = provider.complete(config, prompt, text, attempt=attempt, scenario=scenario)
    latency_ms = round((time.monotonic() - started) * 1000, 3)
    if raw["stop_reason"] == "refusal":
        raise ModelDeclined("The model declined to answer")
    if raw["stop_reason"] in _CUT_OFF:
        raise InvalidModelOutput(f"The answer was cut off ({raw['stop_reason']})")
    return {"answer": parse_answer(raw["text"], prompt.output_schema), "usage": raw["usage"],
            "latency_ms": latency_ms, "served_model": raw["served_model"]}


def checked_text(case_text):
    """The string to send, after the three checks in the module docstring. Raises before anything is sent."""
    if not is_sealed(case_text):
        raise TypeError("structured_answer() takes text from app.llm.redaction.mask(): "
                        "personal data is masked before every AI call")
    text = case_text.text  # read once: the string checked below is the string sent
    found = leftover(text)
    if found:
        kinds = ", ".join(f"{kind} {count}" for kind, count in sorted(found.items()))
        raise UnmaskedText(f"Refused to send text that {REDACTION_VERSION} would still mask ({kinds}); "
                           "call mask() on the text first")
    return text


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
            item = " ".join(_CONTROL.sub(" ", _LONE_SURROGATE.sub("\ufffd", item)).split())[:TEXT_LIMIT]
        result[name] = item
    return result
