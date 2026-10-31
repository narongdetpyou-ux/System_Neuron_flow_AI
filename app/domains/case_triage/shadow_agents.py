"""Shadow mode (case_triage v2): the AI gives a second opinion; it never decides.

Flow of one case:
1. ``classify_rules`` (the unchanged v1 keyword rules) makes the official suggestion.
2. ``classify_llm`` asks the AI for its own category, in parallel with step 1.
   * provider hiccup or off-contract answer -> Core retries once;
   * still failing on the last attempt, or the model declines -> ``unavailable``,
     so the case still reaches a reviewer with the rules suggestion;
   * setup problem (bad key, unknown model) -> the step fails loudly (and Sentry reports it).
3. ``compare`` lines the two up and explains disagreements as review reasons.
4. ``prepare`` builds the reviewer's proposal: always PENDING_HUMAN_REVIEW,
   ``elevated`` priority when rules and AI disagree.

Each agent has a validator that Core runs on its output before saving it:
schema (fields and types), invariants (queue matches category, provenance
matches the frozen job settings) and policy (no automatic decisions).
"""

import math

from app.llm import (InvalidModelOutput, LLMConfig, LLMConfigError, LLMTransientError, ModelDeclined,
                     load_prompt, structured_answer)
from app.llm.gateway import TEXT_LIMIT

from .contracts import (CATEGORIES, CONFIDENCE_LEVELS, FINAL_ATTEMPT_REASONS, QUEUE_FOR, REVIEW_REASONS,
                        UNAVAILABLE_REASONS)

_OK_KEYS = {"status", "category", "queue", "confidence", "rationale", "provenance", "usage",
            "latency_ms", "served_model", "attempt"}
_UNAVAILABLE_KEYS = {"status", "reason", "error_type", "provenance", "attempt"}


def _provenance(params):
    return {"provider": params["llm"]["provider"], "model": params["llm"]["model"],
            "prompt_id": params["prompt"]["id"], "prompt_sha256": params["prompt"]["sha256"]}


def _unavailable(reason, params, attempt, error_type):
    return {"status": "unavailable", "reason": reason, "error_type": error_type,
            "provenance": _provenance(params), "attempt": attempt}


def classify_llm(message):
    params = message["params"]
    attempt = message["attempt"]
    config = LLMConfig.from_params(params["llm"])
    prompt = load_prompt(params["prompt"]["id"])
    if prompt.sha256 != params["prompt"]["sha256"]:
        raise LLMConfigError("The prompt file changed after this job was submitted")
    try:
        result = structured_answer(config, prompt, message["input"]["summary"], attempt=attempt,
                                   scenario=params.get("mock_scenario"))
    except ModelDeclined:
        return _unavailable("model_declined", params, attempt, "ModelDeclined")
    except (LLMTransientError, InvalidModelOutput) as exc:
        if attempt < params["max_attempts"]:
            raise  # Core waits retry_delay_s and tries again
        reason = "invalid_model_output" if isinstance(exc, InvalidModelOutput) else "provider_unavailable"
        return _unavailable(reason, params, attempt, type(exc).__name__)
    answer = result["answer"]
    category = answer["category"]
    return {"status": "ok", "category": category, "queue": QUEUE_FOR[category],
            "confidence": answer["confidence"], "rationale": answer["rationale"],
            "provenance": _provenance(params), "usage": result["usage"],
            "latency_ms": result["latency_ms"], "served_model": result["served_model"], "attempt": attempt}


def _require(condition, problem):
    if not condition:
        raise ValueError(f"classify_llm output rejected: {problem}")


def _count(value):
    return type(value) is int and value >= 0


