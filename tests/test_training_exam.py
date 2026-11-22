"""Own-model track T4: the exam before use (training/exam.py, .github/workflows/own-model-exam.yml, ADR-037).

Reports here come from the real scorecard with the offline mock AI, then are changed case by case (and their figures
recomputed with the scorecard's own code) so that each criterion is shown to fail when it should. The workflow is
checked against the local lane: the same llama.cpp build, the same round 0 file, the recipe's serving flags, the
client's longest wait, the probe before each exam and the comparison on one runner.
"""

import contextlib
import copy
import io
import json
from pathlib import Path
import re
import tempfile
import unittest

from app.eval.triage_shadow_eval import compute_metrics, evaluate, load_golden
from app.llm import LLMConfig
from training import check_set, exam, receipt, train_qlora

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = (ROOT / ".github" / "workflows" / "own-model-exam.yml").read_text(encoding="utf-8")
LANE = (ROOT / ".github" / "workflows" / "local-model-eval.yml").read_text(encoding="utf-8")
SCRIPT = (ROOT / ".github" / "scripts" / "run_exam.sh").read_text(encoding="utf-8")


def recompute(report):
    report["metrics"] = compute_metrics(report["cases"])
    return report


class ExamTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # One small real report (mock AI), copied for every set: compare() needs only the figures.
        dev = evaluate(load_golden(ROOT / "app/eval/golden/case_triage_synthetic_v1.json"), LLMConfig(), limit=8,
                       max_workers=2)
        cls.reports = {name: copy.deepcopy(dev) for name in exam.SET_NAMES}

    def pair(self):
        return copy.deepcopy(self.reports), copy.deepcopy(self.reports)


class CompareTests(ExamTestCase):
    def test_the_same_answers_pass_every_criterion(self):
        result = exam.compare(*self.pair())
        self.assertTrue(result["passed"])
        self.assertEqual([c["key"] for c in result["criteria"]],
                         ["unavailable", "ai_correct_heldout", "ai_correct_hard", "rules_mistakes_raised",
                          "needs_person_raised", "bipia_raised", "latency"])
        self.assertEqual(result["version"], "exam-criteria-v1")

    def check_fails(self, change, key):
        baseline, candidate = self.pair()
        change(baseline, candidate)
        for report in (*baseline.values(), *candidate.values()):
            recompute(report)
        result = exam.compare(baseline, candidate)
        failed = {c["key"] for c in result["criteria"] if not c["passed"]}
        self.assertFalse(result["passed"])
        self.assertIn(key, failed)

    def test_more_missing_answers_fail(self):
        def change(_base, cand):
            row = cand["dev"]["cases"][0]
            row.update(llm_status="unavailable", llm_category=None, llm_latency_ms=None, llm_reason="invalid_model_output")
        self.check_fails(change, "unavailable")

    def test_fewer_correct_answers_on_the_held_out_or_hard_set_fail(self):
        for name in ("heldout", "hard"):
            def change(_base, cand, name=name):
                row = next(r for r in cand[name]["cases"] if r["llm_category"] == r["expected"])
                row["llm_category"] = next(c for c in ("access", "upload", "billing", "other") if c != row["expected"])
            with self.subTest(set=name):
                self.check_fails(change, f"ai_correct_{name}")

    def test_fewer_rule_mistakes_raised_fail(self):
        def change(base, cand):
            for report, priority in ((base["edge"], "elevated"), (cand["edge"], "normal")):
                row = report["cases"][0]
                row["rules_category"] = next(c for c in ("access", "upload", "billing", "other") if c != row["expected"])
                row["review_priority"] = priority
        self.check_fails(change, "rules_mistakes_raised")

    def test_fewer_cases_that_need_a_person_raised_fail(self):
        def change(base, cand):
            for report, priority in ((base["attention"], "elevated"), (cand["attention"], "normal")):
                row = report["cases"][0]
                row["tags"] = [*row["tags"], "needs_person"]
                row["review_priority"] = priority
        self.check_fails(change, "needs_person_raised")

    def test_fewer_bipia_attacks_raised_fail(self):
        def change(base, cand):
            base["bipia"]["cases"][0]["review_priority"] = "elevated"
            cand["bipia"]["cases"][0]["review_priority"] = "normal"
        self.check_fails(change, "bipia_raised")

    def test_answers_much_slower_than_round_0_fail(self):
        def change(base, cand):
            for name in exam.SET_NAMES:
                for row in base[name]["cases"]:
                    row["llm_latency_ms"] = 1000.0
                for row in cand[name]["cases"]:
                    row["llm_latency_ms"] = 1600.0  # 1.6 times: over the 1.5 limit
        self.check_fails(change, "latency")

    def test_reports_must_cover_every_set_with_the_same_cases(self):
        baseline, candidate = self.pair()
        del candidate["bipia"]
        with self.assertRaisesRegex(ValueError, "every exam set"):
            exam.compare(baseline, candidate)
        baseline, candidate = self.pair()
        candidate["hard"]["cases"].pop()
        with self.assertRaisesRegex(ValueError, "hard"):
            exam.compare(baseline, recompute_all(candidate))

    def test_a_candidate_receipt_must_be_valid_and_trained_for_today(self):
        plan, problems = train_qlora.plan(receipt.RECIPE, check_set.DEFAULT_SET)
        self.assertEqual(problems, [])
        digest = "ab" * 32
        run = {"base_files": {"model.safetensors": "cd" * 32}, "gpu": "test", "dtype": "float16",
               "train_seconds": 1.0, "steps": 1, "losses": [], "adapter": {"sha256": "12" * 32},
               "gguf": {"file": "c.gguf", "name": "c", "sha256": digest, "bytes": 1, "model_id": f"c:{digest[:12]}",
                        "llama_cpp_commit": "f" * 40, "quant": "Q4_K_M"}}
        good = train_qlora.build_receipt(plan, run, None, None)
        self.assertTrue(exam.compare(*self.pair(), good)["passed"])
        stale = copy.deepcopy(good)
        stale["serving_contract"]["prompt_sha256"] = "0" * 64
        other_set = copy.deepcopy(good)
        other_set["training_set"]["sha256"] = "1" * 64
        for bad in (stale, other_set):
            result = exam.compare(*self.pair(), bad)
            self.assertFalse(result["passed"])
            self.assertEqual([c["key"] for c in result["criteria"] if not c["passed"]], ["receipt"])


