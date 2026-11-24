"""intake.route.v1 agents (roadmap 4.2, ADR-039): a plain-language message in, one answer out.

    understand (AI) ─► check (rules) ─► respond (rules)

1. ``understand`` masks personal data in the message, then asks the AI which task of the frame it asks for, or
   ``out_of_scope``, with a confidence, the message's language, whether it says enough (``needs_more``), whether
   study resources could help (``also_study``) and a one-sentence restatement. The answer's task is limited to the
   frame's ids by the answer schema. The AI never writes a field of the task: it only says which task.
2. ``check`` is rules: the task must be one of the frame's, and the person's message must give that task's one field
   (its length, from the frame, whose limits were probed against the task's own input check). The AI's
   ``needs_more`` can only add a question; it never skips a check.
3. ``respond`` is rules too and gives exactly one kind of answer: ``proposal`` (the task, with the person's own words
   as its field), ``confirm`` (the same, when the AI was unsure), ``question`` (the frame's one question for the
   field), ``out_of_scope`` (the frame's honest sentence and every task with one example) or ``not_understood`` (the
   AI gave no answer: the same list, so the person can still choose).

The router decides nothing and runs nothing: its job ends ``COMPLETED`` (ADR-018), and a task starts only when a
person confirms a proposal (roadmap 4.2's second part), through normal admission. No answer carries a ``decision``.

The frame comes from the services layer as plain data, frozen into every step's params with its tag; this domain
never imports ``app.services``. Failures follow ADR-012 like the study guide: a provider hiccup or an off-contract
answer is retried once, then the step answers ``unavailable`` and the router answers ``not_understood``.
"""

import math
import re

from app.llm import (REDACTION_VERSION, InvalidModelOutput, LLMConfig, LLMConfigError, LLMTransientError,
                     ModelDeclined, load_prompt, mask, structured_answer)
from app.llm.gateway import TEXT_LIMIT
from app.llm.prompts import specialize
from app.llm.redaction import KINDS as MASKED_KINDS

from . import mock_answers
from .contracts import (CONFIDENCE_LEVELS, CONFIRM_QUESTION, FINAL_ATTEMPT_REASONS, KINDS, LANGUAGES,
                        NOT_UNDERSTOOD, OUT_OF_SCOPE, ROUTE_VERSION, STUDY_TASK, UNAVAILABLE_REASONS,
                        UNDERSTAND_PROMPT_ID, YES_NO, language_of, visible_length)

# A link or web address in AI text. Bare names such as "roadmap.sh" are not links and stay allowed.
URL = re.compile(r"(?i)://|\bwww\.|\b(?:https?|javascript|mailto|ftp):")
_UNDERSTAND_OK = {"status", "task", "confidence", "language", "needs_more", "also_study", "restatement",
                  "provenance", "usage", "latency_ms", "served_model", "attempt", "masked"}
_UNAVAILABLE = {"status", "reason", "error_type", "provenance", "attempt", "masked"}
_CHECK_KEYS = {"task", "field", "fits", "reason"}
RESPONSE_KEYS = {"kind", "language", "task", "workflow_type", "restatement", "confirm_question", "question", "input",
                 "system_fields", "also", "intro", "can_help_with", "frame", "rules"}
_ = mock_answers  # imported for its side effect: the mock provider can answer the router's prompt


# --- shared --------------------------------------------------------------------------------------------

def _require(step, condition, problem):
    if not condition:
        raise ValueError(f"{step} output rejected: {problem}")


def task_of(frame, task_id):
    for task in frame["tasks"]:
        if task["id"] == task_id:
            return task
    raise KeyError(task_id)


def person_field(task):
    """The task's one field a person gives (route-1 needs exactly one; the workflow builder checks it)."""
    (field,) = [field for field in task["fields"] if field["given_by"] == "person"]
    return field


def menu(frame, language):
    """Every task in the person's language, with one example: what an out-of-scope answer lists."""
    return [{"task": task["id"], "name": task["name"][language], "example": task["examples"][language][0]}
            for task in frame["tasks"]]


def understand_prompt(frame):
    """The prompt file completed from the frame (ADR-019): one line per task, and ``task`` limited to the frame's
    ids and ``out_of_scope``. The file keeps its own SHA-256; the frame's tag is in the agent version."""
    lines = []
    for task in frame["tasks"]:
        examples = "; ".join(f'"{phrase}"' for phrase in task["examples"]["en"] + task["examples"]["th"])
        lines.append(f"- {task['id']}: {task['name']['en']} / {task['name']['th']} - {task['description']['en']} "
                     f"Needs: {person_field(task)['meaning']['en']}. Examples: {examples}")
    return specialize(load_prompt(UNDERSTAND_PROMPT_ID), extra_system_lines=lines,
                      enums={"task": [task["id"] for task in frame["tasks"]] + [OUT_OF_SCOPE]})


