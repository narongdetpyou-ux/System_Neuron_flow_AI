"""Turn a finished Core snapshot into the job's public result: what a person (or n8n) needs, nothing internal.

Never included: file paths (such as the receipt path), credentials, step params, or raw error
messages (an agent or validator could echo case text). Error *types* are kept, because they are
fixed class names.

Included: the reviewer proposal, a step timeline in DAG order, the AI provenance and usage of the
second opinion, how many personal-data items were masked before the AI saw the case (counts per kind,
never the values), and the receipt checksum.

``plan_view`` describes a spec's shape (step ids, agents, order, retry budget, time limit) for the web
page, again without params.
"""

_REVIEW_FIELDS = ("case_id", "suggested_category", "suggested_queue", "suggestion_source", "second_opinion",
                  "agreement", "review_required", "review_priority", "review_reasons", "decision", "mode")
_AI_PROVENANCE = ("provider", "model", "prompt_id", "prompt_sha256", "redaction")
AI_STEP = "classify_llm"       # the step whose output becomes the result's AI view
CORE_FINAL = ("SUCCEEDED", "FAILED", "DELIVERY_FAILED")
CORE_DEFAULT_MAX_ATTEMPTS = 2  # neuron_flow.model.normalize_spec default
CORE_DEFAULT_TIMEOUT_S = 5     # neuron_flow.model.normalize_spec default


def plan_view(spec):
    """The shape of a workflow spec, for people: which steps run, in what order, how often each may be
    tried and for how long. Params are never included: they carry the AI settings and prompt hash today
    and could carry anything later."""
    return [{"id": step["id"], "agent": step["agent"], "depends_on": list(step.get("depends_on") or []),
             "max_attempts": step.get("max_attempts", CORE_DEFAULT_MAX_ATTEMPTS),
             "timeout_s": step.get("timeout_s", CORE_DEFAULT_TIMEOUT_S)}
            for step in spec["steps"]]


def review_view(output):
    """A uniform reviewer proposal for v2 (shadow) and v1 (rules only); ``None`` for other outputs."""
    if not isinstance(output, dict) or "decision" not in output or "review_required" not in output:
        return None
    if output.get("mode") == "shadow":
        return {field: output.get(field) for field in _REVIEW_FIELDS}
    return {"case_id": output.get("case_id"), "suggested_category": output.get("category"),
            "suggested_queue": output.get("suggested_queue"), "suggestion_source": "rules:keywords-v1",
            "second_opinion": None, "agreement": None, "review_required": output.get("review_required"),
            "review_priority": "normal", "review_reasons": [], "decision": output.get("decision"),
            "mode": "rules_only"}


def ai_view(output):
    """Where the AI second opinion came from, what it cost in tokens and how long it took."""
    if not isinstance(output, dict) or output.get("status") not in {"ok", "unavailable"}:
        return None
    view = {"status": output["status"], **{key: (output.get("provenance") or {}).get(key) for key in _AI_PROVENANCE},
            "attempt": output.get("attempt"), "masked": output.get("masked")}
    if output["status"] == "ok":
        view.update(served_model=output.get("served_model"), usage=output.get("usage"),
                    latency_ms=output.get("latency_ms"))
    else:
        view.update(reason=output.get("reason"), error_type=output.get("error_type"))
    return view


def step_timeline(snapshot, spec):
    timeline = []
    for step in spec["steps"]:
        state = snapshot["steps"].get(step["id"], {})
        error = state.get("error") if isinstance(state.get("error"), dict) else {}
        timeline.append({"id": step["id"], "agent": step["agent"], "status": state.get("status"),
                         "attempts": state.get("attempts", 0),
                         "max_attempts": step.get("max_attempts", CORE_DEFAULT_MAX_ATTEMPTS),
                         "error_type": error.get("type")})
    return timeline


def summarize(snapshot, spec, workflow):
    """Returns ``(status, result, failure)`` for the application queue."""
    core_status = snapshot["status"]
    if core_status not in CORE_FINAL:
        raise ValueError(f"Core job is not finished ({core_status})")
    steps = step_timeline(snapshot, spec)
    receipt = snapshot.get("receipt")
    result = {"core_status": core_status, "steps": steps,
              "receipt": {"sha256": receipt["sha256"], "bytes": receipt["bytes"]} if receipt else None,
              "review": None, "ai": None, "output": None}
    llm_state = snapshot["steps"].get(AI_STEP)
    if llm_state and llm_state.get("status") == "SUCCEEDED":
        result["ai"] = ai_view(llm_state.get("output"))
    if core_status == "DELIVERY_FAILED":
        return "DELIVERY_FAILED", result, {"reason": "delivery_failed"}
    if core_status == "FAILED":
        failed = [step for step in steps if step["status"] == "FAILED"]
        return "FAILED", result, {"reason": "step_failed", "failed_steps": [step["id"] for step in failed],
                                  "error_types": sorted({step["error_type"] or "Unknown" for step in failed})}
    output = snapshot["steps"][workflow.final_step]["output"]
    review = review_view(output)
    if review is None:
        result["output"] = output
        return "COMPLETED", result, None
    result["review"] = review
    return ("REVIEW_REQUIRED" if review["review_required"] is True else "COMPLETED"), result, None


def step_events(result):
    """One queue event per step, so the job's history shows how each step ended."""
    return [(f"step.{(step['status'] or 'unknown').lower()}",
             {key: step[key] for key in ("id", "agent", "attempts", "max_attempts", "error_type")})
            for step in result["steps"]]
