"""The plain-language router (roadmap 4.2, ADR-039): ``intake.route.v1``, the front door of Phase 4.

A person's message in, exactly one answer out: a proposal of one task from the frame (with the person's own words as
its field), a restatement to confirm when the AI is unsure, one question for missing information, an honest
out-of-scope answer, or "not understood" when the AI could not answer. The router never runs a task: a person
confirms a proposal first, and the task is then admitted through normal admission (roadmap 4.2's second part).

The frame (``app/services/frame.py``) belongs to the services layer, so this domain never imports it: the catalog
entry hands its view over as plain data, and every step keeps it, with its tag, in its frozen params.
"""

from .workflow import build_route_workflow, check_frame, check_message, route_registry

__all__ = ["build_route_workflow", "check_frame", "check_message", "route_registry"]