def _check_prompt(params):
    prompt = load_prompt(params["prompt"]["id"])
    if prompt.sha256 != params["prompt"]["sha256"]:
        raise LLMConfigError("The prompt file changed after this job was submitted")
    if params["redaction"] != REDACTION_VERSION:
        raise LLMConfigError("The personal-data masking rules changed after this job was submitted")


def _provenance(params):
    return {"provider": params["llm"]["provider"], "model": params["llm"]["model"],
            "prompt_id": params["prompt"]["id"], "prompt_sha256": params["prompt"]["sha256"],
            "redaction": params["redaction"], "frame": params["frame"]["frame_version"]}


def _ask(params, attempt, prompt, masked):
    """``(result, None)`` with an answer, or ``(None, unavailable)``; raises to let Core retry."""
    def unavailable(reason, error_type):
        return {"status": "unavailable", "reason": reason, "error_type": error_type,
                "provenance": _provenance(params), "attempt": attempt, "masked": masked.counts}

    config = LLMConfig.from_params(params["llm"])
    try:
        result = structured_answer(config, prompt, masked, attempt=attempt, scenario=params.get("mock_scenario"))
        restatement = result["answer"]["restatement"]
        if not restatement:
            raise InvalidModelOutput("The answer field restatement is empty")
        if URL.search(restatement):
            raise InvalidModelOutput("The answer contains a link or a web address")
    except ModelDeclined:
        return None, unavailable("model_declined", "ModelDeclined")
    except (LLMTransientError, InvalidModelOutput) as exc:
        if attempt < params["max_attempts"]:
            raise  # Core waits retry_delay_s and tries again
        reason = "invalid_model_output" if isinstance(exc, InvalidModelOutput) else "provider_unavailable"
        return None, unavailable(reason, type(exc).__name__)
    return result, None


# --- 1. understand (AI) -----------------------------------------------------------------------------------

def understand(message):
    params, attempt = message["params"], message["attempt"]
    _check_prompt(params)
    masked = mask(message["input"]["message"])  # the AI sees placeholders, never the masked values
    result, unavailable = _ask(params, attempt, understand_prompt(params["frame"]), masked)
    if unavailable:
        return unavailable
    answer = result["answer"]
    return {"status": "ok", "task": answer["task"], "confidence": answer["confidence"],
            "language": answer["language"], "needs_more": answer["needs_more"], "also_study": answer["also_study"],
            "restatement": answer["restatement"], "provenance": _provenance(params), "usage": result["usage"],
            "latency_ms": result["latency_ms"], "served_model": result["served_model"], "attempt": attempt,
            "masked": masked.counts}


def validate_understanding(message, output):
    step, params = "understand", message["params"]
    _require(step, isinstance(output, dict), "not an object")
    status = output.get("status")
    if status == "ok":
        _require(step, set(output) == _UNDERSTAND_OK, "unexpected or missing fields")
        usage = output["usage"]
        count = lambda value: type(value) is int and value >= 0  # noqa: E731
        _require(step, isinstance(usage, dict) and set(usage) == {"input_tokens", "output_tokens", "estimated"}
                 and count(usage["input_tokens"]) and count(usage["output_tokens"])
                 and type(usage["estimated"]) is bool, "invalid usage record")
        latency = output["latency_ms"]
        _require(step, not isinstance(latency, bool) and isinstance(latency, (int, float))
                 and math.isfinite(latency) and latency >= 0, "invalid latency")
        _require(step, isinstance(output["served_model"], str) and 1 <= len(output["served_model"]) <= 100,
                 "invalid served model")
        tasks = {task["id"] for task in params["frame"]["tasks"]}
        _require(step, output["task"] in tasks | {OUT_OF_SCOPE}, "unknown task")
        _require(step, output["confidence"] in CONFIDENCE_LEVELS, "unknown confidence level")
        _require(step, output["language"] in LANGUAGES, "unknown language")
        _require(step, output["needs_more"] in YES_NO and output["also_study"] in YES_NO, "unknown yes/no answer")
        restatement = output["restatement"]
        _require(step, isinstance(restatement, str) and 1 <= len(restatement) <= TEXT_LIMIT,
                 f"restatement must be 1-{TEXT_LIMIT} characters")
        _require(step, not URL.search(restatement), "restatement contains a link or a web address")
    elif status == "unavailable":
        _require(step, set(output) == _UNAVAILABLE, "unexpected or missing fields")
        _require(step, output["reason"] in UNAVAILABLE_REASONS, "unknown reason")
        _require(step, isinstance(output["error_type"], str) and 1 <= len(output["error_type"]) <= 100,
                 "invalid error type")
        if output["reason"] in FINAL_ATTEMPT_REASONS:
            _require(step, output["attempt"] >= params["max_attempts"], "gave up before the last allowed attempt")
    else:
        _require(step, False, "unknown status")
    masked = output["masked"]
    _require(step, isinstance(masked, dict) and set(masked) <= set(MASKED_KINDS)
             and all(type(n) is int and n > 0 for n in masked.values()), "invalid masked-data counts")
    _require(step, output["provenance"] == _provenance(params), "provenance differs from the frozen job settings")
    _require(step, output["attempt"] == message["attempt"], "attempt number mismatch")