def recompute_all(reports):
    for report in reports.values():
        recompute(report)
    return reports


class ProbeAndDigestTests(ExamTestCase):
    def test_the_probe_is_eight_clear_development_cases(self):
        probe = exam.make_probe()
        self.assertEqual([case["case_id"] for case in probe["cases"]], list(exam.PROBE_IDS))
        self.assertTrue(all(case["tags"] == ["clear"] for case in probe["cases"]))
        pairs = {(case["language"], case["expected_category"]) for case in probe["cases"]}
        self.assertEqual(len(pairs), 8)  # each category once in each language

    def probe_report(self):
        probe = exam.make_probe()
        return {"cases": [{"case_id": c["case_id"], "expected": c["expected_category"], "llm_status": "ok",
                           "llm_category": c["expected_category"], "llm_reason": None} for c in probe["cases"]]}

    def test_a_probe_passes_only_with_every_clear_answer_right_and_well_formed(self):
        self.assertEqual(exam.probe_problems(self.probe_report()), [])
        broken = self.probe_report()
        broken["cases"][0].update(llm_status="unavailable", llm_reason="invalid_model_output", llm_category=None)
        wrong = self.probe_report()
        wrong["cases"][1]["llm_category"] = "billing" if wrong["cases"][1]["expected"] != "billing" else "other"
        missing = self.probe_report()
        missing["cases"].pop()
        for report, words in ((broken, "no usable answer"), (wrong, "the clear answer is"), (missing, "not in the report")):
            with self.subTest(words=words):
                self.assertTrue(any(words in p for p in exam.probe_problems(report)))

    def test_digest_lines_carry_ids_and_labels_never_case_text(self):
        lines = exam.digest_lines("r0", {"dev": self.reports["dev"]})
        cases = [json.loads(line.split(" ", 1)[1]) for line in lines if line.startswith("EXAM-CASE ")]
        metrics = [json.loads(line.split(" ", 1)[1]) for line in lines if line.startswith("EXAM-METRICS ")]
        self.assertEqual(len(cases), len(self.reports["dev"]["cases"]))
        self.assertEqual(len(metrics), 1)
        text = "\n".join(lines)
        for row in self.reports["dev"]["cases"]:
            self.assertNotIn(row["summary"], text)
        self.assertNotIn("summary", cases[0])

    def test_a_raise_is_needless_only_on_an_ordinary_case(self):
        report = copy.deepcopy(self.reports["dev"])
        for row in report["cases"]:
            row["review_priority"] = "normal"
        right = [row for row in report["cases"] if row["rules_category"] == row["expected"]]
        self.assertGreaterEqual(len(right), 3)
        for row, tags in zip(right, (["clear"], ["bipia", "open_injection", "base:EN-ACC-01"], ["needs_person"])):
            row.update(review_priority="elevated", tags=tags)
        # An attack raised for a person is what the bipia criterion asks for, not a needless raise.
        self.assertEqual(exam.figures(report)["needless_raises"], 1)

    def test_report_files_must_name_their_set(self):
        self.assertEqual(exam.set_name("reports/r0/r0-heldout.json"), "heldout")
        with self.assertRaises(ValueError):
            exam.set_name("reports/r0/r0-everything.json")

    def test_the_command_line_compares_folders_and_writes_a_thai_table(self):
        with tempfile.TemporaryDirectory() as folder:
            base, cand = Path(folder) / "r0", Path(folder) / "cand"
            base.mkdir()
            cand.mkdir()
            for name, report in self.reports.items():
                (base / f"r0-{name}.json").write_text(json.dumps(report), encoding="utf-8")
                slower = copy.deepcopy(report)
                for row in slower["cases"]:
                    row["llm_latency_ms"] = (row["llm_latency_ms"] or 0) * 10 + 5
                (cand / f"cand-{name}.json").write_text(json.dumps(slower), encoding="utf-8")
            summary = Path(folder) / "summary.md"
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = exam.main(["compare", "--baseline", str(base), "--candidate", str(cand), "--name", "test",
                                  "--summary", str(summary)])
            self.assertEqual(code, 1)  # ten times slower: the latency criterion fails
            self.assertIn("FAIL latency", out.getvalue())
            self.assertIn("ไม่ผ่าน", summary.read_text(encoding="utf-8"))


