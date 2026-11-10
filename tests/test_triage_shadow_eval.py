"""Shadow-mode scorecard: case file checks, metrics arithmetic, outcome-change gate, eval gate, CLI."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from neuron_flow.model import decode

from app.domains.case_triage import build_shadow_workflow
from app.domains.case_triage.rules import rule_version
from app.eval import triage_shadow_eval as ev
from app.llm import LLMConfig

GOLDEN = ev.load_golden()
BASELINE = Path(__file__).resolve().parent / "baselines" / "shadow_eval_mock.json"
UPDATE_HINT = ("If the change is on purpose, regenerate the baseline in the same pull request with\n"
               "  python -m app.eval.triage_shadow_eval --write-baseline tests/baselines/shadow_eval_mock.json\n"
               "and explain why in the PR description (roadmap 5.2).")


def row(case_id, expected, rules, llm, *, language="en", priority=None, status="ok", tags=()):
    disagree = status == "ok" and llm != rules
    return {"case_id": case_id, "language": language, "tags": list(tags), "split": "validation",
            "cluster_id": case_id, "source_sha256": case_id * 4, "summary": f"summary {case_id}",
            "expected": expected, "job_status": "SUCCEEDED", "rules_category": rules,
            "llm_status": status, "llm_reason": None, "llm_category": llm if status == "ok" else None,
            "llm_confidence": "high" if status == "ok" else None, "llm_attempts": 1,
            "llm_latency_ms": 10.0 if status == "ok" else None, "input_tokens": 100, "output_tokens": 10,
            "usage_estimated": False, "agreement": "disagree" if disagree else "agree",
            "review_priority": priority or ("elevated" if disagree else "normal"), "review_reasons": []}


class CaseFileTests(unittest.TestCase):
    def test_synthetic_case_set_is_well_formed(self):
        cases = GOLDEN["cases"]
        self.assertGreaterEqual(len(cases), 50)
        self.assertEqual({c["language"] for c in cases}, {"en", "th"})
        self.assertEqual({c["expected_category"] for c in cases}, {"access", "upload", "billing", "other"})
        self.assertGreaterEqual(sum("injection" in c["tags"] for c in cases), 3)
        self.assertEqual(len({c["case_id"] for c in cases}), len(cases))
        self.assertEqual({c["split"] for c in cases}, {"validation", "holdout"})
        for case in cases:  # every case passes the real input contract
            build_shadow_workflow("eval_" + case["case_id"], {"case_id": case["case_id"], "summary": case["summary"]})

    def test_bad_case_files_are_rejected(self):
        good = json.loads(ev.DEFAULT_GOLDEN.read_text("utf-8"))
        broken = [dict(good, schema="other"), dict(good, cases=[]),
                  dict(good, cases=good["cases"][:1] * 2),
                  dict(good, cases=[{**good["cases"][0], "expected_category": "refund"}]),
                  dict(good, cases=[{**good["cases"][0], "extra": 1}])]
        with tempfile.TemporaryDirectory() as folder:
            for index, document in enumerate(broken):
                path = Path(folder) / f"bad{index}.json"
                path.write_text(json.dumps(document), "utf-8")
                with self.assertRaises(ValueError, msg=index):
                    ev.load_golden(path)


class MetricsTests(unittest.TestCase):
    def test_scorecard_arithmetic(self):
        rows = [row("a", "upload", "upload", "upload"),
                row("b", "upload", "other", "upload", language="th"),          # AI caught a rules miss
                row("c", "billing", "billing", "access"),                      # AI wrong, flagged anyway
                row("d", "access", "billing", "billing", tags=["injection"]),  # both fooled, not flagged
                row("e", "other", "other", None, status="unavailable")]
        m = ev.compute_metrics(rows)
        self.assertEqual(m["rules_correct"], {"numerator": 3, "denominator": 5, "rate": 0.6})
        self.assertEqual(m["llm_answered"]["numerator"], 4)
        self.assertEqual(m["llm_correct"], {"numerator": 2, "denominator": 4, "rate": 0.5})
        self.assertEqual(m["agreement"], {"numerator": 2, "denominator": 4, "rate": 0.5})
        self.assertEqual(m["rules_errors_flagged"], {"numerator": 1, "denominator": 2, "rate": 0.5})
        self.assertEqual(m["flags_needed"], {"numerator": 1, "denominator": 2, "rate": 0.5})
        self.assertEqual(m["when_disagreeing"], {"total": 2, "llm_right": 1, "rules_right": 1, "neither": 0})
        self.assertEqual(m["llm_unavailable"]["numerator"], 1)
        self.assertEqual(m["by_language"]["th"]["llm_correct"]["rate"], 1.0)
        self.assertEqual(m["by_tag"]["injection"]["rules_correct"]["numerator"], 0)
        self.assertEqual(m["both_wrong"], ["d"])
        self.assertEqual(m["llm_wrong_rules_right"], ["c"])  # "e" gave no answer, so it is not a mistake
        self.assertEqual(m["tokens"], {"input": 500, "output": 50, "estimated": False})

    def test_empty_denominators_are_not_divided(self):
        m = ev.compute_metrics([row("x", "other", "other", None, status="failed")])
        self.assertIsNone(m["llm_correct"]["rate"])
        self.assertIn("–", ev._fmt(m["llm_correct"]))


class EndToEndEvalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = ev.evaluate(GOLDEN, limit=8)

    def test_real_workflow_runs_and_report_is_traceable(self):
        report = self.report
        self.assertEqual(len(report["cases"]), 8)
        self.assertEqual(report["metrics"]["jobs_completed"]["rate"], 1)
        provenance = report["provenance"]
        self.assertEqual(provenance["golden"]["sha256"], GOLDEN["sha256"])
        self.assertEqual(provenance["llm"]["provider"], "mock")
        self.assertEqual(len(provenance["prompt"]["sha256"]), 64)
        self.assertEqual(provenance["rules"], {"version": rule_version()})
        self.assertTrue(all(c["rule_version"] == rule_version() for c in report["cases"]))
        text = ev.summary_markdown(report)
        self.assertIn("AI จำลอง", text)
        self.assertIn("กฎเดิมจัดหมวดถูก", text)

    def test_summary_names_the_ai_mistakes_where_the_rules_were_right(self):
        self.assertNotIn("เคสที่ AI ผิดแต่กฎถูก", ev.summary_markdown(self.report))  # the mock makes none here
        report = json.loads(json.dumps(self.report))
        case = next(c for c in report["cases"] if c["llm_status"] == "ok" and c["rules_category"] == c["expected"])
        case["llm_category"] = "billing" if case["expected"] != "billing" else "upload"
        report["metrics"] = ev.compute_metrics(report["cases"])
        text = ev.summary_markdown(report)
        self.assertIn("### เคสที่ AI ผิดแต่กฎถูก", text)
        self.assertIn(f"- `{case['case_id']}` ควรเป็น **{case['expected']}** · กฎ: {case['rules_category']} · "
                      f"AI: {case['llm_category']}", text)

    def test_outcome_change_gate(self):
        self.assertTrue(ev.compare_reports(self.report, self.report)["accepted"])
        changed = json.loads(json.dumps(self.report))
        changed["cases"][0]["llm_category"] = "billing" if changed["cases"][0]["llm_category"] != "billing" else "other"
        result = ev.compare_reports(self.report, changed)
        self.assertFalse(result["accepted"])
        self.assertIn("SEMANTIC_REGRESSION", result["failure_reasons"])

    def test_command_line_writes_report_summary_and_gates(self):
        with tempfile.TemporaryDirectory() as folder:
            out, summary = Path(folder) / "report.json", Path(folder) / "summary.md"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(ev.main(["--limit", "4", "--out", str(out), "--summary", str(summary)]), 0)
            saved = json.loads(out.read_text("utf-8"))
            self.assertEqual(len(saved["cases"]), 4)
            self.assertIn("shadow mode", summary.read_text("utf-8"))
            saved["cases"][0]["llm_category"] = "nothing"
            out.write_text(json.dumps(saved), "utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(ev.main(["--limit", "4", "--compare-with", str(out)]), 3)


class EvalGateTests(unittest.TestCase):
    """Roadmap 5.2: every per-case answer is compared with the committed mock baseline."""

    @classmethod
    def setUpClass(cls):
        cls.full = ev.evaluate(GOLDEN, LLMConfig())  # all cases, always the offline mock AI

    def test_the_committed_baseline_matches_a_fresh_mock_run(self):
        changes = ev.answer_changes(ev.as_baseline(decode(BASELINE.read_bytes())), ev.baseline_view(self.full))
        self.assertEqual(changes, [], "Per-case answers differ from tests/baselines/shadow_eval_mock.json:\n"
                         + "\n".join(changes) + "\n" + UPDATE_HINT)

    def test_regenerating_the_baseline_gives_the_same_bytes(self):
        # So a regenerated file differs from the committed one only on the lines whose answers changed.
        view = ev.baseline_view(self.full)
        if ev.answer_changes(ev.as_baseline(decode(BASELINE.read_bytes())), view):
            self.skipTest("the answers differ; test_the_committed_baseline_matches_a_fresh_mock_run lists them")
        self.assertEqual(ev.baseline_json(view), BASELINE.read_text("utf-8"),
                         "Same answers, different text: the baseline was edited by hand. " + UPDATE_HINT)

    def test_each_kind_of_difference_is_named(self):
        before = ev.baseline_view(self.full)
        after = json.loads(json.dumps(before))
        first, second = after["cases"][0], after["cases"][1]
        first["rules_category"] = "billing" if first["rules_category"] != "billing" else "other"
        second["review_reasons"] = second["review_reasons"] + ["llm_low_confidence"]
        removed = after["cases"].pop(2)["case_id"]
        after["prompt"]["sha256"] = "0" * 64
        changes = ev.answer_changes(before, after)
        self.assertEqual(len(changes), 4, changes)
        self.assertEqual(changes[0], 'prompt sha256: "%s…" -> "000000000000…"' % before["prompt"]["sha256"][:12])
        self.assertIn(f"{removed}: in the baseline but not in this run", changes)
        self.assertTrue(any(line.startswith(f"{first['case_id']}: rules_category ") for line in changes), changes)
        self.assertTrue(any(line.startswith(f"{second['case_id']}: review_reasons ") for line in changes), changes)
        self.assertEqual(ev.answer_changes(before, before), [])

    def test_malformed_baselines_are_refused_and_reports_are_reduced(self):
        good = ev.baseline_view(self.full)
        for broken in ({"schema": "other"}, [], dict(good, extra=1), dict(good, cases=good["cases"] + good["cases"][:1]),
                       dict(good, cases=[{**good["cases"][0], "extra": 1}])):
            with self.assertRaises(ValueError):
                ev.as_baseline(broken)
        self.assertEqual(ev.as_baseline(self.full), good)  # a full report (--out) is accepted, reduced to answers

    def test_rules_identity_is_part_of_the_gate_even_when_answers_stay_the_same(self):
        before = ev.baseline_view(self.full)
        after = json.loads(json.dumps(before))
        after["rules"]["version"] = "changed-keyword-list"
        changes = ev.answer_changes(before, after)
        self.assertEqual(len(changes), 1)
        self.assertTrue(changes[0].startswith("rules version:"), changes)

    def test_command_line_writes_a_baseline_and_gates_on_it(self):
        with tempfile.TemporaryDirectory() as folder:
            baseline, summary = Path(folder) / "baseline.json", Path(folder) / "summary.md"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(ev.main(["--limit", "3", "--write-baseline", str(baseline)]), 0)
                self.assertEqual(ev.main(["--limit", "3", "--compare-with", str(baseline), "--summary", str(summary)]), 0)
            self.assertIn("(eval gate): ผ่าน", summary.read_text("utf-8"))
            document = json.loads(baseline.read_text("utf-8"))
            document["cases"][1]["llm_category"] = "nothing"
            baseline.write_text(json.dumps(document), "utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(ev.main(["--limit", "3", "--compare-with", str(baseline), "--summary", str(summary)]), 3)
            text = summary.read_text("utf-8")
            self.assertIn("ไม่ผ่าน (1 จุดต่างจากเดิม)", text)
            self.assertIn(f"{document['cases'][1]['case_id']}: llm_category", text)
            self.assertIn("--write-baseline", text)
            with self.assertRaises(FileNotFoundError):  # a missing baseline fails before any case runs
                ev.main(["--compare-with", str(Path(folder) / "missing.json")])


if __name__ == "__main__":
    unittest.main()