# --- 2. check (rules) ------------------------------------------------------------------------------------

def check(message):
    """Is the AI's task one of the frame's, and does the person's message give what that task needs?"""
    frame = message["params"]["frame"]
    understood = message["dependencies"]["understand"]
    text = message["input"]["message"]
    if understood.get("status") != "ok":
        return {"task": None, "field": None, "fits": False, "reason": "not_understood"}
    if understood["task"] == OUT_OF_SCOPE:
        return {"task": OUT_OF_SCOPE, "field": None, "fits": False, "reason": "out_of_scope"}
    task = task_of(frame, understood["task"])
    field = person_field(task)
    if visible_length(text) < field["min_chars"]:
        reason = "too_short"
    elif len(text) > field["max_chars"]:
        reason = "too_long"
    elif understood["needs_more"] == "yes":  # the AI can add a question; it can never skip a check
        reason = "needs_more"
    else:
        reason = "fits"
    return {"task": task["id"], "field": field["name"], "fits": reason == "fits", "reason": reason}


def validate_check(message, output):
    _require("check", isinstance(output, dict) and set(output) == _CHECK_KEYS, "unexpected or missing fields")
    _require("check", output == check(message), f"does not follow the {ROUTE_VERSION} rules")


# --- 3. respond (rules) ----------------------------------------------------------------------------------

def respond(message):
    """Exactly one kind of answer, in the person's language. The input of a proposal is the person's own words."""
    frame = message["params"]["frame"]
    understood, checked = message["dependencies"]["understand"], message["dependencies"]["check"]
    text = message["input"]["message"]
    language = understood["language"] if understood.get("status") == "ok" else language_of(text)
    reply = {"kind": None, "language": language, "task": None, "workflow_type": None, "restatement": None,
             "confirm_question": None, "question": None, "input": None, "system_fields": [], "also": [],
             "intro": None, "can_help_with": [], "frame": frame["frame_version"], "rules": ROUTE_VERSION}
    if checked["reason"] == "not_understood":
        return {**reply, "kind": "not_understood", "intro": NOT_UNDERSTOOD[language],
                "can_help_with": menu(frame, language)}
    if checked["reason"] == "out_of_scope":
        return {**reply, "kind": "out_of_scope", "restatement": understood["restatement"],
                "intro": frame["out_of_scope"][language], "can_help_with": menu(frame, language)}
    task = task_of(frame, checked["task"])
    field = person_field(task)
    reply.update(task=task["id"], workflow_type=task["workflow_type"], restatement=understood["restatement"])
    if not checked["fits"]:
        return {**reply, "kind": "question", "question": field["question"][language]}
    reply.update(kind="confirm" if understood["confidence"] == "low" else "proposal",
                 confirm_question=CONFIRM_QUESTION[language],
                 # The person's own words, never the AI's: code copies the message into the task's field (ADR-039).
                 # Fields the application fills (a case id) are named here and set when a person confirms.
                 input={field["name"]: text},
                 system_fields=[item["name"] for item in task["fields"] if item["given_by"] == "system"])
    study = next((item for item in frame["tasks"] if item["id"] == STUDY_TASK), None)
    if understood["also_study"] == "yes" and task["id"] != STUDY_TASK and study is not None:
        study_field = person_field(study)  # the first-response rule: an offer the person may take, never instead
        if visible_length(text) >= study_field["min_chars"] and len(text) <= study_field["max_chars"]:
            reply["also"] = [{"task": study["id"], "workflow_type": study["workflow_type"],
                              "name": study["name"][language], "input": {study_field["name"]: text}}]
    return reply


def validate_response(message, output):
    _require("respond", isinstance(output, dict) and set(output) == RESPONSE_KEYS, "unexpected or missing fields")
    _require("respond", output["kind"] in KINDS, "unknown kind")
    _require("respond", output == respond(message), f"does not follow the {ROUTE_VERSION} rules")
