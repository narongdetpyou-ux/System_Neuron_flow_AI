"""Shadow-mode scorecard: case file checks, metrics arithmetic, outcome-change gate, CLI."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from app.domains.case_triage import build_shadow_workflow
from app.eval import triage_shadow_eval as ev

GOLDEN = ev.load_golden()


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
        text = ev.summary_markdown(report)
        self.assertIn("AI จำลอง", text)
        self.assertIn("กฎเดิมจัดหมวดถูก", text)

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


if __name__ == "__main__":
    unittest.main()
