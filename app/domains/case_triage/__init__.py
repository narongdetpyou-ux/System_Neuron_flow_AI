"""Support-case triage domain.

* v1 (``build_workflow``/``registry``): deterministic keyword rules, no AI.
* v2 shadow mode (``build_shadow_workflow``/``shadow_registry``): the v1 rules stay
  the official suggestion and an AI model adds a second opinion and review flags.
"""

from .shadow_workflow import build_shadow_workflow, shadow_registry
from .workflow import build_workflow, registry

__all__ = ["build_workflow", "registry", "build_shadow_workflow", "shadow_registry"]