def validate_llm_classification(message, output):
    params = message["params"]
    _require(isinstance(output, dict), "not an object")
    status = output.get("status")
    if status == "ok":
        _require(set(output) == _OK_KEYS, "unexpected or missing fields")
        _require(output["category"] in CATEGORIES, "unknown category")
        _require(output["queue"] == QUEUE_FOR[output["category"]], "queue does not match category")
        _require(output["confidence"] in CONFIDENCE_LEVELS, "unknown confidence level")
        rationale = output["rationale"]
        _require(isinstance(rationale, str) and len(rationale) <= TEXT_LIMIT, "rationale too long")
        usage = output["usage"]
        _require(isinstance(usage, dict) and set(usage) == {"input_tokens", "output_tokens", "estimated"}
                 and _count(usage["input_tokens"]) and _count(usage["output_tokens"])
                 and type(usage["estimated"]) is bool, "invalid usage record")
        latency = output["latency_ms"]
        _require(not isinstance(latency, bool) and isinstance(latency, (int, float))
                 and math.isfinite(latency) and latency >= 0, "invalid latency")
        _require(isinstance(output["served_model"], str) and 1 <= len(output["served_model"]) <= 100,
                 "invalid served model")
    elif status == "unavailable":
        _require(set(output) == _UNAVAILABLE_KEYS, "unexpected or missing fields")
        _require(output["reason"] in UNAVAILABLE_REASONS, "unknown reason")
        _require(isinstance(output["error_type"], str) and 1 <= len(output["error_type"]) <= 100,
                 "invalid error type")
        if output["reason"] in FINAL_ATTEMPT_REASONS:
            _require(output["attempt"] >= params["max_attempts"], "gave up before the last allowed attempt")
    else:
        _require(False, "unknown status")
    _require(output["provenance"] == _provenance(params), "provenance differs from the frozen job settings")
    _require(output["attempt"] == message["attempt"], "attempt number mismatch")


def compare(message):
    rules = message["dependencies"]["classify_rules"]
    llm = message["dependencies"]["classify_llm"]
    reasons = []
    if rules["category"] == "other":
        reasons.append("rules_no_keyword_match")
    if llm["status"] == "ok":
        second = {"status": "ok", "category": llm["category"], "queue": llm["queue"],
                  "confidence": llm["confidence"], "rationale": llm["rationale"]}
        agreement = "agree" if llm["category"] == rules["category"] else "disagree"
        if agreement == "disagree":
            reasons.append("rules_llm_disagree")
        if llm["confidence"] == "low":
            reasons.append("llm_low_confidence")
    else:
        second = {"status": "unavailable", "reason": llm["reason"]}
        agreement = "llm_unavailable"
        reasons.append("llm_unavailable")
    return {"official": {"category": rules["category"], "queue": rules["queue"],
                         "source": f"rules:{rules['rule_version']}"},
            "second_opinion": second, "agreement": agreement,
            "review_priority": "elevated" if agreement == "disagree" else "normal",
            "review_reasons": sorted(reasons, key=REVIEW_REASONS.index)}


def validate_comparison(message, output):
    if output != compare(message):
        raise ValueError("compare output does not follow the shadow-1 comparison contract")


def prepare(message):
    compared = message["dependencies"]["compare"]
    return {"case_id": message["input"]["case_id"],
            "suggested_category": compared["official"]["category"],
            "suggested_queue": compared["official"]["queue"],
            "suggestion_source": compared["official"]["source"],
            "second_opinion": compared["second_opinion"],
            "agreement": compared["agreement"],
            "review_required": True,
            "review_priority": compared["review_priority"],
            "review_reasons": compared["review_reasons"],
            "decision": "PENDING_HUMAN_REVIEW",
            "mode": "shadow"}


def validate_preparation(message, output):
    # Policy first, so a violation gets a clear message: the AI never decides here.
    if not isinstance(output, dict) or output.get("decision") != "PENDING_HUMAN_REVIEW" \
            or output.get("review_required") is not True or output.get("mode") != "shadow":
        raise ValueError("Shadow mode proposals must stay PENDING_HUMAN_REVIEW with review_required")
    if output != prepare(message):
        raise ValueError("prepare output does not follow the shadow-1 proposal contract")
