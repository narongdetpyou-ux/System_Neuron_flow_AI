"""Invisible and direction-changing characters (roadmap 5.5, the robustness benchmark's gaps SYN-INT-044 to 046,
SYN-AIR-041 to 043 and SYN-E2E-030).

* A case's summary may not carry bidi controls (U+202E and the like): they make a reviewer read something other
  than what the rules and the AI read. Its minimum length counts only characters a reader can see, and it must hold
  at least one letter, digit or sign. Ordinary text, Thai with zero-width spaces between words, emoji and the old
  limits are unchanged.
* The AI's free text loses invisible format characters before anyone reads it, and an answer whose free text is
  empty or invisible is invalid: asked once more, then the case goes to review with the rules' suggestion.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from neuron_flow import Runtime, SpecError
from app.api.routes import ApiApp, Request
from app.domains.case_triage import build_shadow_workflow, build_workflow, shadow_registry
from app.domains.case_triage.contracts import SUMMARY_MAX_CHARS
from app.domains.case_triage.workflow import BIDI_CONTROLS, has_visible_character, visible_length
from app.llm import InvalidModelOutput, LLMConfig, load_prompt
from app.llm.gateway import parse_answer
from app.persistence import QueueStore
from app.services.workflows import check_case
from tests.fake_openai import FakeServer, completion
from tests.service_fixtures import KEY, case_body, settings

ZWSP, RLO, PDF = "​", "‮", "‬"
SCHEMA = load_prompt("triage_classify_v2").output_schema
UPLOAD = "I cannot upload an attachment to my ticket"


def answer(rationale, **fields):
    return json.dumps({"category": "upload", "confidence": "high", "attention": "none", "rationale": rationale,
                       **fields})


def summary_of(text):
    return check_case({"case_id": "C-1", "summary": text})["summary"]


class CaseTextTests(unittest.TestCase):
    def test_bidi_controls_are_refused_wherever_they_are(self):
        for control in ("‮", "‪", "‫", "‬", "‭", "⁦", "⁧", "⁨", "⁩",
                        "‎", "‏", "؜"):
            with self.subTest(control=f"U+{ord(control):04X}"):
                self.assertTrue(BIDI_CONTROLS.search(control))
                with self.assertRaisesRegex(SpecError, "change the direction"):
                    summary_of(f"refund {control}denied please, I was charged twice")
        with self.assertRaisesRegex(SpecError, "change the direction"):  # the rules-only demonstration shares it
            build_workflow("bidi_v1", {"case_id": "C-1", "summary": f"refund {RLO}deined{PDF} please"})

    def test_invisible_characters_do_not_count_towards_the_minimum(self):
        for text in (ZWSP * 10, ZWSP * 30 + "login", "﻿" * 9, "short" + "­" * 6):
            with self.subTest(text=ascii(text)):
                with self.assertRaisesRegex(SpecError, "not counting invisible ones"):
                    summary_of(text)
        self.assertEqual(summary_of(f"login{ZWSP}bad"), f"login{ZWSP}bad")  # 8 visible characters: enough
        self.assertEqual((visible_length(f"ab{ZWSP}cd"), visible_length("เข้าไม่ได้")), (4, 10))

    def test_marks_alone_are_not_a_case(self):
        for text in ("็" * 10, "่้๊๋" * 3, "́" * 9, " ็ " * 5):
            with self.subTest(text=ascii(text)):
                self.assertFalse(has_visible_character(text))
                with self.assertRaisesRegex(SpecError, "at least one letter, digit or sign"):
                    summary_of(text)

    def test_ordinary_text_is_accepted_and_stored_as_written(self):
        for text in ("เข้าไม่ได้",                                   # 10 characters, 7 of them consonants or vowels
                     f"ล็อก{ZWSP}อิน{ZWSP}ไม่ได้ ช่วยด้วยครับ",          # Thai copied with zero-width spaces between words
                     "\U0001f468‍\U0001f469‍\U0001f467 upload fails",  # an emoji family joined by ZWJ
                     "\U0001f600" * 8, "!!!!!!!!", "12345678", "x" * SUMMARY_MAX_CHARS,
                     "  I cannot upload an attachment  "):
            with self.subTest(text=ascii(text)[:40]):
                self.assertEqual(summary_of(text), text.strip())

    def test_the_old_limits_still_hold(self):
        for text in ("short", "x" * (SUMMARY_MAX_CHARS + 1), " " * 20, 12345678):
            with self.subTest(text=ascii(text)[:20]):
                with self.assertRaises(SpecError):
                    summary_of(text)

    def test_the_api_refuses_them_with_400_and_says_why(self):
        with tempfile.TemporaryDirectory() as folder:
            config = settings(Path(folder))
            store = QueueStore(config.queue_db)
            store.migrate()
            app = ApiApp(config, store)
            for number, text in enumerate((f"refund {RLO}deined si tnemyap{PDF} please", ZWSP * 10, "็" * 10)):
                body = json.dumps(case_body(f"key-invisible-{number:03d}", summary=text)).encode("utf-8")
                reply = app.handle(Request("POST", "/v1/jobs", {}, {"authorization": f"Bearer {KEY}",
                                                                    "content-type": "application/json"}, body, "t"))
                with self.subTest(text=ascii(text)):
                    self.assertEqual((reply.status, json.loads(reply.body)["error"]), (400, "invalid_input"))
                    self.assertIn("summary must", json.loads(reply.body)["message"])
            self.assertEqual(store.list_jobs(limit=10)[0], [])  # nothing was queued


class AiTextTests(unittest.TestCase):
    def test_invisible_characters_are_removed_from_free_text(self):
        cleaned = parse_answer(answer(f"{RLO}devorppa{PDF} see note"), SCHEMA)
        self.assertEqual((cleaned["category"], cleaned["rationale"]), ("upload", "devorppa see note"))
        self.assertEqual(parse_answer(answer(f"บัญชี{ZWSP}ถูก{ZWSP}แฮ็ก‍"), SCHEMA)["rationale"], "บัญชีถูกแฮ็ก")
        half_emoji = '{"category": "upload", "confidence": "high", "attention": "none", "rationale": "bad \\ud800 text"}'
        self.assertEqual(parse_answer(half_emoji, SCHEMA)["rationale"], "bad � text")  # as before (SYN-E2E-029)

    def test_an_empty_or_invisible_rationale_is_invalid(self):
        for rationale in ("", "   ", ZWSP * 3, f"{RLO}{PDF}", "็็", "\n\t"):
            with self.subTest(rationale=ascii(rationale)):
                with self.assertRaisesRegex(InvalidModelOutput, "rationale is empty"):
                    parse_answer(answer(rationale), SCHEMA)

    def test_fixed_choices_are_still_checked_exactly(self):
        with self.assertRaises(InvalidModelOutput):
            parse_answer(answer("ok", category=f"upload{ZWSP}"), SCHEMA)  # never cleaned into a valid choice

    def run_case(self, replies, job_id):
        with mock.patch.dict(os.environ, {"TYPHOON_API_KEY": "typhoon-test-placeholder"}), FakeServer(replies) as fake, \
                tempfile.TemporaryDirectory() as work:
            config = LLMConfig(provider="typhoon", model="typhoon-v2.5-30b-a3b-instruct", base_url=fake.base_url,
                               request_timeout_s=5)
            with Runtime(work, agents=shadow_registry(config)) as runtime:
                runtime.submit(build_shadow_workflow(job_id, {"case_id": "INV-1", "summary": UPLOAD}, config))
                return runtime.run(job_id), len(fake.requests)

    def test_a_reordered_rationale_reaches_the_reviewer_as_plain_text(self):
        snapshot, calls = self.run_case([(200, completion(answer(f"{RLO}devorppa{PDF} ok")))], "bidi_rationale")
        proposal = snapshot["steps"]["prepare"]["output"]
        self.assertEqual((snapshot["status"], calls), ("SUCCEEDED", 1))
        self.assertEqual((proposal["decision"], proposal["second_opinion"]["status"],
                          proposal["second_opinion"]["rationale"]), ("PENDING_HUMAN_REVIEW", "ok", "devorppa ok"))

    def test_an_empty_rationale_is_asked_again_then_the_rules_alone_go_to_review(self):
        snapshot, calls = self.run_case([(200, completion(answer(""))), (200, completion(answer(ZWSP)))],
                                        "empty_rationale")
        llm = snapshot["steps"]["classify_llm"]
        proposal = snapshot["steps"]["prepare"]["output"]
        self.assertEqual((snapshot["status"], calls, llm["attempts"]), ("SUCCEEDED", 2, 2))
        self.assertEqual((llm["output"]["status"], llm["output"]["reason"]), ("unavailable", "invalid_model_output"))
        self.assertEqual((proposal["decision"], proposal["suggested_category"]), ("PENDING_HUMAN_REVIEW", "upload"))
        self.assertIn("llm_unavailable", proposal["review_reasons"])


if __name__ == "__main__":
    unittest.main()
