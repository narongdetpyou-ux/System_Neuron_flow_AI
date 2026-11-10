"""case_triage.v2.apply: record where an approved case goes, with a Core receipt (roadmap 2.3, ADR-004).

It is the target of the first skill-handoff route (ADR-030): after a person approves a ``case_triage.v2`` case,
the exchange translates the approval into this workflow's own input and admits one job of it. Nobody can admit it
from outside (the catalog marks it route-only), so its input always comes from a recorded human decision.

    record_routing   (one step: rules; nothing is sent outside the system)

Its input is the case id, the category and queue the person approved, the decision id and who approved. The agent
copies them into a routing record, and Core writes that record into the job's verified receipt. It decides
nothing: the decision was made by the person before this job existed.
"""

import re

from neuron_flow import AgentDefinition, SpecError

from .contracts import CATEGORIES, QUEUE_FOR

APPLY_VERSION = "apply-1"
APPROVERS = ("owner",)  # who can approve today (ADR-027); per-person roles arrive with roadmap 2.1
STEP_ID = "record_routing"
_CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
_DECISION_ID = re.compile(r"^dec_[0-9a-f]{24}$")
_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
_FIELDS = {"case_id", "final_category", "final_queue", "decision_id", "approved_by"}
PREVIEW_INPUT = {"case_id": "PREVIEW", "final_category": "other", "final_queue": QUEUE_FOR["other"],
                 "decision_id": "dec_" + "0" * 24, "approved_by": "owner"}


def check_apply_input(raw):
    """The input contract: exactly the five fields, each from its fixed vocabulary; the queue matches the category."""
    if not isinstance(raw, dict) or set(raw) != _FIELDS:
        raise SpecError("Apply input must contain exactly: " + ", ".join(sorted(_FIELDS)))
    if not isinstance(raw["case_id"], str) or _CASE_ID.fullmatch(raw["case_id"]) is None:
        raise SpecError("case_id must be a valid identifier")
    if raw["final_category"] not in CATEGORIES:
        raise SpecError("final_category must be one of the fixed categories")
    if raw["final_queue"] != QUEUE_FOR[raw["final_category"]]:
        raise SpecError("final_queue must be the queue of final_category")
    if not isinstance(raw["decision_id"], str) or _DECISION_ID.fullmatch(raw["decision_id"]) is None:
        raise SpecError("decision_id must be a recorded decision id")
    if raw["approved_by"] not in APPROVERS:
        raise SpecError("approved_by must be a known reviewer role")
    return {field: raw[field] for field in sorted(_FIELDS)}


def record_routing(message):
    """The routing record: the approved case, its queue, the decision and who approved. Nothing goes outside."""
    case = message["input"]
    return {"kind": "routing_record", "case_id": case["case_id"], "final_category": case["final_category"],
            "final_queue": case["final_queue"], "decision_id": case["decision_id"], "approved_by": case["approved_by"],
            "sends_outside": False, "rules": message["params"]["rules"]}


def validate_routing(message, output):
    # The record must be exactly what the approved input says: no agent can change the person's decision.
    if output != record_routing(message):
        raise ValueError("The routing record must copy the approved decision exactly")


def apply_registry():
    return [AgentDefinition("triage.apply", "app.domains.case_triage.apply:record_routing", validate_routing,
                            version=APPLY_VERSION)]


def build_apply_workflow(job_id, raw):
    if not isinstance(job_id, str) or _JOB_ID.fullmatch(job_id) is None:
        raise SpecError("job_id must be a valid core identifier")
    return {"job_id": job_id, "input": check_apply_input(raw),
            "steps": [{"id": STEP_ID, "agent": "triage.apply", "max_attempts": 1, "params": {"rules": APPLY_VERSION}}]}
