"""study_guide.v1 agents (roadmap 3.2): a plain-language request in, up to 5 verified resources in order out.

    detect_topic (AI) ─► pick_resources (rules) ─► build_path (rules) ─► explain (AI) ─► answer (rules)

1. ``detect_topic`` masks personal data in the message, then asks the AI which catalog topic it is about,
   or ``out_of_scope``, with a confidence, the message's language and a one-sentence restatement for the
   person to confirm. The answer's topic is limited to the catalog's ids by the answer schema.
2. ``pick_resources`` and ``build_path`` are rules (``planning.py``): at most 5 resources from the library,
   in the person's language and free ones first, prerequisites first, then easy to hard.
3. ``explain`` asks the AI for one plain sentence per chosen resource and a summary. The AI is told
   titles and purposes, never URLs, and an answer that contains a link is refused.
4. ``prepare`` (the ``answer`` step) builds the layered answer: a one-line summary, the steps (code inserts every URL from the
   library) and the details, plus "เข้าใจถูกไหม". Out of scope, it says honestly what the guide covers.

Failures follow ADR-012: a provider hiccup or an off-contract answer is retried once; on the last attempt,
or when the model declines, the step answers ``unavailable`` and the guide still answers: without a topic
it says it could not understand and lists what it covers; without an explanation it uses the library's
own text. A setup problem (bad key, unknown model) fails the step loudly. A library or prompt that changed
after the job was submitted fails the step too: an answer is never built from data it was not admitted
with.

A study guide is informational: it decides nothing about anyone and sends nothing anywhere, so its job
ends ``COMPLETED`` without human review (ADR-018). Every validator below checks the output before Core
stores it; the rule steps are recomputed and compared.
"""

import math
import re

from app.llm import (REDACTION_VERSION, InvalidModelOutput, LLMConfig, LLMConfigError, LLMTransientError,
                     ModelDeclined, load_prompt, mask, structured_answer)
from app.llm.gateway import TEXT_LIMIT
from app.llm.redaction import KINDS as MASKED_KINDS

from . import mock_answers, planning
from .ai_prompts import detect_prompt, explain_payload, explain_prompt, note_fields
from .contracts import (ANSWER_LANGUAGES, CONFIDENCE_LEVELS, CONFIRM_QUESTION, FINAL_ATTEMPT_REASONS,
                        LEVEL_LABELS, LIBRARY_VERSION, MAX_RESOURCES, PRIORITY_LABELS, STUDY_VERSION,
                        UNAVAILABLE_REASONS, LibraryChanged)
from .library import OUT_OF_SCOPE, load_library

# A link or web address in AI text. Bare names such as "roadmap.sh" are not links and stay allowed.
URL = re.compile(r"(?i)://|\bwww\.|\b(?:https?|javascript|mailto|ftp):")
_DETECT_OK = {"status", "topic", "confidence", "language", "restatement", "provenance", "usage", "latency_ms",
              "served_model", "attempt", "masked"}
_EXPLAIN_OK = {"status", "summary", "notes", "provenance", "usage", "latency_ms", "served_model", "attempt",
               "masked"}
_UNAVAILABLE = {"status", "reason", "error_type", "provenance", "attempt", "masked"}
_SKIPPED = {"status", "reason", "provenance", "attempt"}
_ANSWER_KEYS = {"kind", "status", "language", "summary", "restatement", "confirm_question", "confidence", "topic",
                "steps", "start_with", "can_help_with", "details"}
_ = mock_answers  # imported for its side effect: the mock provider can answer both study prompts


# --- shared --------------------------------------------------------------------------------------------

def _library(params):
    library = load_library(LIBRARY_VERSION)
    if library.tag != params["library"]:
        raise LibraryChanged("The study library changed after this job was submitted")
    return library


def _check_prompt(params):
    prompt = load_prompt(params["prompt"]["id"])
    if prompt.sha256 != params["prompt"]["sha256"]:
        raise LLMConfigError("The prompt file changed after this job was submitted")
    if params["redaction"] != REDACTION_VERSION:
        raise LLMConfigError("The personal-data masking rules changed after this job was submitted")


def _provenance(params):
    return {"provider": params["llm"]["provider"], "model": params["llm"]["model"],
            "prompt_id": params["prompt"]["id"], "prompt_sha256": params["prompt"]["sha256"],
            "redaction": params["redaction"], "library": params["library"]}


