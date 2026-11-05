"""Offline stand-in for an AI model. It is a keyword simulation, NOT an AI model.

It exists so the whole shadow-mode flow (retry, fallback, comparison, review
flags, measurement) can be tested on GitHub without an API key or network.
Its "accuracy" says nothing about how a real model would perform.

Test scenarios (``mock_scenario`` in the step params) simulate provider
behaviour on chosen attempts, e.g. ``{"kind": "transient", "attempts": [1]}``
fails the first attempt and answers normally afterwards.

Each prompt needs its own simulation: the triage prompt uses the keyword answer below, and a domain
registers the simulation of its own prompts with :func:`register_simulator` (the study guide does, in
``app.domains.study_guide.mock_answers``). A prompt without one fails loudly instead of getting an answer
shaped for another prompt.
"""

import json
import math

from neuron_flow import SpecError

from ..errors import LLMConfigError, LLMTransientError

SCENARIO_KINDS = ("keyword", "fixed", "answer", "transient", "invalid_output", "malformed", "declined",
                  "config_error")
_ORDER = ("access", "upload", "billing")
KEYWORDS = {
    "access": ("password", "passcode", "sign in", "sign-in", "signin", "log in", "log-in", "login",
               "locked out", "account is locked", "account locked", "2fa", "two-factor", "otp",
               "verification code", "reset link", "account access",
               "รหัสผ่าน", "เข้าสู่ระบบ", "ล็อกอิน", "ล็อคอิน", "บัญชีถูกล็อก", "บัญชีถูกล็อค", "สิทธิ์เข้าใช้"),
    "upload": ("upload", "attach", "file transfer", "file size", "too large to send", "drag and drop",
               "อัปโหลด", "อัพโหลด", "แนบไฟล์", "ไฟล์แนบ", "ส่งไฟล์"),
    "billing": ("payment", "billing", "invoice", "receipt", "refund", "charge", "subscription",
                "credit card", "declined", "ชำระเงิน", "จ่ายเงิน", "ใบแจ้งหนี้", "ใบเสร็จ", "คืนเงิน",
                "หักเงิน", "ค่าบริการ", "สมัครสมาชิก"),
}


def validate_scenario(scenario):
    if not isinstance(scenario, dict) or scenario.get("kind") not in SCENARIO_KINDS:
        raise SpecError(f"mock_scenario needs a kind from: {', '.join(SCENARIO_KINDS)}")
    allowed = {"kind", "attempts"}
    if scenario["kind"] == "fixed":
        allowed |= {"category", "confidence", "rationale"}
        if not isinstance(scenario.get("category"), str):
            raise SpecError("A fixed mock_scenario needs a category")
        for key in ("confidence", "rationale"):
            if key in scenario and not isinstance(scenario[key], str):
                raise SpecError(f"mock_scenario {key} must be text")
    elif scenario["kind"] == "answer":  # any prompt: the exact answer fields, as text
        allowed |= {"answer"}
        answer = scenario.get("answer")
        if (not isinstance(answer, dict) or not answer
                or not all(isinstance(k, str) and isinstance(v, str) for k, v in answer.items())):
            raise SpecError("An answer mock_scenario needs an answer object of text fields")
    if set(scenario) - allowed:
        raise SpecError("mock_scenario has unsupported fields")
    attempts = scenario.get("attempts")
    if attempts is not None and (not isinstance(attempts, list) or not attempts
                                 or any(type(a) is not int or not 1 <= a <= 5 for a in attempts)
                                 or len(set(attempts)) != len(attempts)):
        raise SpecError("mock_scenario attempts must be unique attempt numbers 1-5")
    return scenario


def keyword_answer(case_text):
    text = case_text.lower()
    matched = {category: sorted({word for word in words if word in text}) for category, words in KEYWORDS.items()}
    scores = {category: len(words) for category, words in matched.items()}
    best = max(scores.values())
    if best == 0:
        return {"category": "other", "confidence": "medium",
                "rationale": "Keyword simulation (not an AI model): no category keywords found."}
    winners = [category for category in _ORDER if scores[category] == best]
    category = winners[0]
    if len(winners) > 1:
        confidence = "low"
    elif any(scores[other] for other in _ORDER if other != category):
        confidence = "medium"
    else:
        confidence = "high"
    return {"category": category, "confidence": confidence,
            "rationale": "Keyword simulation (not an AI model): matched " + ", ".join(matched[category]) + "."}


_SIMULATORS = {"triage_classify_v1": lambda prompt, text: keyword_answer(text)}


def register_simulator(prompt_id, simulate):
    """Register ``simulate(prompt, text) -> answer dict`` for one prompt id. Registering the same function
    again is a no-op; a different one for the same prompt is refused."""
    known = _SIMULATORS.get(prompt_id)
    if known is not None and known is not simulate:
        raise ValueError(f"A different mock simulation is already registered for prompt {prompt_id}")
    _SIMULATORS[prompt_id] = simulate


def complete(config, prompt, case_text, *, attempt=1, scenario=None):
    scenario = validate_scenario(scenario or {"kind": "keyword"})
    applies = "attempts" not in scenario or attempt in scenario["attempts"]
    kind = scenario["kind"] if applies else "keyword"
    if kind == "transient":
        raise LLMTransientError("Simulated provider outage (mock)")
    if kind == "config_error":
        raise LLMConfigError("Simulated credential rejection (mock)")
    stop_reason, text = "end_turn", ""
    if kind == "declined":
        stop_reason = "refusal"
    elif kind == "malformed":
        text = "Sorry, I cannot answer in JSON right now."
    elif kind == "invalid_output":
        text = json.dumps({"category": "priority_override", "confidence": "high",
                           "rationale": "Simulated off-contract answer (mock)."})
    elif kind == "fixed":
        text = json.dumps({"category": scenario["category"], "confidence": scenario.get("confidence", "high"),
                           "rationale": scenario.get("rationale", "Fixed answer from a test scenario (mock).")},
                          ensure_ascii=False)
    elif kind == "answer":
        text = json.dumps(scenario["answer"], ensure_ascii=False)
    else:
        simulate = _SIMULATORS.get(prompt.id)
        if simulate is None:
            raise LLMConfigError(f"The mock provider has no simulation for prompt {prompt.id}")
        text = json.dumps(simulate(prompt, case_text), ensure_ascii=False)
    request_chars = len(prompt.system) + len(prompt.user_message(case_text))
    return {"text": text, "stop_reason": stop_reason, "served_model": config.model,
            "usage": {"input_tokens": max(1, math.ceil(request_chars / 4)),
                      "output_tokens": max(1, math.ceil(len(text) / 4)), "estimated": True}}
