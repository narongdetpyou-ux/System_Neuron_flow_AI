"""E2 arithmetic and evidence checks; never inspect or tune on the held-out set."""

import contextlib
import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from app.domains.case_triage.rules import classify_case, rule_version
from app.eval import rules_comparison as ev


def report():
    rows = []
    for case_id, summary, language, expected, llm in (
            ("demo_en", "Please reset my password", "en", "access", "access"),
            ("demo_th", "ฉันลืมรหัสผ่านของบัญชีทดสอบ", "th", "access", "access"),
            ("demo_other", "Hello there, thanks for the help", "en", "other", None)):
        new = classify_case({"summary": summary})
        rows.append({"case_id": case_id, "summary": summary, "language": language, "expected": expected,
                     "source_sha256": hashlib.sha256(summary.encode("utf-8")).hexdigest(),
                     "rules_category": new["category"], "rule_version": new["rule_version"],
                     "llm_status": "ok" if llm else "unavailable", "llm_category": llm,
                     "job_status": "SUCCEEDED"})
    return {"schema": "neuron-flow-shadow-eval-v1", "cases": rows,
            "provenance": {"golden": {"name": "synthetic_test_only", "sha256": "1" * 64, "cases": len(rows)},
                           "rules": {"version": rule_version()}, "llm": {"provider": "mock", "model": "mock"},
                           "prompt": {"id": "test", "sha256": "2" * 64}, "git_sha": "test"}}


class RulesComparisonTests(unittest.TestCase):
    def test_same_ai_answers_compare_rules_and_keep_language_counts(self):
        source = report()
        before = copy.deepcopy(source)
        result = ev.compare_report(source)
        self.assertEqual(source, before)
        self.assertEqual(result["rules_v1"]["metrics"]["rules_correct"]["numerator"], 2)
        self.assertEqual(result["rules_v2"]["metrics"]["rules_correct"]["numerator"], 3)
        self.assertEqual(result["rules_v1"]["metrics"]["elevated_review"]["numerator"], 1)
        self.assertEqual(result["rules_v2"]["metrics"]["elevated_review"]["numerator"], 0)
        self.assertEqual(result["improvements"], ["demo_th"])
        self.assertEqual(result["regressions"], [])
        self.assertEqual(result["rules_v2"]["metrics"]["by_language"]["th"]["numerator"], 1)
        self.assertEqual([(r["llm_status"], r["llm_category"]) for r in result["cases"]],
                         [(r["llm_status"], r["llm_category"]) for r in source["cases"]])

    def test_both_wrong_excludes_an_unavailable_ai_and_zero_denominators(self):
        rows = [{"case_id": "miss", "expected": "billing", "rules_v1": "other", "language": "en",
                 "llm_status": "unavailable", "llm_category": None, "job_status": "SUCCEEDED"}]
        m = ev._metrics(rows, "rules_v1")
        self.assertEqual(m["both_wrong"], [])
        self.assertEqual(m["rule_wrong_ai_unavailable"], ["miss"])
        self.assertIsNone(m["llm_correct"]["rate"])
        rows += [{"case_id": "both", "expected": "billing", "rules_v1": "access", "language": "en",
                  "llm_status": "ok", "llm_category": "upload", "job_status": "SUCCEEDED"}]
        m = ev._metrics(rows, "rules_v1")
        self.assertEqual(m["both_wrong"], ["both"])
        self.assertEqual(m["rules_errors_flagged"], {"numerator": 1, "denominator": 2, "rate": .5})

    def test_stale_version_source_duplicate_and_replayed_output_are_refused(self):
        changes = [lambda d: d.update(schema="other"),
                   lambda d: d["provenance"]["rules"].update(version="old"),
                   lambda d: d["provenance"].pop("llm"),
                   lambda d: d["provenance"]["llm"].update(model=""),
                   lambda d: d["provenance"]["golden"].update(sha256="not-a-sha"),
                   lambda d: d["provenance"]["prompt"].update(sha256="not-a-sha"),
                   lambda d: d["provenance"]["golden"].update(cases=100),
                   lambda d: d["cases"][0].update(summary="changed source"),
                   lambda d: d["cases"][0].update(rules_category="other"),
                   lambda d: d["cases"][0].update(rule_version="old"),
                   lambda d: d["cases"][0].update(llm_category="unknown"),
                   lambda d: d["cases"].__setitem__(1, d["cases"][0])]
        for change in changes:
            broken = report()
            change(broken)
            with self.assertRaises(ValueError):
                ev.compare_report(broken)

    def test_failed_job_cannot_claim_to_have_raised_a_case_for_review(self):
        source = report()
        source["cases"][1]["job_status"] = "FAILED"
        result = ev.compare_report(source)
        self.assertEqual(result["rules_v1"]["metrics"]["elevated_review"]["numerator"], 0)
        self.assertEqual(result["rules_v1"]["metrics"]["jobs_completed"]["numerator"], 2)
        self.assertEqual(len(result["rules_v1"]["source_sha256"]), 64)

    def test_summary_and_command_line_keep_versions_metrics_and_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            source, out, summary = [Path(folder) / p for p in ("report.json", "comparison.json", "summary.md")]
            source.write_text(json.dumps(report()), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(ev.main(["--report", str(source), "--out", str(out), "--summary", str(summary)]), 0)
            document = json.loads(out.read_text("utf-8"))
            self.assertEqual(document["schema"], ev.SCHEMA)
            self.assertEqual(len(document["sets"]), 1)
            text = summary.read_text("utf-8")
            for value in ("mock/mock", rule_version(), "demo_th", "3/3", "2/3", "AI ไม่ตอบ"):
                self.assertIn(value, text)


if __name__ == "__main__":
    unittest.main()