def _ask(params, attempt, prompt, masked, text_fields):
    """``(result, None)`` with an answer, or ``(None, unavailable)``; raises to let Core retry."""
    def unavailable(reason, error_type):
        return {"status": "unavailable", "reason": reason, "error_type": error_type,
                "provenance": _provenance(params), "attempt": attempt, "masked": masked.counts}

    config = LLMConfig.from_params(params["llm"])
    try:
        result = structured_answer(config, prompt, masked, attempt=attempt, scenario=params.get("mock_scenario"))
        for field in text_fields:
            if not result["answer"][field]:
                raise InvalidModelOutput(f"The answer field {field} is empty")
            if URL.search(result["answer"][field]):
                raise InvalidModelOutput("The answer contains a link or a web address; code adds the links")
    except ModelDeclined:
        return None, unavailable("model_declined", "ModelDeclined")
    except (LLMTransientError, InvalidModelOutput) as exc:
        if attempt < params["max_attempts"]:
            raise  # Core waits retry_delay_s and tries again
        reason = "invalid_model_output" if isinstance(exc, InvalidModelOutput) else "provider_unavailable"
        return None, unavailable(reason, type(exc).__name__)
    return result, None


def _answered(output, params, masked, attempt, **fields):
    return {"status": "ok", **fields, "provenance": _provenance(params), "usage": output["usage"],
            "latency_ms": output["latency_ms"], "served_model": output["served_model"], "attempt": attempt,
            "masked": masked.counts}


def _topic_of(detected):
    """The detected topic, or ``None`` when there is none to plan for."""
    if detected.get("status") != "ok" or detected.get("topic") == OUT_OF_SCOPE:
        return None
    return detected["topic"]


def _language(message_text, detected):
    if detected.get("status") == "ok":
        return detected["language"]
    return mock_answers.language_of(message_text)  # a plain character test, not an AI guess


def _require(step, condition, problem):
    if not condition:
        raise ValueError(f"{step} output rejected: {problem}")


def _check_text(step, value, name):
    _require(step, isinstance(value, str) and 1 <= len(value) <= TEXT_LIMIT, f"{name} must be 1-{TEXT_LIMIT} characters")
    _require(step, not URL.search(value), f"{name} contains a link or a web address")


def _check_ai_record(step, message, output, ok_keys):
    """The checks both AI steps share: the record's shape, attempts, masking counts and provenance."""
    params = message["params"]
    _require(step, isinstance(output, dict), "not an object")
    status = output.get("status")
    if status == "ok":
        _require(step, set(output) == ok_keys, "unexpected or missing fields")
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
    elif status == "unavailable":
        _require(step, set(output) == _UNAVAILABLE, "unexpected or missing fields")
        _require(step, output["reason"] in UNAVAILABLE_REASONS, "unknown reason")
        _require(step, isinstance(output["error_type"], str) and 1 <= len(output["error_type"]) <= 100,
                 "invalid error type")
        if output["reason"] in FINAL_ATTEMPT_REASONS:
            _require(step, output["attempt"] >= params["max_attempts"], "gave up before the last allowed attempt")
    elif status != "skipped":
        _require(step, False, "unknown status")
    if status != "skipped":
        masked = output["masked"]
        _require(step, isinstance(masked, dict) and set(masked) <= set(MASKED_KINDS)
                 and all(type(n) is int and n > 0 for n in masked.values()), "invalid masked-data counts")
    _require(step, output["provenance"] == _provenance(params), "provenance differs from the frozen job settings")
    _require(step, output["attempt"] == message["attempt"], "attempt number mismatch")
    return status


# --- 1. detect_topic (AI) -------------------------------------------------------------------------------

def detect_topic(message):
    params, attempt = message["params"], message["attempt"]
    library = _library(params)
    _check_prompt(params)
    masked = mask(message["input"]["message"])  # the AI sees placeholders, never the masked values
    result, unavailable = _ask(params, attempt, detect_prompt(library), masked, ("restatement",))
    if unavailable:
        return unavailable
    answer = result["answer"]
    return _answered(result, params, masked, attempt, topic=answer["topic"], confidence=answer["confidence"],
                     language=answer["language"], restatement=answer["restatement"])


def validate_detection(message, output):
    status = _check_ai_record("detect_topic", message, output, _DETECT_OK)
    _require("detect_topic", status != "skipped", "detection is never skipped")
    if status == "ok":
        topics = {topic.id for topic in _library(message["params"]).topics}
        _require("detect_topic", output["topic"] in topics | {OUT_OF_SCOPE}, "unknown topic")
        _require("detect_topic", output["confidence"] in CONFIDENCE_LEVELS, "unknown confidence level")
        _require("detect_topic", output["language"] in ANSWER_LANGUAGES, "unknown language")
        _check_text("detect_topic", output["restatement"], "restatement")


