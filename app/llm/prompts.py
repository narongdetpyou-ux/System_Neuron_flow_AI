"""Versioned prompt files. Everything that shapes the model's answer lives in one file.

The SHA-256 covers the whole file content (instructions *and* answer schema), so
editing a single character produces a new agent version and old jobs cannot be
re-run silently with a different prompt.
"""

from dataclasses import dataclass
import json
from pathlib import Path
import re

from neuron_flow.model import decode, fingerprint

from .errors import LLMConfigError

PROMPT_DIR = Path(__file__).with_name("prompt_library")
_ID = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
_KEYS = {"id", "description", "system_lines", "instruction", "output_schema"}


@dataclass(frozen=True)
class PromptTemplate:
    id: str
    system: str
    instruction: str
    output_schema: dict
    sha256: str

    def user_message(self, case_text):
        """Wrap untrusted text as a JSON string so it cannot break out into instructions."""
        payload = json.dumps({"case_text": case_text}, ensure_ascii=False)
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
    if not isinstance(document, dict) or set(document) != _KEYS or document["id"] != prompt_id:
        raise LLMConfigError(f"Prompt file {prompt_id} has the wrong structure")
    lines, instruction, schema = document["system_lines"], document["instruction"], document["output_schema"]
    if (not isinstance(lines, list) or not lines or not all(isinstance(line, str) for line in lines)
            or not isinstance(instruction, str) or not instruction.strip()):
        raise LLMConfigError(f"Prompt file {prompt_id} needs system_lines and an instruction")
    _check_schema(schema, prompt_id)
    return PromptTemplate(prompt_id, "\n".join(lines), instruction, schema, fingerprint(document))


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
