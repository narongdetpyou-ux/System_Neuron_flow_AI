"""Personal data is masked before any AI call (roadmap 7.1, gap G5): Thai and English samples, the things
that must stay readable, and the proof that neither provider ever receives the masked values."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock as patch

from neuron_flow import Runtime

from app.api.routes import ApiApp, Request
from app.domains.case_triage import build_shadow_workflow, shadow_registry
from app.llm import LLMConfig, MaskedText, load_prompt, mask, structured_answer
from app.llm.redaction import REDACTION_VERSION
from app.persistence import QueueStore
from app.services.runner import Runner
from tests.fake_anthropic import FakeAnthropic, message
from tests.service_fixtures import KEY, case_body, settings

PROMPT = load_prompt("triage_classify_v1")


def thai_id(first_twelve):
    """A 13-digit Thai ID with a valid check digit."""
    total = sum(int(first_twelve[i]) * (13 - i) for i in range(12))
    return first_twelve + str((11 - total % 11) % 10)


class MaskTests(unittest.TestCase):
    def check(self, text, expected_text, expected_counts):
        masked = mask(text)
        self.assertEqual((masked.text, masked.counts), (expected_text, expected_counts), text)
        return masked

    def test_each_kind_is_masked_in_thai_and_english(self):
        valid_id = thai_id("110170023080")
        samples = [
            ("ติดต่อกลับที่ 081-234-5678 หรือ somchai.j@example.co.th อัปโหลดไม่ได้",
             "ติดต่อกลับที่ [PHONE] หรือ [EMAIL] อัปโหลดไม่ได้", {"email": 1, "phone": 1}),
            ("โทร0812345678 ล็อกอินไม่ได้", "โทร[PHONE] ล็อกอินไม่ได้", {"phone": 1}),
            ("บ้าน 02 123 4567, มือถือ +66 81 234 5678 และ 0066812345678",
             "บ้าน [PHONE], มือถือ [PHONE] และ [PHONE]", {"phone": 3}),
            ("Call +1 415 555 0132 or (02) 234 5678", "Call [PHONE] or [PHONE]", {"phone": 2}),
            ("เลขไทย ๐๘๑-๒๓๔-๕๖๗๘ โทรกลับด้วย", "เลขไทย [PHONE] โทรกลับด้วย", {"phone": 1}),
            (f"เลขบัตรประชาชน {valid_id[0]}-{valid_id[1:5]}-{valid_id[5:10]}-{valid_id[10:12]}-{valid_id[12]} หักเงินซ้ำ",
             "เลขบัตรประชาชน [THAI_ID] หักเงินซ้ำ", {"thai_id": 1}),
            ("Card 4111 1111 1111 1111 was charged twice", "Card [CARD] was charged twice", {"card": 1}),
            ("บัญชี 123-4-56789-0 โอนแล้วยังไม่เข้า", "บัญชี [NUMBER] โอนแล้วยังไม่เข้า", {"number": 1}),
            ("My name is John Smith and Mrs. Jane Doe asked Dr Lee",
             "My name is [NAME] and Mrs. [NAME] asked Dr [NAME]", {"name": 3}),
            ("Name: Alice Brown\nThe upload fails", "Name: [NAME]\nThe upload fails", {"name": 1}),
            ("นายสมชาย ใจดี แจ้งว่าอัปโหลดไม่ได้", "นาย[NAME] ใจดี แจ้งว่าอัปโหลดไม่ได้", {"name": 1}),
            ("น.ส.มาลี โทรมา, ด.ช.ต้น สมัครไม่ได้", "น.ส.[NAME] โทรมา, ด.ช.[NAME] สมัครไม่ได้", {"name": 2}),
            ("นางสาวฟ้าใส ลืมรหัสผ่าน", "นางสาว[NAME] ลืมรหัสผ่าน", {"name": 1}),
            ("นามสกุล ใจดี เข้าระบบไม่ได้", "นามสกุล [NAME] เข้าระบบไม่ได้", {"name": 1}),
            ("คุณ John แจ้งว่า upload ค้าง", "คุณ [NAME] แจ้งว่า upload ค้าง", {"name": 1}),
        ]
        for text, expected_text, expected_counts in samples:
            self.check(text, expected_text, expected_counts)

    def test_check_digits_decide_between_id_card_and_plain_number(self):
        valid_id = thai_id("310170023080")
        wrong_id = valid_id[:12] + str((int(valid_id[12]) + 1) % 10)
        self.check(valid_id, "[THAI_ID]", {"thai_id": 1})
        self.assertEqual(mask(wrong_id).counts, {"number": 1})  # still masked, just not called an ID
        self.check("4111111111111112", "[NUMBER]", {"number": 1})  # fails the Luhn check
        self.check("5500 0000 0000 0004", "[CARD]", {"card": 1})

    def test_ordinary_text_stays_readable(self):
        for text in ("เกิดเมื่อ 2026-11-03 12:30 ยอด 1,500 บาท ค้างที่ 99% เวอร์ชัน 2.5.10",
                     "IP 10.0.0.1, order 12345678, 2FA code, file over 10 MB",
                     "username: john_doe cannot log in; file name: Report final",
                     "นายจ้างของผมจ่ายเงินแล้ว แต่ระบบยังเรียกเก็บ", "นางพยาบาลส่งไฟล์ไม่ได้",
                     "คุณช่วยดูให้หน่อยได้ไหม อัปโหลดไม่ได้", "Miss the deadline? The upload failed.",
                     "นายสมชายแจ้งว่าอัปโหลดไม่ได้เลยตั้งแต่เมื่อวาน"):  # a name run into the sentence: not cut out
            self.check(text, text, {})

    def test_masking_is_stable_and_reveals_nothing(self):
        text = "Mr Somchai Jaidee, 081-234-5678, somchai@example.com, card 4111 1111 1111 1111"
        once = mask(text)
        twice = mask(once.text)
        self.assertEqual((twice.text, twice.counts), (once.text, {}))
        for secret in ("Somchai", "Jaidee", "5678", "example.com", "1111"):
            self.assertNotIn(secret, once.text)
        self.assertEqual(once.version, REDACTION_VERSION)
        with self.assertRaises(TypeError):
            mask(None)


class GatewayTests(unittest.TestCase):
    def test_the_gateway_refuses_text_that_was_not_masked(self):
        with self.assertRaisesRegex(TypeError, "masked before every AI call"):
            structured_answer(LLMConfig(), PROMPT, "I cannot upload, call 081-234-5678")
        look_alike = type("LookAlike", (), {"text": "call 081-234-5678", "counts": {}})()
        with self.assertRaises(TypeError):  # only a real MaskedText, made by mask(), is accepted
            structured_answer(LLMConfig(), PROMPT, look_alike)
        self.assertIsInstance(mask("x"), MaskedText)

    def test_claude_receives_placeholders_only(self):
        good = {"category": "upload", "confidence": "high", "rationale": "Upload problem."}
        text = "นายสมชาย ใจดี อัปโหลดไม่ได้ โทร 081-234-5678 อีเมล somchai@example.com"
        with patch.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test-0123"}):
            with FakeAnthropic([(200, message(good))]) as fake:
                config = LLMConfig(provider="anthropic", model="claude-haiku-5-5", base_url=fake.base_url,
                                   request_timeout_s=5)
                result = structured_answer(config, PROMPT, mask(text))
        self.assertEqual(result["answer"], good)
        sent = json.dumps(fake.requests[0]["body"], ensure_ascii=False)
        for value in ("สมชาย", "081-234-5678", "5678", "somchai@example.com"):
            self.assertNotIn(value, sent)
        for placeholder in ("[NAME]", "[PHONE]", "[EMAIL]"):
            self.assertIn(placeholder, sent)


class WorkflowTests(unittest.TestCase):
    SUMMARY = "อัปโหลดไฟล์แนบไม่ได้ ติดต่อนายสมชาย ที่ 081-234-5678 หรือ somchai@example.com"

    def test_the_ai_step_records_what_it_masked(self):
        with tempfile.TemporaryDirectory() as work:
            with Runtime(work, agents=shadow_registry(LLMConfig())) as runtime:
                runtime.submit(build_shadow_workflow("masked", {"case_id": "M-1", "summary": self.SUMMARY}, LLMConfig()))
                snapshot = runtime.run("masked")
        output = snapshot["steps"]["classify_llm"]["output"]
        self.assertEqual((output["status"], output["category"]), ("ok", "upload"))  # the keywords still reach the AI
        self.assertEqual(output["masked"], {"email": 1, "phone": 1, "name": 1})
        self.assertEqual(output["provenance"]["redaction"], REDACTION_VERSION)
        for value in ("สมชาย", "081-234-5678", "somchai@example.com"):
            self.assertNotIn(value, json.dumps(output, ensure_ascii=False))

    def test_the_job_view_shows_the_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            config = settings(Path(folder))
            store = QueueStore(config.queue_db)
            store.migrate()
            app = ApiApp(config, store)
            body = json.dumps(case_body("key-masking-01", summary=self.SUMMARY)).encode("utf-8")
            headers = {"content-type": "application/json", "authorization": f"Bearer {KEY}"}
            job_id = json.loads(app.handle(Request("POST", "/v1/jobs", {}, headers, body, "tester")).body)["job_id"]
            Runner(config, store=store).drain()
            view = json.loads(app.handle(Request("GET", f"/v1/jobs/{job_id}", {}, headers, b"", "tester")).body)
        self.assertEqual(view["result"]["ai"]["masked"], {"email": 1, "phone": 1, "name": 1})
        self.assertEqual(view["result"]["ai"]["redaction"], REDACTION_VERSION)
        self.assertEqual(view["input"]["summary"], self.SUMMARY)  # the person still sees the case as it was sent


if __name__ == "__main__":
    unittest.main()