# --- 2. pick_resources and 3. build_path (rules) ----------------------------------------------------------

def pick_resources(message):
    library = _library(message["params"])
    detected = message["dependencies"]["detect_topic"]
    return planning.pick(library, _topic_of(detected), _language(message["input"]["message"], detected))


def validate_pick(message, output):
    library = _library(message["params"])
    known = {resource.id for resource in library.resources}
    _require("pick_resources", isinstance(output, dict)
             and set(output) == {"topic", "selection", "prerequisites_left_out"}, "unexpected or missing fields")
    ids = [item.get("resource_id") for item in output["selection"]]
    _require("pick_resources", len(ids) <= MAX_RESOURCES, f"more than {MAX_RESOURCES} resources")
    _require("pick_resources", len(set(ids)) == len(ids) and set(ids) <= known, "unknown or repeated resource")
    _require("pick_resources", output == pick_resources(message), "does not follow the study-1 selection rules")


def build_path(message):
    return planning.path(_library(message["params"]), message["dependencies"]["pick_resources"])


def validate_path(message, output):
    picked = message["dependencies"]["pick_resources"]
    _require("build_path", isinstance(output, dict) and set(output) == {"topic", "steps", "start_with"},
             "unexpected or missing fields")
    selected = sorted(item["resource_id"] for item in picked["selection"])
    _require("build_path", sorted(step.get("resource_id") for step in output["steps"]) == selected,
             "the steps are not exactly the selected resources")
    roles = [step.get("priority") == "prerequisite" for step in output["steps"]]
    _require("build_path", roles == sorted(roles, reverse=True), "a prerequisite comes after the topic itself")
    _require("build_path", output == build_path(message), "does not follow the study-1 ordering rules")


# --- 4. explain (AI) --------------------------------------------------------------------------------------

def explain(message):
    params, attempt = message["params"], message["attempt"]
    library = _library(params)
    _check_prompt(params)
    planned = message["dependencies"]["build_path"]
    detected = message["dependencies"]["detect_topic"]
    if not planned["steps"]:
        return {"status": "skipped", "reason": "no_plan", "provenance": _provenance(params), "attempt": attempt}
    payload = explain_payload(library, detected["language"], detected["restatement"], planned)
    masked = mask(payload)  # the plan holds the restatement, which came from the person's message
    fields = note_fields(len(planned["steps"]))
    result, unavailable = _ask(params, attempt, explain_prompt(len(fields)), masked, ["summary", *fields])
    if unavailable:
        return unavailable
    answer = result["answer"]
    return _answered(result, params, masked, attempt, summary=answer["summary"],
                     notes=[answer[field] for field in fields])


def validate_explanation(message, output):
    status = _check_ai_record("explain", message, output, _EXPLAIN_OK)
    steps = message["dependencies"]["build_path"]["steps"]
    if status == "skipped":
        _require("explain", set(output) == _SKIPPED and output["reason"] == "no_plan" and not steps,
                 "skipped although there is a plan")
    elif status == "ok":
        _require("explain", steps, "explained an empty plan")
        _check_text("explain", output["summary"], "summary")
        _require("explain", isinstance(output["notes"], list) and len(output["notes"]) == len(steps),
                 "not one note per step")
        for note in output["notes"]:
            _check_text("explain", note, "a note")


# --- 5. prepare (rules) -----------------------------------------------------------------------------------

