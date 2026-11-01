"""Strict application input contract and fixed, trusted DAG template."""

import re
from neuron_flow import AgentDefinition, SpecError
from . import agents
from .contracts import SUMMARY_MAX_CHARS, SUMMARY_MIN_CHARS

_CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")


def registry():
    """Trusted entrypoints are built in code; never supplied by a user request."""
    return [
        AgentDefinition("triage.classify", "app.domains.case_triage.agents:classify",
                        agents.validate_classification, version="1"),
        AgentDefinition("triage.prepare", "app.domains.case_triage.agents:prepare",
                        agents.validate_preparation, version="1"),
    ]


def build_workflow(job_id, case):
    """Produce one immutable v1 core workflow from a bounded synthetic case."""
    if not isinstance(job_id, str) or _CASE_ID.fullmatch(job_id) is None:
        raise SpecError("job_id must be a valid core identifier")
    if not isinstance(case, dict) or set(case) != {"case_id", "summary"}:
        raise SpecError("Case input must contain only case_id and summary")
    case_id = case["case_id"]
    summary = case["summary"]
    if not isinstance(case_id, str) or _CASE_ID.fullmatch(case_id) is None:
        raise SpecError("case_id must be a valid identifier")
    if not isinstance(summary, str) or not SUMMARY_MIN_CHARS <= len(summary.strip()) <= SUMMARY_MAX_CHARS:
        raise SpecError(f"summary must contain {SUMMARY_MIN_CHARS}–{SUMMARY_MAX_CHARS} non-whitespace characters")
    return {
        "job_id": job_id,
        "input": {"case_id": case_id, "summary": summary.strip()},
        "steps": [
            {"id": "classify", "agent": "triage.classify", "max_attempts": 1},
            {"id": "prepare", "agent": "triage.prepare",
             "depends_on": ["classify"], "max_attempts": 1},
        ],
    }
