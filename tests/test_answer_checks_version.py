"""The gateway's answer checks are versioned, and what each version does is pinned here (ADR-035).

``app.llm.config.ANSWER_CHECKS_VERSION`` is part of every AI agent's version. So when the checks change:
* a job that Core accepted under the old checks and that is caught mid-way fails as ``configuration_changed``
  instead of finishing under the new ones (``tests/test_service_runner.py``);
* a scorecard, an evidence note or a group of reviewer labels names one behaviour, never two.

The quality report of 2026-11-19 found that PR #74 changed the checks and kept the version (PR #42 had done the same).
This test makes that hard to miss: it runs ``gateway.parse_answer`` over a fixed set of replies and the gateway over
every stop reason, writes down what came out (the cleaned fields, or the class of the error), adds the text limit and
the stop reasons that count as cut off, and compares the SHA-256 of all that with the one recorded for the version.

When it fails after a change to the gateway: give the checks a new version in ``config.py`` and add a line to
``PINNED``. Never edit the line of a version that was released: jobs, traces and evidence notes carry its name.
"""

import hashlib
import json
import types
import unittest
from unittest import mock as patch

from app.llm import config as config_module
from app.llm import gateway, load_prompt, mask
from app.llm.config import ANSWER_CHECKS_VERSION, PROVIDERS, LLMConfig
from app.services.workflows import CATALOG, agents_for

# One SHA-256 per version of the checks, oldest first. v1 and v2 were never pinned (see config.py).
PINNED = {
    "answer-checks-v3": "9a2ff9576f0b7e28d66bec4bf6ad2178f6fe23eb2a390c535f611366717e1ced",
}

# A schema of its own, so a new prompt never changes this test: one fixed choice and one free-text field.
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["choice", "note"],
          "properties": {"choice": {"type": "string", "enum": ["yes", "no"]}, "note": {"type": "string"}}}

# Replies as a model could send them (JSON escapes such as \\u202e are written as the model writes them).
REPLIES = (
    ("plain", '{"choice": "yes", "note": "a short reason"}'),
    ("spaces and newlines", '  {"choice": "no", "note": "  two   spaces\\n\\tand a tab  "}  '),
    ("control characters", '{"choice": "yes", "note": "bell\\u0007 nul\\u0000 del\\u007f end"}'),
    ("line and paragraph separators", '{"choice": "yes", "note": "one\\u2028two\\u2029three"}'),
    ("half of an emoji", '{"choice": "yes", "note": "half \\ud800 of an emoji"}'),
    ("a whole emoji", '{"choice": "yes", "note": "a whole emoji \\ud83d\\ude00"}'),
    ("bidi controls", '{"choice": "yes", "note": "abc\\u202edcba\\u202c"}'),
    ("zero-width characters", '{"choice": "yes", "note": "ภา\\u200bษา and \\ud83d\\udc69\\u200d\\ud83d\\udcbb"}'),
    ("only invisible characters", '{"choice": "yes", "note": "\\u200b\\u200b\\u2060"}'),
    ("only combining marks", '{"choice": "yes", "note": "\\u0e48\\u0e49"}'),
    ("only spaces", '{"choice": "yes", "note": " \\u00a0 "}'),
    ("only punctuation", '{"choice": "yes", "note": "..."}'),
    ("Thai text, Thai digits and the baht sign", '{"choice": "no", "note": "ถูกหักเงินซ้ำ ๒ ครั้ง ฿500"}'),
    ("too long", '{"choice": "yes", "note": "' + "x" * 250 + '"}'),
    ("unknown choice", '{"choice": "maybe", "note": "x"}'),
    ("choice with a space", '{"choice": " yes", "note": "x"}'),
    ("missing field", '{"choice": "yes"}'),
    ("extra field", '{"choice": "yes", "note": "x", "extra": "y"}'),
    ("number instead of text", '{"choice": "yes", "note": 5}'),
    ("object instead of text", '{"choice": "yes", "note": {"a": 1}}'),
    ("null", '{"choice": null, "note": "x"}'),
    ("not JSON", "choice: yes\nnote: x"),
    ("a list", '[{"choice": "yes", "note": "x"}]'),
    ("empty", ""),
    ("only whitespace", " \n\t "),
    ("two objects", '{"choice": "yes", "note": "x"} {"choice": "no", "note": "y"}'),
    ("a repeated key", '{"choice": "yes", "choice": "no", "note": "x"}'),
    ("NaN", '{"choice": "yes", "note": NaN}'),
    ("byte order mark", '﻿{"choice": "yes", "note": "x"}'),
    ("a code fence", '```json\n{"choice": "yes", "note": "x"}\n```'),
    ("no text at all", None),
)