def prepare(message):
    library = _library(message["params"])
    deps = message["dependencies"]
    detected, picked, planned, explained = (deps["detect_topic"], deps["pick_resources"], deps["build_path"],
                                            deps["explain"])
    language = _language(message["input"]["message"], detected)
    if detected["status"] != "ok":
        status = "not_understood"
    elif detected["topic"] == OUT_OF_SCOPE:
        status = "out_of_scope"
    else:
        status = "guide"
    by_id = {resource.id: resource for resource in library.resources}
    explained_ok = explained["status"] == "ok"
    steps = []
    for index, step in enumerate(planned["steps"]):
        resource = by_id[step["resource_id"]]
        steps.append({"order": step["order"], "resource_id": resource.id, "title": resource.title,
                      "url": resource.url,  # always from the library, never from an AI answer
                      "by": resource.by, "kind": resource.kind, "level": resource.level,
                      "level_label": LEVEL_LABELS[language][resource.level], "language": resource.language,
                      "access": resource.access, "topic": step["topic"], "priority": step["priority"],
                      "priority_label": PRIORITY_LABELS[language][step["priority"]],
                      "purpose": getattr(resource.purpose, language), "focus": getattr(resource.focus, language),
                      "note": explained["notes"][index] if explained_ok else None})
    topic = library.topic(planned["topic"]) if planned["topic"] else None
    frame = [{"id": t.id, "name": getattr(t.name, language)} for t in library.topics]
    return {
        "kind": "study_guide", "status": status, "language": language,
        "summary": _summary(status, language, steps, explained),
        "restatement": detected["restatement"] if detected["status"] == "ok" else None,
        "confirm_question": CONFIRM_QUESTION[language] if detected["status"] == "ok" else None,
        "confidence": detected["confidence"] if detected["status"] == "ok" else None,
        "topic": ({"id": topic.id, "name": getattr(topic.name, language), "level": topic.level,
                   "level_label": LEVEL_LABELS[language][topic.level]} if topic else None),
        "steps": steps, "start_with": planned["start_with"],
        "can_help_with": frame if status != "guide" else [],  # out of scope: say honestly what it covers
        "details": {
            "why_this_order": _WHY[language],
            "prerequisites_left_out": [{"id": t, "name": getattr(library.topic(t).name, language)}
                                       for t in picked["prerequisites_left_out"]],
            "explanation_source": "ai" if explained_ok else "library",
            "explanation_unavailable": explained.get("reason") if explained["status"] == "unavailable" else None,
            "detection_unavailable": detected.get("reason") if detected["status"] == "unavailable" else None,
            "library": message["params"]["library"], "rules": STUDY_VERSION,
        },
    }


_WHY = {
    "th": "เรียงจากพื้นฐานที่ควรรู้ก่อน แล้วไปจากง่ายไปยาก ไม่เกิน 5 แหล่ง แหล่งภาษาไทยและแหล่งฟรีมาก่อนเมื่อมี "
          "ทุกลิงก์มาจากคลังแหล่งเรียนที่ตรวจแล้ว",
    "en": "Background topics come first, then easy to hard, at most 5 resources, Thai and free resources first "
          "when there are any. Every link comes from the verified library.",
}


def _summary(status, language, steps, explained):
    if status == "guide":
        if explained["status"] == "ok":
            return explained["summary"]
        first = steps[0]["title"]
        return {"th": f"เริ่มที่ «{first}» แล้วไปต่อตามลำดับ รวม {len(steps)} แหล่ง",
                "en": f"Start with “{first}”, then follow the order: {len(steps)} resources in all."}[language]
    if status == "out_of_scope":
        return {"th": "เรื่องนี้อยู่นอกสิ่งที่ผู้ช่วยแนะนำแหล่งเรียนช่วยได้ ดูหัวข้อที่ช่วยได้ด้านล่าง",
                "en": "This is outside what the study guide can help with; the topics it covers are below."}[language]
    return {"th": "ตอนนี้ระบบยังเข้าใจคำขอไม่ได้ เพราะ AI ใช้งานไม่ได้ ลองส่งใหม่อีกครั้ง หรือดูหัวข้อที่ช่วยได้ด้านล่าง",
            "en": "The guide could not understand the request right now because the AI is unavailable. "
                  "Try again, or see the topics it covers below."}[language]


def validate_answer(message, output):
    # Policy first, so a violation gets a clear message.
    _require("prepare", isinstance(output, dict) and set(output) == _ANSWER_KEYS, "unexpected or missing fields")
    _require("prepare", output["kind"] == "study_guide", "not a study guide")
    library = _library(message["params"])
    urls = {resource.id: resource.url for resource in library.resources}
    selection = {item["resource_id"] for item in message["dependencies"]["pick_resources"]["selection"]}
    steps = output["steps"]
    _require("prepare", isinstance(steps, list) and len(steps) <= MAX_RESOURCES, f"more than {MAX_RESOURCES} steps")
    for step in steps:
        _require("prepare", step.get("resource_id") in selection, "a step cites a resource that was not selected")
        _require("prepare", step.get("url") == urls.get(step.get("resource_id")),
                 "a link does not come from the library")
        _require("prepare", step.get("purpose") and step.get("level") and step.get("language"),
                 "a resource lacks its purpose, level or language")
        if step.get("note") is not None:
            _check_text("prepare", step["note"], "a note")
    if output["status"] != "guide":
        _require("prepare", not steps and {t["id"] for t in output["can_help_with"]} == {t.id for t in library.topics},
                 "an answer without a guide must list every topic the guide covers")
    for name in ("summary", "restatement"):
        if output[name] is not None:
            _require("prepare", not URL.search(output[name]), f"{name} contains a link or a web address")
    _require("prepare", output == prepare(message), "does not follow the study-1 answer contract")
