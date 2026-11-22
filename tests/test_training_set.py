"""Own-model track T2: the synthetic training set and its overlap check (training/check_set.py, ADR-037).

The committed set must pass every record check and must not equal or nearly equal any text of any exam set. The
checker itself is tested on small sets built here, including every way it should refuse, and the training folder
is held outside the service (the image, Render's build filter and the app's imports).
"""

import ast
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

from app.domains.case_triage.contracts import ATTENTION_VALUES, CATEGORIES
from training import check_set

ROOT = Path(__file__).resolve().parent.parent


def record(**changes):
    base = {"case_id": "TR-EN-ACC-901", "language": "en", "summary": "The sign-in page rejects my new password.",
            "category": "access", "attention": "none", "confidence": "high",
            "rationale": "The customer cannot sign in after a password change."}
    base.update(changes)
    return base


def problems_of(*records):
    return [problem for _label, problem in check_set.check_records(list(records))]


def piece_result(training, exam, sealed=False):
    cases = [record(case_id=f"TR-EN-ACC-{900 + i}", summary=text) for i, text in enumerate(training)]
    return check_set.overlap(cases, [("exam", sealed, list(exam))])[0]


class CommittedSetTests(unittest.TestCase):
    def test_the_committed_set_passes_against_every_committed_exam_set(self):
        passed, problems, manifest_problems, results, _cases = check_set.run()
        self.assertEqual(problems, [])
        self.assertEqual(manifest_problems, [])
        for result in results:
            with self.subTest(exam=result["name"]):
                self.assertEqual((result["exact"], result["near"]), ([], []))
        self.assertTrue(passed)

    def test_the_manifest_pins_the_file_and_its_balance(self):
        path = check_set.DEFAULT_SET
        manifest = json.loads(check_set.manifest_path(path).read_text(encoding="utf-8"))
        self.assertEqual(manifest["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(manifest["cases"], 240)
        self.assertEqual(manifest["by_language"], {"th": 120, "en": 120})
        self.assertEqual(manifest["by_category"], {category: 60 for category in CATEGORIES})
        self.assertEqual(set(manifest["by_attention"]), set(ATTENTION_VALUES))
        self.assertTrue(all(count > 0 for count in manifest["by_attention"].values()))
        self.assertEqual(manifest["overlap_rule"], check_set.OVERLAP_RULE)
        self.assertEqual(manifest["prompt_id"], "triage_classify_v2")

    def test_every_exam_set_of_the_repository_is_checked(self):
        listed = {relative for _name, relative, _read in check_set.EXAM_SETS}
        on_disk = {str(path.relative_to(ROOT)) for folder in ("app/eval/golden", "tests/robustness")
                   for path in (ROOT / folder).glob("*.json")}
        self.assertEqual(on_disk - listed, set(), "add the new exam set to training/check_set.py EXAM_SETS")

    def test_every_exam_set_gives_its_texts(self):
        sizes = {name: len(texts) for name, _sealed, texts in check_set.exam_texts()}
        for name, expected in (("case_triage_synthetic_v1", 61), ("case_triage_heldout_v1", 40),
                               ("case_triage_autosend_hard_v1", 128), ("case_triage_attention_heldout_v1", 64),
                               ("triage_edge_golden_v1", 116), ("study_guide_synthetic_v1", 67)):
            with self.subTest(exam=name):
                self.assertEqual(sizes[name], expected)
        self.assertGreater(sizes["robustness_synthetic_v1"], 270)
        self.assertGreater(sizes["robustness_open_extract_v1"], 500)


class RecordTests(unittest.TestCase):
    def test_a_good_record_has_no_problem(self):
        self.assertEqual(problems_of(record()), [])
        thai = record(case_id="TR-TH-ACC-901", language="th", summary="เข้าสู่ระบบไม่ได้หลังเปลี่ยนรหัสผ่าน",
                      rationale="ลูกค้าเข้าสู่ระบบไม่ได้")
        self.assertEqual(problems_of(thai), [])
        placeholders = record(summary="Please call me at [PHONE]; the login code never reaches [EMAIL].")
        self.assertEqual(problems_of(placeholders), [])

    def test_labels_outside_the_prompt_are_refused(self):
        for change in ({"category": "security"}, {"attention": "urgent"}, {"confidence": "certain"}):
            with self.subTest(change=change):
                self.assertTrue(any("gateway would refuse" in p for p in problems_of(record(**change))))

    def test_personal_data_the_masking_would_change_is_refused(self):
        for change in ({"summary": "Reset link never reaches jane.doe@example.com at all."},
                       {"rationale": "Call the customer back on 0812345678."}):
            with self.subTest(change=change):
                self.assertTrue(any("masking rules would change" in p for p in problems_of(record(**change))))

    def test_the_language_must_match_the_text(self):
        for change in ({"language": "th"}, {"summary": "เข้าสู่ระบบไม่ได้หลังเปลี่ยนรหัสผ่าน"},
                       {"rationale": "ลูกค้าเข้าสู่ระบบไม่ได้"}, {"language": "fr"}):
            with self.subTest(change=change):
                self.assertTrue(any("language" in p for p in problems_of(record(**change))))

    def test_a_summary_the_workflow_would_refuse_is_refused(self):
        for summary in ("short", "Login ‮fails after reset", "x" * 501):
            with self.subTest(summary=summary[:20]):
                self.assertTrue(any("would refuse the summary" in p for p in problems_of(record(summary=summary))))

    def test_a_rationale_must_be_one_short_line(self):
        for rationale in ("", "   ", "a" * 201, "Two lines\nof rationale."):
            with self.subTest(rationale=rationale[:20]):
                self.assertTrue(any("rationale must be one line" in p for p in problems_of(record(rationale=rationale))))

    def test_ids_and_summaries_must_be_unique(self):
        same_id = problems_of(record(), record(summary="A different sign-in problem entirely here."))
        self.assertTrue(any("used twice" in p for p in same_id))
        same_text = problems_of(record(), record(case_id="TR-EN-ACC-902",
                                                 summary="  THE sign-in page   rejects my new password. "))
        self.assertTrue(any("the same summary as" in p for p in same_text))

    def test_fields_and_ids_must_have_the_set_shape(self):
        missing = record()
        del missing["rationale"]
        self.assertTrue(any("fields must be exactly" in p for p in problems_of(missing)))
        self.assertTrue(any("fields must be exactly" in p for p in problems_of(record(source="web"))))
        self.assertTrue(any("case_id must look like" in p for p in problems_of(record(case_id="case-1"))))
        self.assertTrue(problems_of("not a record"))


class OverlapTests(unittest.TestCase):
    def test_the_rule_is_the_documented_one(self):
        self.assertEqual(check_set.OVERLAP_RULE, {"version": "overlap-v1", "piece_chars": 4, "jaccard_min": 0.6,
                                                 "containment_min": 0.9, "containment_min_pieces": 20})

    def test_normalization_catches_case_width_spaces_and_invisible_characters(self):
        result = piece_result(["  I CANNOT​ sign   in to the portal "], ["i cannot sign in to the ｐｏｒｔａｌ"])
        self.assertEqual(len(result["exact"]), 1)

    def test_a_near_copy_is_caught_and_an_unrelated_text_is_not(self):
        exam = ["The weekly invoice email arrives with the wrong company address on it."]
        near = piece_result(["The weekly invoice email arrives with the wrong company name on it."], exam)
        self.assertEqual((len(near["exact"]), len(near["near"])), (0, 1))
        unrelated = piece_result(["My video upload stops at ninety percent on mobile data."], exam)
        self.assertEqual((unrelated["exact"], unrelated["near"]), ([], []))
        self.assertLess(unrelated["highest_jaccard"], check_set.OVERLAP_RULE["jaccard_min"])

    def test_an_exam_text_inside_a_longer_training_text_is_caught(self):
        exam = ["the reset link in the email has expired"]
        result = piece_result(["Hello team, the reset link in the email has expired again, and I have tried three "
                               "times today without any luck, please help me."], exam)
        self.assertEqual(len(result["near"]), 1)
        self.assertGreaterEqual(result["near"][0][3], check_set.OVERLAP_RULE["containment_min"])

    def test_a_short_exam_string_is_not_counted_as_contained(self):
        result = piece_result(["My invoice for the annual plan shows the wrong tax rate this year."], ["tax"])
        self.assertEqual((result["exact"], result["near"]), ([], []))

    def test_sealed_results_are_reported_as_counts_only(self):
        secret = "a sealed request nobody may read"
        sealed = piece_result([secret + " please"], [secret], sealed=True)
        self.assertTrue(sealed["near"] or sealed["exact"])
        lines = "\n".join(check_set.report_lines([], [], [sealed], [record()]))
        thai = "\n".join(check_set.summary_lines([], [], [sealed], [record()], False))
        for text in (lines, thai):
            self.assertNotIn("TR-EN-ACC-900", text)
            self.assertNotIn(secret, text)
            self.assertNotIn("text #", text)


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.folder = Path(self._temp.name)

    def tearDown(self):
        self._temp.cleanup()

    def write_set(self, cases):
        path = self.folder / "small_set.json"
        path.write_text(json.dumps({"schema": check_set.SCHEMA, "name": "small", "cases": cases}, ensure_ascii=False),
                        encoding="utf-8")
        return path

    def main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = check_set.main(list(args))
        return code, out.getvalue()

    def test_a_clean_set_passes_and_writes_a_thai_summary(self):
        path = self.write_set([record()])
        summary = self.folder / "summary.md"
        code, out = self.main("--set", str(path), "--write-manifest", "--summary", str(summary))
        self.assertEqual(code, 0, out)
        self.assertIn("PASSED", out)
        self.assertIn("ผ่าน", summary.read_text(encoding="utf-8"))

    def test_a_set_that_copies_an_exam_text_fails(self):
        exam = json.loads((ROOT / "app/eval/golden/case_triage_heldout_v1.json").read_text(encoding="utf-8"))
        copied = exam["cases"][0]
        language = copied["language"]
        path = self.write_set([record(case_id="TR-EN-XXX-001" if language == "en" else "TR-TH-XXX-001",
                                      language=language, summary=copied["summary"],
                                      rationale="Copied from an exam." if language == "en" else "คัดลอกจากข้อสอบ")])
        code, out = self.main("--set", str(path), "--write-manifest")
        self.assertEqual(code, 1)
        self.assertIn("exact:", out)

    def test_extra_exam_files_are_compared_too(self):
        path = self.write_set([record()])
        extra = self.folder / "open_extra_v1.json"
        extra.write_text(json.dumps({"cases": [{"summary": record()["summary"]}]}), encoding="utf-8")
        code, out = self.main("--set", str(path), "--write-manifest", "--extra", str(extra))
        self.assertEqual(code, 1)
        self.assertIn("open_extra_v1: 1 texts, 1 exact", out)

    def test_a_changed_set_fails_until_its_manifest_is_written_again(self):
        path = self.write_set([record()])
        self.assertEqual(self.main("--set", str(path), "--write-manifest")[0], 0)
        path.write_text(path.read_text(encoding="utf-8").replace("rejects", "refuses"), encoding="utf-8")
        code, out = self.main("--set", str(path))
        self.assertEqual(code, 1)
        self.assertIn("manifest problem: manifest field sha256", out)

    def test_a_missing_manifest_or_a_wrong_file_fails(self):
        path = self.write_set([record()])
        code, out = self.main("--set", str(path))
        self.assertEqual(code, 1)
        self.assertIn("write it with --write-manifest", out)
        wrong = self.folder / "wrong.json"
        wrong.write_text(json.dumps({"schema": "something-else", "cases": []}), encoding="utf-8")
        with self.assertRaises(check_set.SetError):
            check_set.load_set(wrong)


class IsolationTests(unittest.TestCase):
    def test_the_training_folder_is_never_part_of_the_service(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        copies = [line for line in dockerfile.splitlines() if line.startswith(("COPY", "ADD"))]
        self.assertTrue(copies)
        self.assertFalse(any("training" in line for line in copies))
        self.assertIn("training", (ROOT / ".dockerignore").read_text(encoding="utf-8").split())
        self.assertIn('- training/**', (ROOT / "render.yaml").read_text(encoding="utf-8"))
        for path in (ROOT / "app").rglob("*.py"):
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertNotRegex(path.read_text(encoding="utf-8"), r"(?m)^\s*(from|import) training\b")

    def test_the_checker_uses_the_standard_library_and_the_app_only(self):
        for path in sorted((ROOT / "training").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            modules = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                       for alias in node.names}
            modules |= {node.module.split(".")[0] for node in ast.walk(tree)
                        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0}
            with self.subTest(path=path.name):
                self.assertLessEqual(modules - set(sys.stdlib_module_names), {"app"})


if __name__ == "__main__":
    unittest.main()
