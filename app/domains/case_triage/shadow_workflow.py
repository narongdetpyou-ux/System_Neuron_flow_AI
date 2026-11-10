"""case_triage.v2 (shadow mode): trusted agent registry and the fixed four-step DAG.

    classify_rules ─┐
                    ├─> compare ─> prepare
    classify_llm  ──┘

No Core file is changed: the domain only builds a spec and registers agents.
"""

from neuron_flow import AgentDefinition, SpecError

from app.llm import REDACTION_VERSION, LLMConfig, load_prompt
from app.llm.providers import mock

from . import rules, shadow_agents
from .workflow import build_workflow

PROMPT_ID = "triage_classify_v1"
LLM_MAX_ATTEMPTS = 2
SHADOW_VERSION = "shadow-1"


def shadow_registry(llm_config=None):
    """Agents for v2 jobs. A real provider without an API key fails here, before any job."""
    config = llm_config or LLMConfig.from_env()
    config.check_ready()
    prompt = load_prompt(PROMPT_ID)
    return [
        AgentDefinition("triage.classify_rules", "app.domains.case_triage.rules:classify",
                        rules.validate_classification, version=rules.rule_version()),
        AgentDefinition("triage.classify_llm", "app.domains.case_triage.shadow_agents:classify_llm",
                        shadow_agents.validate_llm_classification, version=config.version_tag(prompt)),
        AgentDefinition("triage.compare", "app.domains.case_triage.shadow_agents:compare",
                        shadow_agents.validate_comparison, version=SHADOW_VERSION),
        AgentDefinition("triage.prepare_shadow", "app.domains.case_triage.shadow_agents:prepare",
                        shadow_agents.validate_preparation, version=SHADOW_VERSION),
    ]


def build_shadow_workflow(job_id, case, llm_config=None, *, mock_scenario=None):
    """One immutable v2 job: same strict case input as v1, AI settings frozen into params."""
    base = build_workflow(job_id, case)  # reuses the v1 input contract and checks
    config = llm_config or LLMConfig.from_env()
    prompt = load_prompt(PROMPT_ID)
    llm_params = {"llm": config.to_params(), "prompt": {"id": prompt.id, "sha256": prompt.sha256},
                  "redaction": REDACTION_VERSION, "max_attempts": LLM_MAX_ATTEMPTS}
    if mock_scenario is not None:
        if config.provider != "mock":
            raise SpecError("mock_scenario is only allowed with the mock provider")
        llm_params["mock_scenario"] = mock.validate_scenario(mock_scenario)
    return {
        "job_id": base["job_id"],
        "input": base["input"],
        "steps": [
            {"id": "classify_rules", "agent": "triage.classify_rules", "max_attempts": 1,
             "params": {"rule_version": rules.rule_version()}},
            {"id": "classify_llm", "agent": "triage.classify_llm", "max_attempts": LLM_MAX_ATTEMPTS,
             # The HTTP timeout is shorter than the step timeout, so the agent can still
             # answer "unavailable" itself instead of being killed by Core.
             "timeout_s": float(config.request_timeout_s) + 15,
             "retry_delay_s": 0.05 if config.provider == "mock" else 2.0,
             "params": llm_params},
            {"id": "compare", "agent": "triage.compare",
             "depends_on": ["classify_rules", "classify_llm"], "max_attempts": 1},
            {"id": "prepare", "agent": "triage.prepare_shadow", "depends_on": ["compare"], "max_attempts": 1},
        ],
    }
