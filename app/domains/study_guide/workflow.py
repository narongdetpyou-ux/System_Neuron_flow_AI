"""study_guide.v1: the input contract, the trusted agent registry and the fixed five-step DAG.

    detect_topic ─► pick_resources ─► build_path ─► explain ─► answer
          └──────────────────────────────────────────┴──────────┘ (explain and answer also read it)

The last step's id is ``answer`` (its agent is ``study.prepare``), so the web page can tell it apart from
case triage's ``prepare`` step, which prepares a proposal for a reviewer.

No Core file is changed: the domain only builds a spec and registers agents (Milestone E, gate M4).

What is frozen into each job (so a changed setting can never answer an old job silently):
* every step carries the library tag (``v1@sha256:…``), and every agent version includes it;
* the AI steps also carry the AI settings, the prompt file's SHA-256 and the masking rules, like
  case_triage v2.
"""

import re

from neuron_flow import AgentDefinition, SpecError

from app.llm import REDACTION_VERSION, LLMConfig, load_prompt
from app.llm.providers import mock

from . import agents
from .contracts import (DETECT_PROMPT_ID, EXPLAIN_PROMPT_ID, LIBRARY_VERSION, LLM_MAX_ATTEMPTS, MESSAGE_MAX_CHARS,
                        MESSAGE_MIN_CHARS, STUDY_VERSION)
from .library import load_library

_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
AI_STEPS = ("detect_topic", "explain")


def check_message(request):
    """The input contract: exactly ``{"message": "..."}``, 4-500 characters after trimming."""
    if not isinstance(request, dict) or set(request) != {"message"}:
        raise SpecError("Study guide input must contain only message")
    message = request["message"]
    if not isinstance(message, str) or not MESSAGE_MIN_CHARS <= len(message.strip()) <= MESSAGE_MAX_CHARS:
        raise SpecError(f"message must contain {MESSAGE_MIN_CHARS}–{MESSAGE_MAX_CHARS} non-whitespace characters")
    return {"message": message.strip()}


def study_registry(llm_config=None):
    """Agents for study guide jobs. A real provider without an API key fails here, before any job."""
    config = llm_config or LLMConfig.from_env()
    config.check_ready()
    library = f"library={load_library(LIBRARY_VERSION).tag}"
    rules = f"{STUDY_VERSION};{library}"
    module = "app.domains.study_guide.agents"
    return [
        AgentDefinition("study.detect_topic", f"{module}:detect_topic", agents.validate_detection,
                        version=f"{config.version_tag(load_prompt(DETECT_PROMPT_ID))};{library}"),
        AgentDefinition("study.pick_resources", f"{module}:pick_resources", agents.validate_pick, version=rules),
        AgentDefinition("study.build_path", f"{module}:build_path", agents.validate_path, version=rules),
        AgentDefinition("study.explain", f"{module}:explain", agents.validate_explanation,
                        version=f"{config.version_tag(load_prompt(EXPLAIN_PROMPT_ID))};{library}"),
        AgentDefinition("study.prepare", f"{module}:prepare", agents.validate_answer, version=rules),
    ]


def build_study_workflow(job_id, request, llm_config=None, *, mock_scenarios=None):
    """One immutable study guide job. ``mock_scenarios`` (tests only, mock provider only) maps an AI step
    id to a mock scenario, e.g. ``{"explain": {"kind": "transient"}}``."""
    if not isinstance(job_id, str) or _JOB_ID.fullmatch(job_id) is None:
        raise SpecError("job_id must be a valid core identifier")
    normalized = check_message(request)
    config = llm_config or LLMConfig.from_env()
    tag = load_library(LIBRARY_VERSION).tag
    scenarios = dict(mock_scenarios or {})
    if scenarios and (config.provider != "mock" or set(scenarios) - set(AI_STEPS)):
        raise SpecError("mock_scenarios are only allowed with the mock provider, for the AI steps")

    def ai_params(step_id, prompt_id):
        prompt = load_prompt(prompt_id)
        params = {"llm": config.to_params(), "prompt": {"id": prompt.id, "sha256": prompt.sha256},
                  "library": tag, "redaction": REDACTION_VERSION, "max_attempts": LLM_MAX_ATTEMPTS}
        if step_id in scenarios:
            params["mock_scenario"] = mock.validate_scenario(scenarios[step_id])
        return params

    def ai_step(step_id, agent, prompt_id, depends_on):
        return {"id": step_id, "agent": agent, "depends_on": depends_on, "max_attempts": LLM_MAX_ATTEMPTS,
                # The HTTP timeout is shorter than the step timeout, so the agent can still answer
                # "unavailable" itself instead of being killed by Core.
                "timeout_s": float(config.request_timeout_s) + 15,
                "retry_delay_s": 0.05 if config.provider == "mock" else 2.0,
                "params": ai_params(step_id, prompt_id)}

    rules = {"library": tag}
    return {
        "job_id": job_id,
        "input": normalized,
        "steps": [
            ai_step("detect_topic", "study.detect_topic", DETECT_PROMPT_ID, []),
            {"id": "pick_resources", "agent": "study.pick_resources", "depends_on": ["detect_topic"],
             "max_attempts": 1, "params": rules},
            {"id": "build_path", "agent": "study.build_path", "depends_on": ["pick_resources"],
             "max_attempts": 1, "params": rules},
            ai_step("explain", "study.explain", EXPLAIN_PROMPT_ID, ["detect_topic", "build_path"]),
            {"id": "answer", "agent": "study.prepare",
             "depends_on": ["detect_topic", "pick_resources", "build_path", "explain"], "max_attempts": 1,
             "params": rules},
        ],
    }
