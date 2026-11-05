"""The workflows the intake accepts, and how each one becomes a Core job.

A request only names a ``workflow_type``. It can never carry agent names, import paths, step lists,
params or callbacks: this catalog is the whole frame, and anything outside it is refused at
admission ("out of scope" is a valid answer).
"""

from dataclasses import dataclass, field
from typing import Callable, Optional

from app.domains.case_triage import build_shadow_workflow, build_workflow, registry, shadow_registry
from app.domains.study_guide import build_study_workflow, check_message, study_registry

_CHECK_JOB_ID = "admission_check"
_PREVIEW_JOB_ID = "workflow_preview"
_PREVIEW_CASE = {"case_id": "PREVIEW", "summary": "Placeholder case that shows the shape of this workflow"}


@dataclass(frozen=True)
class WorkflowType:
    name: str
    description: str
    final_step: str            # the step whose output is the job's result
    check_input: Callable      # raw input -> normalized input; raises SpecError when invalid
    build_spec: Callable       # (job_id, normalized input, llm_config) -> Core workflow spec
    agents: Callable           # (llm_config) -> [AgentDefinition]
    ai_step: Optional[str] = None  # the step whose output becomes the result's AI view (and the trace's AI span)
    preview_input: dict = field(default_factory=lambda: dict(_PREVIEW_CASE))  # a placeholder that passes check_input


def check_case(case):
    """The v1 case contract (case_id + summary of 8-500 characters), shared by v1 and v2."""
    return build_workflow(_CHECK_JOB_ID, case)["input"]


CATALOG = {
    "case_triage.v2": WorkflowType(
        "case_triage.v2", "Support-case triage in shadow mode: rules suggest, AI gives a second opinion",
        "prepare", check_case,
        lambda job_id, case, config: build_shadow_workflow(job_id, case, config),
        lambda config: shadow_registry(config), ai_step="classify_llm"),
    "case_triage.v1": WorkflowType(
        "case_triage.v1", "Support-case triage with the keyword rules only",
        "prepare", check_case,
        lambda job_id, case, config: build_workflow(job_id, case),
        lambda config: registry()),
    # Informational: it answers with study resources and decides nothing, so it ends COMPLETED (ADR-018).
    "study_guide.v1": WorkflowType(
        "study_guide.v1", "Study guide: a plain-language request in, up to 5 verified study resources in order out",
        "answer", check_message,
        lambda job_id, request, config: build_study_workflow(job_id, request, config),
        lambda config: study_registry(config), ai_step="detect_topic",
        preview_input={"message": "Placeholder request that shows the shape of this workflow"}),
}
DEFAULT_WORKFLOW = "case_triage.v2"


def preview_spec(workflow, config):
    """The spec this workflow builds for a placeholder case. The web page shows its steps before a
    case is sent; nothing is admitted or run."""
    return workflow.build_spec(_PREVIEW_JOB_ID, workflow.check_input(dict(workflow.preview_input)), config)


def agents_for(catalog, config):
    """One registry for every workflow type the Runner serves. Shared names must be identical."""
    merged = {}
    for workflow in catalog.values():
        for definition in workflow.agents(config):
            known = merged.get(definition.name)
            if known is not None and known != definition:
                raise ValueError(f"Two workflow types define agent {definition.name} differently")
            merged[definition.name] = definition
    return list(merged.values())
