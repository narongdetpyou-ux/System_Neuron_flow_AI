"""Versioned prompt files. Everything that shapes the model's answer lives in one file.

The SHA-256 covers the whole file content (instructions *and* answer schema), so
editing a single character produces a new agent version and old jobs cannot be
re-run silently with a different prompt.

A prompt may be *specialized* with versioned data before a call (:func:`specialize`): extra system lines
and fixed choices taken from a catalog, or extra answer fields. The template keeps the file's SHA-256, so
the caller must put the data's own version in the agent version too (ADR-019). The study guide does this
with its topic catalog and resource library.
"""

from dataclasses import dataclass
import json
from pathlib import Path
import re

from neuron_flow.model import decode, fingerprint

from .errors import LLMConfigError

PROMPT_DIR = Path(__file__).with_name("prompt_library")
_ID = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
_FIELD = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_KEYS = {"id", "description", "system_lines", "instruction", "output_schema"}
_OPTIONAL_KEYS = {"input_field"}  # the JSON field that carries the untrusted text (default "case_text")


@dataclass(frozen=True)
class PromptTemplate:
    id: str
    system: str
    instruction: str
    output_schema: dict
    sha256: str
    input_field: str = "case_text"

    def user_message(self, case_text):
        """Wrap untrusted text as a JSON string so it cannot break out into instructions."""
        payload = json.dumps({self.input_field: case_text}, ensure_ascii=False)
        return f"{self.instruction}\n{payload}"


def load_prompt(prompt_id):
    if not isinstance(prompt_id, str) or not _ID.fullmatch(prompt_id):
        raise LLMConfigError("Invalid prompt id")
    path = PROMPT_DIR / f"{prompt_id}.json"
    try:
        document = decode(path.read_bytes())
    except OSError:
        raise LLMConfigError(f"Prompt file not found: {prompt_id}") from None
    except ValueError as exc:
        raise LLMConfigError(f"Prompt file {prompt_id} is not valid JSON") from exc
    if (not isinstance(document, dict) or not _KEYS <= set(document) <= _KEYS | _OPTIONAL_KEYS
            or document["id"] != prompt_id):
        raise LLMConfigError(f"Prompt file {prompt_id} has the wrong structure")
    input_field = document.get("input_field", "case_text")
    if not isinstance(input_field, str) or not _FIELD.fullmatch(input_field):
        raise LLMConfigError(f"Prompt file {prompt_id} has an invalid input_field")
    lines, instruction, schema = document["system_lines"], document["instruction"], document["output_schema"]
    if (not isinstance(lines, list) or not lines or not all(isinstance(line, str) for line in lines)
            or not isinstance(instruction, str) or not instruction.strip()):
        raise LLMConfigError(f"Prompt file {prompt_id} needs system_lines and an instruction")
    _check_schema(schema, prompt_id)
    return PromptTemplate(prompt_id, "\n".join(lines), instruction, schema, fingerprint(document), input_field)


def specialize(prompt, *, extra_system_lines=(), enums=None, extra_properties=None):
    """A copy of ``prompt`` completed with data: more system lines, fixed choices for existing text fields
    (``enums``: field -> list of values; the field must not have choices already) and more required text
    fields (``extra_properties``: field -> description, added after the file's fields, in order).

    The result keeps the file's SHA-256. Whoever specializes a prompt must version the data separately and
    put that version in the agent version (ADR-019)."""
    schema = json.loads(json.dumps(prompt.output_schema))
    properties = schema["properties"]
    for name, values in (enums or {}).items():
        spec = properties.get(name)
        if spec is None or "enum" in spec:
            raise LLMConfigError(f"Prompt {prompt.id}: cannot add choices to field {name!r}")
        spec["enum"] = list(values)
    for name, description in (extra_properties or {}).items():
        if name in properties or not isinstance(name, str) or not _FIELD.fullmatch(name):
            raise LLMConfigError(f"Prompt {prompt.id}: cannot add field {name!r}")
        properties[name] = {"type": "string", "description": description}
    schema["required"] = list(properties)
    _check_schema(schema, prompt.id)
    lines = [line for line in extra_system_lines]
    if not all(isinstance(line, str) and line.strip() for line in lines):
        raise LLMConfigError(f"Prompt {prompt.id}: extra system lines must be text")
    system = "\n".join([prompt.system, *lines])
    return PromptTemplate(prompt.id, system, prompt.instruction, schema, prompt.sha256, prompt.input_field)


def _check_schema(schema, prompt_id):
    """Only the JSON Schema subset that the provider's strict structured output accepts."""
    problem = None
    if not isinstance(schema, dict) or schema.get("type") != "object":
        problem = "must be an object schema"
    elif schema.get("additionalProperties") is not False:
        problem = "must set additionalProperties to false"
    else:
        properties = schema.get("properties")
        required = schema.get("required")
        if not isinstance(properties, dict) or not properties or required != list(properties):
            problem = "must list every property as required, in order"
        else:
            for name, spec in properties.items():
                if not isinstance(spec, dict) or spec.get("type") != "string":
                    problem = f"property {name} must be a string"
                elif set(spec) - {"type", "enum", "description"}:
                    problem = f"property {name} uses an unsupported constraint"
                elif "enum" in spec and (not isinstance(spec["enum"], list) or not spec["enum"]
                                         or not all(isinstance(v, str) for v in spec["enum"])):
                    problem = f"property {name} has an invalid enum"
                if problem:
                    break
    if problem:
        raise LLMConfigError(f"Prompt {prompt_id} output_schema {problem}")
