"""intake.route.v1: the input contract, the trusted agent registry and the fixed three-step DAG.

    understand (AI) ─► check (rules) ─► respond (rules)
          └──────────────────────────────┘ (respond reads both)

The last step is ``respond`` rather than ``prepare``, so the web page's step names stay apart from case triage's
``prepare``. No Core file is changed: the domain only builds a spec and registers agents.

What is frozen into each job (so a changed setting can never answer an old job silently, ADR-015):
* every step carries the frame (the view the services layer hands over, ``app.services.frame.Frame.view``) and its
  tag (``frame-v1@sha256:…``); every agent version names that tag, so a changed frame is a new version;
* the AI step also carries the AI settings, the prompt file's SHA-256 and the masking rules, like case_triage v2 and
  the study guide.
"""

import copy
import re

from neuron_flow import AgentDefinition, SpecError

from app.llm import REDACTION_VERSION, LLMConfig, load_prompt
from app.llm.providers import mock

from . import agents
from .contracts import (BIDI_CONTROLS, FRAME_TAG, LLM_MAX_ATTEMPTS, MESSAGE_MAX_CHARS, MESSAGE_MIN_CHARS,
                        OUT_OF_SCOPE, ROUTE_VERSION, UNDERSTAND_PROMPT_ID, has_visible_character, visible_length)

_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
_VIEW_KEYS = {"frame_version", "languages", "out_of_scope", "tasks"}


def check_message(request):
    """The input contract: exactly ``{"message": "..."}``, 4-500 characters after trimming, at least one letter, digit
    or sign, and no characters that change the direction of the text (they make a person read something else)."""
    if not isinstance(request, dict) or set(request) != {"message"}:
        raise SpecError("Router input must contain only message")
    message = request["message"]
    if not isinstance(message, str):
        raise SpecError("message must be text")
    trimmed = message.strip()
    if BIDI_CONTROLS.search(trimmed):
        raise SpecError("message must not contain characters that change the direction of the text (bidi controls)")
    if (not MESSAGE_MIN_CHARS <= visible_length(trimmed) or len(trimmed) > MESSAGE_MAX_CHARS
            or not has_visible_character(trimmed)):
        raise SpecError(f"message must contain {MESSAGE_MIN_CHARS}–{MESSAGE_MAX_CHARS} characters, not counting "
                        "invisible ones, with at least one letter, digit or sign")
    return {"message": trimmed}


def check_frame(frame):
    """The frame as the services layer hands it over. route-1 asks one question per task, so every task needs exactly
    one field a person gives. Raises ``SpecError``; returns the frame unchanged."""
    if (not isinstance(frame, dict) or set(frame) != _VIEW_KEYS
            or not isinstance(frame["frame_version"], str) or not FRAME_TAG.fullmatch(frame["frame_version"])):
        raise SpecError("The router needs the frame's view with its version")
    tasks = frame["tasks"]
    if not isinstance(tasks, list) or not tasks or not all(isinstance(task, dict) for task in tasks):
        raise SpecError("The frame offers no task in this catalog")
    ids = [task.get("id") for task in tasks]
    if len(set(ids)) != len(ids) or OUT_OF_SCOPE in ids:
        raise SpecError("The frame's task ids must be unique and never out_of_scope")
    for task in tasks:
        asked = [field for field in task.get("fields") or [] if field.get("given_by") == "person"]
        if len(asked) != 1:
            raise SpecError(f"{ROUTE_VERSION} needs exactly one field a person gives in task {task.get('id')}")
    return frame


def route_registry(llm_config=None, frame=None):
    """Agents for router jobs. A real provider without an API key fails here, before any job."""
    config = llm_config or LLMConfig.from_env()
    config.check_ready()
    tag = check_frame(frame)["frame_version"]
    rules = f"{ROUTE_VERSION};frame={tag}"
    module = "app.domains.intake.agents"
    return [
        AgentDefinition("route.understand", f"{module}:understand", agents.validate_understanding,
                        version=f"{config.version_tag(load_prompt(UNDERSTAND_PROMPT_ID))};frame={tag}"),
        AgentDefinition("route.check", f"{module}:check", agents.validate_check, version=rules),
        AgentDefinition("route.respond", f"{module}:respond", agents.validate_response, version=rules),
    ]


def build_route_workflow(job_id, request, llm_config=None, *, frame, mock_scenario=None):
    """One immutable router job. ``mock_scenario`` (tests only, mock provider only) simulates the AI step's
    provider, e.g. ``{"kind": "transient"}``."""
    if not isinstance(job_id, str) or _JOB_ID.fullmatch(job_id) is None:
        raise SpecError("job_id must be a valid core identifier")
    normalized = check_message(request)
    frame = copy.deepcopy(check_frame(frame))
    config = llm_config or LLMConfig.from_env()
    prompt = load_prompt(UNDERSTAND_PROMPT_ID)
    ai_params = {"llm": config.to_params(), "prompt": {"id": prompt.id, "sha256": prompt.sha256}, "frame": frame,
                 "redaction": REDACTION_VERSION, "max_attempts": LLM_MAX_ATTEMPTS}
    if mock_scenario is not None:
        if config.provider != "mock":
            raise SpecError("mock_scenario is only allowed with the mock provider")
        ai_params["mock_scenario"] = mock.validate_scenario(mock_scenario)
    rules = {"frame": frame, "rules": ROUTE_VERSION}
    return {
        "job_id": job_id,
        "input": normalized,
        "steps": [
            # The HTTP timeout is shorter than the step timeout, so the agent can still answer "unavailable" itself.
            {"id": "understand", "agent": "route.understand", "max_attempts": LLM_MAX_ATTEMPTS,
             "timeout_s": float(config.request_timeout_s) + 15,
             "retry_delay_s": 0.05 if config.provider == "mock" else 2.0, "params": ai_params},
            {"id": "check", "agent": "route.check", "depends_on": ["understand"], "max_attempts": 1,
             "params": rules},
            {"id": "respond", "agent": "route.respond", "depends_on": ["understand", "check"], "max_attempts": 1,
             "params": rules},
        ],
    }
