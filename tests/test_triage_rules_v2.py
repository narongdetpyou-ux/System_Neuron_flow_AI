"""Rules v2 contracts, frozen data identity and development-set regressions.

The held-out set is intentionally never loaded here; changing the keyword list
must not turn the final measurement into a development test.
"""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from neuron_flow import Runtime, SpecError

from app.domains.case_triage import agents, build_shadow_workflow, shadow_registry
from app.domains.case_triage import rules
from app.llm import LLMConfig
from app.services.workflows import CATALOG, agents_for

ROOT = Path(__file__).resolve().parent.parent


class RulesV2Tests(unittest.TestCase):
    def category(self, summary):
        return rules.classify_case({"case_id": "SYN", "summary": summary})["category"]

    def test_normalization_is_for_matching_only_and_keeps_thai_marks(self):
        for summary in ("Cannot ＬＯＧＩＮ", "Cannot LOGİN", "Forgot my pássword",
                        "Cannot log\u200bin", "Cannot log\u00adin", "Cannot log\u200cin",
                        "Cannot log\u200din", "Cannot log\u2060in", "Cannot log\ufeffin"):
            with self.subTest(summary=summary):
                case = {"case_id": "SYN", "summary": summary}
                original = dict(case)
                self.assertEqual(rules.classify_case(case)["category"], "access")
                self.assertEqual(case, original)
        thai = "ใบเสร็จไม่ถูกต้อง ลืมรหัสผ่าน"
        self.assertEqual(rules.normalize(thai), thai)
        self.assertEqual(rules.normalize(rules.normalize("PÁSSWORD ใบเสร็จ")),
                         rules.normalize("PÁSSWORD ใบเสร็จ"))

    def test_english_matches_whole_words_and_explicit_forms(self):
        for summary in ("The design in this dashboard is confusing", "Fly to Billings tomorrow",
                        "Please explain the surcharge schedule", "loginhelper is the project name",
                        "passwords_file is a variable", "A billings account for our town"):
            with self.subTest(summary=summary):
                self.assertEqual(self.category(summary), "other")
        self.assertEqual(self.category("Please assign invoice 1234 to finance"), "billing")
        self.assertEqual(self.category("Uploading attachments fails"), "upload")
        self.assertEqual(self.category("My passcodes are missing"), "access")

    def test_hyphens_and_whitespace_have_documented_forms(self):
        for summary in ("Cannot sign-in", "Cannot sign–in", "Cannot log-in",
                        "Cannot log\t \nin", "Cannot sign\u00a0in"):
            with self.subTest(summary=summary):
                self.assertEqual(self.category(summary), "access")
        self.assertEqual(self.category("The up-load of my report fails"), "upload")
        self.assertEqual(self.category("The file-transfer has failed"), "upload")

    def test_thai_matches_inside_sentences_without_spaces(self):
        for summary, expected in (("ลืมรหัสผ่านเข้าระบบไม่ได้", "access"),
                                  ("ไฟล์แนบหายไปหลังกดส่ง", "upload"),
                                  ("อัปไฟล์ไม่ขึ้นเลย", "upload"),
                                  ("โดนตัดบัตรสองครั้งเดือนนี้", "billing"),
                                  ("อยากให้เพิ่มโหมดมืด", "other")):
            with self.subTest(summary=summary):
                self.assertEqual(self.category(summary), expected)

    def test_precedence_determinism_and_human_review_queues(self):
        for summary, expected in (("invoice upload password", "access"),
                                  ("invoice attachment", "upload"),
                                  ("Login works fine, but the payment failed", "access")):
            first = rules.classify_case({"summary": summary})
            self.assertEqual(first["category"], expected)
            self.assertEqual(first["queue"], expected + "_review")
            for _ in range(5):
                self.assertEqual(rules.classify_case({"summary": summary}), first)
            self.assertEqual(set(first), {"category", "queue", "rule_version"})

    def test_data_hash_names_the_algorithm_and_exact_data(self):
        expected = "keywords-v2:" + hashlib.sha256(rules.KEYWORDS_PATH.read_bytes()).hexdigest()
        self.assertEqual(rules.rule_version(), expected)
        spec = build_shadow_workflow("frozen", {"case_id": "SYN", "summary": "Cannot upload my file"})
        step = next(s for s in spec["steps"] if s["id"] == "classify_rules")
        definition = next(d for d in shadow_registry() if d.name == step["agent"])
        self.assertEqual(step["params"]["rule_version"], expected)
        self.assertEqual(definition.version, expected)

    def test_validator_rejects_edited_data_and_tampered_classification(self):
        message = {"input": {"summary": "Cannot upload my file"},
                   "params": {"rule_version": rules.rule_version()}}
        output = rules.classify(message)
        rules.validate_classification(message, output)
        for change in ({"category": "billing"}, {"queue": "general_review"},
                       {"rule_version": "keywords-v2:wrong"}, {"decision": "APPROVED"}):
            with self.assertRaises(ValueError):
                rules.validate_classification(message, {**output, **change})
        with tempfile.TemporaryDirectory() as folder:
            edited = Path(folder) / "keywords.json"
            edited.write_bytes(rules.KEYWORDS_PATH.read_bytes() + b"\n")
            with patch.object(rules, "KEYWORDS_PATH", edited):
                with self.assertRaisesRegex(ValueError, "data changed"):
                    rules.classify(message)
                with self.assertRaisesRegex(ValueError, "data changed"):
                    rules.validate_classification(message, output)

    def test_old_core_job_refuses_a_changed_rule_data_version(self):
        case = {"case_id": "SYN", "summary": "Cannot upload my file"}
        with tempfile.TemporaryDirectory() as folder:
            core = Path(folder) / "core"
            edited = Path(folder) / "keywords.json"
            edited.write_bytes(rules.KEYWORDS_PATH.read_bytes() + b"\n")
            with Runtime(core, agents=shadow_registry(LLMConfig())) as runtime:
                runtime.submit(build_shadow_workflow("frozen", case, LLMConfig()))
            with patch.object(rules, "KEYWORDS_PATH", edited):
                with Runtime(core, agents=shadow_registry(LLMConfig())) as runtime:
                    with self.assertRaisesRegex(SpecError, "Agent version changed: triage.classify_rules"):
                        runtime.run("frozen")

    def test_bad_data_cannot_change_precedence_or_silently_load(self):
        original = json.loads(rules.KEYWORDS_PATH.read_bytes())
        for change in ({"precedence": ["billing", "upload", "access"]},
                       {"keywords": {}}, {"schema": "untrusted"}):
            with tempfile.TemporaryDirectory() as folder:
                bad = Path(folder) / "bad.json"
                bad.write_text(json.dumps({**original, **change}), encoding="utf-8")
                with self.assertRaises(ValueError):
                    rules._load(bad)

    def test_v1_stays_original_and_both_agents_share_the_runner(self):
        self.assertEqual(agents.classify({"input": {"summary": "ลืมรหัสผ่านเข้าระบบไม่ได้"}}),
                         {"category": "other", "queue": "general_review", "rule_version": "keywords-v1"})
        definitions = {d.name: d for d in agents_for(CATALOG, LLMConfig())}
        self.assertEqual(definitions["triage.classify"].version, "1")
        self.assertEqual(definitions["triage.classify_rules"].version, rules.rule_version())

    def test_development_sets_keep_every_previously_correct_answer(self):
        paths = ("app/eval/golden/case_triage_synthetic_v1.json",
                 "tests/robustness/triage_edge_golden_v1.json")
        for name in paths:
            cases = json.loads((ROOT / name).read_bytes())["cases"]
            for case in cases:
                if agents._classification(case)["category"] == case["expected_category"]:
                    with self.subTest(case=case["case_id"]):
                        self.assertEqual(rules.classify_case(case)["category"], case["expected_category"])


if __name__ == "__main__":
    unittest.main()
