"""Support-case triage domain.

* v1 (``build_workflow``/``registry``): deterministic keyword rules, no AI.
* v2 shadow mode (``build_shadow_workflow``/``shadow_registry``): the v1 rules stay
  the official suggestion and an AI model adds a second opinion and review flags.
* v2 apply (``build_apply_workflow``/``apply_registry``): records where an approved case goes, with a Core
  receipt; started only by the skill-handoff route after a person approves (roadmap 2.3, ADR-030).
"""

from .apply import build_apply_workflow, apply_registry, check_apply_input
from .shadow_workflow import build_shadow_workflow, shadow_registry
from .workflow import build_workflow, registry

__all__ = ["build_workflow", "registry", "build_shadow_workflow", "shadow_registry", "build_apply_workflow",
           "apply_registry", "check_apply_input"]