# Every stop reason a provider maps its reply onto (providers/*.py), and two it never sends today.
STOP_REASONS = ("end_turn", "stop_sequence", "max_tokens", "model_context_window_exceeded", "refusal",
                "pause_turn", "tool_use")


def _outcome(call):
    try:
        return {"fields": call()}
    except Exception as exc:  # the class is the behaviour that matters: Core retries by it (ADR-012)
        return {"error": type(exc).__name__}


def _through_the_gateway(stop_reason):
    """``structured_answer`` with a provider that returns one valid reply and the given stop reason."""
    def complete(config, prompt, case_text, *, attempt=1, scenario=None):
        return {"text": '{"choice": "yes", "note": "x"}', "stop_reason": stop_reason,
                "usage": {"input_tokens": 1, "output_tokens": 1}, "served_model": config.model}
    prompt = types.SimpleNamespace(output_schema=SCHEMA)
    with patch.patch.dict(gateway._PROVIDERS, {"mock": types.SimpleNamespace(complete=complete)}):
        return gateway.structured_answer(LLMConfig(), prompt, mask("a synthetic case"))["answer"]


def behaviour():
    """What the checks do, as one JSON-ready value."""
    return {"text_limit": gateway.TEXT_LIMIT, "cut_off": sorted(gateway._CUT_OFF),
            "replies": [[name, _outcome(lambda text=text: gateway.parse_answer(text, SCHEMA))] for name, text in REPLIES],
            "stop_reasons": [[reason, _outcome(lambda reason=reason: _through_the_gateway(reason))]
                             for reason in STOP_REASONS]}


def digest():
    material = json.dumps(behaviour(), sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("ascii")).hexdigest()


class AnswerChecksVersionTests(unittest.TestCase):
    def test_the_checks_do_what_their_version_says(self):
        self.assertIn(ANSWER_CHECKS_VERSION, PINNED, "a new version of the answer checks needs its line in PINNED")
        self.assertEqual(list(PINNED)[-1], ANSWER_CHECKS_VERSION, "the version in use is the newest one")
        self.assertEqual(digest(), PINNED[ANSWER_CHECKS_VERSION],
                         "The gateway's answer checks changed. Give them a new version (config.ANSWER_CHECKS_VERSION, "
                         "ADR-035) and add its line to PINNED; never edit the line of a released version.")

    def test_every_version_names_a_different_behaviour(self):
        self.assertEqual(len(set(PINNED.values())), len(PINNED))
        self.assertTrue(all(len(value) == 64 for value in PINNED.values()))

    def test_what_version_3_means_in_a_few_readable_cases(self):
        replies = dict(behaviour()["replies"])
        self.assertEqual(replies["bidi controls"], {"fields": {"choice": "yes", "note": "abcdcba"}})
        self.assertEqual(replies["half of an emoji"], {"fields": {"choice": "yes", "note": "half � of an emoji"}})
        for name in ("only invisible characters", "only combining marks", "only spaces", "unknown choice", "NaN"):
            self.assertEqual(replies[name], {"error": "InvalidModelOutput"}, name)
        self.assertEqual(replies["Thai text, Thai digits and the baht sign"]["fields"]["note"],
                         "ถูกหักเงินซ้ำ ๒ ครั้ง ฿500")
        self.assertEqual(len(replies["too long"]["fields"]["note"]), gateway.TEXT_LIMIT)
        stops = dict(behaviour()["stop_reasons"])
        self.assertEqual((stops["refusal"], stops["max_tokens"], stops["end_turn"]),
                         ({"error": "ModelDeclined"}, {"error": "InvalidModelOutput"},
                          {"fields": {"choice": "yes", "note": "x"}}))

    def test_the_version_is_part_of_every_ai_agent_version(self):
        prompt = load_prompt("triage_classify_v2")
        for provider in PROVIDERS:
            model = "mock-keyword-1" if provider == "mock" else "some-model-1"
            self.assertIn(f";checks={ANSWER_CHECKS_VERSION}", LLMConfig(provider=provider, model=model).version_tag(prompt))
        ai_agents = ("triage.classify_llm", "study.detect_topic", "study.explain")
        before = {agent.name: agent.version for agent in agents_for(CATALOG, LLMConfig()) if agent.name in ai_agents}
        self.assertEqual(set(before), set(ai_agents))
        for name, version in before.items():
            self.assertIn(f"checks={ANSWER_CHECKS_VERSION}", version, name)
        with patch.patch.object(config_module, "ANSWER_CHECKS_VERSION", "answer-checks-test"):
            after = {agent.name: agent.version for agent in agents_for(CATALOG, LLMConfig())}
        for name in ai_agents:
            self.assertNotEqual(before[name], after[name], name)
            self.assertIn("checks=answer-checks-test", after[name], name)


if __name__ == "__main__":
    unittest.main()