class WorkflowTests(unittest.TestCase):
    def test_the_exam_uses_the_local_lane_s_build_and_round_0_file(self):
        keys = ("LLAMA_CPP_TAG", "LLAMA_CPP_COMMIT", "MODEL_REPO", "MODEL_REVISION", "MODEL_FILE", "MODEL_SHA256",
                "MODEL_NAME")
        pattern = r"^\s+(" + "|".join(keys) + r"): (\S+)$"
        self.assertEqual(dict(re.findall(pattern, WORKFLOW, re.M)), dict(re.findall(pattern, LANE, re.M)))
        self.assertEqual(len(re.findall(pattern, WORKFLOW, re.M)), len(keys))

    def test_the_exam_serves_as_the_recipe_and_waits_as_long_as_the_lane(self):
        self.assertIn("load_recipe()['serving']", SCRIPT)
        for field in ("reasoning", "temperature", "repeat_penalty", "seed", "ctx_size"):
            self.assertIn(f"s['{field}']", SCRIPT)
        self.assertIn('NEURON_FLOW_LLM_TIMEOUT_S: "300"', WORKFLOW)
        self.assertIn('NEURON_FLOW_LLM_TIMEOUT_S: "300"', LANE)
        self.assertIn("NEURON_FLOW_LLM_PROVIDER: local", WORKFLOW)

    def test_every_model_is_probed_before_its_exam_and_compared_on_the_same_runner(self):
        self.assertLess(SCRIPT.index("probe-check"), SCRIPT.index("from training.exam import EXAM_SETS"))
        self.assertIn("run_exam.sh r0", WORKFLOW)
        self.assertIn("run_exam.sh cand", WORKFLOW)
        self.assertEqual(WORKFLOW.count("runs-on:"), 1)  # one job: round 0 and the candidate on one machine
        self.assertIn("training.exam compare --baseline reports/r0 --candidate reports/cand", WORKFLOW)
        self.assertRegex(WORKFLOW, r"CANDIDATE_SHA256\" =~ \^\[0-9a-f\]\{64\}\$")  # a candidate is pinned

    def test_the_exam_sets_are_kept_out_of_training(self):
        guarded = {path for _name, path, _read in check_set.EXAM_SETS}
        for name, path in exam.EXAM_SETS:
            with self.subTest(set=name):
                if name == "bipia":  # built at run time; the Training set check workflow compares it
                    self.assertIn("open_bipia_injection_v1.json",
                                  (ROOT / ".github/workflows/training-set.yml").read_text(encoding="utf-8"))
                else:
                    self.assertIn(path, guarded)


if __name__ == "__main__":
    unittest.main()
