"""The auto-approve simulation (app/eval/autosend_sim.py, ADR-031) and the hard auto-send case set.

The simulation is a replay on saved answers. These tests check its arithmetic, that it refuses reports it
cannot read, that it fails when a real job did not wait for a person, and that the service can never import
it: the button exists on paper only (rule 4).
"""

import ast
import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from app.eval import autosend_sim as sim
from app.eval import triage_shadow_eval
from app.llm import LLMConfig, mask

ROOT = Path(__file__).resolve().parent.parent
HARD_SET = ROOT / "app" / "eval" / "golden" / "case_triage_autosend_hard_v1.json"


def row(case_id, expected, rules, llm, confidence="high", *, tags=(), language="en", masked=None,
        status="ok", decision="PENDING_HUMAN_REVIEW", job_status="SUCCEEDED"):
    ok = status == "ok"
    reasons = []
    if rules == "other":
        reasons.append("rules_no_keyword_match")
    if ok and llm != rules:
        reasons.insert(0, "rules_llm_disagree")
    if ok and confidence == "low":
        reasons.append("llm_low_confidence")
    if not ok:
        reasons.append("llm_unavailable")
    return {"case_id": case_id, "language": language, "tags": list(tags), "summary": f"case {case_id}",
            "expected": expected, "job_status": job_status, "rules_category": rules, "llm_status": status,
            "llm_category": llm if ok else None, "llm_confidence": confidence if ok else None,
            "agreement": ("agree" if llm == rules else "disagree") if ok else "llm_unavailable",
            "review_reasons": reasons, "masked": masked or {}, "decision": decision}


def report(rows, name="unit_set"):
    return {"schema": "neuron-flow-shadow-eval-v1", "cases": rows,
            "provenance": {"golden": {"name": name, "sha256": "0" * 64, "cases": len(rows), "label_scope": "unit"},
                           "llm": {"provider": "mock", "model": "mock-keyword-1"},
                           "prompt": {"id": "triage_classify_v1", "sha256": "1" * 64},
                           "rules": {"version": "keywords-v2:test"}, "git_sha": "abc"}}


class DecideTests(unittest.TestCase):
    def test_the_ladder(self):
        agree_high = row("A", "access", "access", "access")
        ai_only = row("B", "billing", "other", "billing")
        agree_medium = row("C", "upload", "upload", "upload", "medium")
        agree_other = row("D", "other", "other", "other")
        with_pii = row("E", "billing", "billing", "billing", masked={"phone": 1})
        unavailable = row("F", "access", "access", None, status="unavailable")
        expected = {"ai_high": ["access", "billing", None, "other", "billing", None],
                    "agree": ["access", None, "upload", "other", "billing", None],
                    "agree_high": ["access", None, None, "other", "billing", None],
                    "screened": ["access", None, None, "other", "billing", None],  # no row has a signal
                    # strict: no review reason at all, so "other" by rules (no keyword) and masked data hold.
                    "strict": ["access", None, None, None, None, None]}
        for policy, decisions in expected.items():
            self.assertEqual([sim.would_send(policy, r) for r in (agree_high, ai_only, agree_medium, agree_other,
                                                             with_pii, unavailable)], decisions, policy)

    def test_a_failed_job_is_never_sent(self):
        failed = row("A", "access", "access", "access", job_status="FAILED", decision=None)
        self.assertEqual({sim.would_send(p, failed) for p in sim.POLICY_IDS}, {None})

    def test_unknown_policy(self):
        with self.assertRaises(ValueError):
            sim.would_send("everything", row("A", "access", "access", "access"))


class ArithmeticTests(unittest.TestCase):
    def test_wilson_upper_bound(self):
        self.assertIsNone(sim.wilson_upper(0, 0))
        self.assertAlmostEqual(sim.wilson_upper(0, 10), 0.2775, places=3)
        self.assertAlmostEqual(sim.wilson_upper(0, 100), 0.037, places=3)  # "no mistake in 100" is not 0%
        self.assertEqual(sim.wilson_upper(5, 5), 1.0)
        self.assertGreater(sim.wilson_upper(1, 20), 1 / 20)

    def test_category_scores_keep_counts_and_treat_no_answer_as_a_miss(self):
        from app.eval.common import category_scores
        rows = [{"expected": "access", "p": "access"}, {"expected": "access", "p": "billing"},
                {"expected": "billing", "p": "billing"}, {"expected": "other", "p": None}]
        scores = category_scores(rows, "p", ("access", "upload", "billing", "other"))
        self.assertEqual(scores["per_category"]["access"],
                         {"support": 2, "predicted": 1, "correct": 1, "precision": 1.0, "recall": 0.5, "f1": 0.6667})
        self.assertEqual(scores["per_category"]["billing"]["precision"], 0.5)
        self.assertEqual(scores["per_category"]["other"]["f1"], 0.0)  # never answered: recall 0
        self.assertIsNone(scores["per_category"]["upload"]["f1"])  # absent and never predicted: left out
        self.assertEqual(scores["categories_in_macro"], 3)
        self.assertAlmostEqual(scores["macro_f1"], (0.6667 + 0.6667 + 0.0) / 3, places=3)

    def test_policy_metrics_count_wrong_unsafe_needs_person_and_injection(self):
        rows = [row("OK", "access", "access", "access"),
                row("WRONG", "other", "billing", "billing"),
                row("PERSON", "billing", "billing", "billing", tags=["security", "needs_person"]),
                row("INJ", "upload", "upload", "upload", tags=["routing_injection", "needs_person"]),
                row("HELD", "access", "other", "access", "medium", tags=["needs_person"], language="th")]
        m = sim.policy_metrics(rows, "agree_high")
        self.assertEqual(m["sent"], {"numerator": 4, "denominator": 5, "rate": 0.8})
        self.assertEqual((m["sent_wrong"]["numerator"], m["sent_wrong"]["denominator"]), (1, 4))
        self.assertEqual(m["sent_unsafe"]["numerator"], 3)
        self.assertEqual((m["needs_person_sent"]["numerator"], m["needs_person_sent"]["denominator"]), (2, 3))
        self.assertEqual((m["injection_sent"]["numerator"], m["injection_sent"]["denominator"]), (1, 1))
        self.assertEqual(m["safe_sends"]["numerator"], 1)
        self.assertEqual([c["case_id"] for c in m["unsafe_cases"]], ["WRONG", "PERSON", "INJ"])
        self.assertEqual(m["by_language"]["th"]["sent"]["numerator"], 0)

    def test_pairs_and_injected_copies(self):
        rows = [row("MAS-TH-1", "other", "other", "billing", language="th", tags=["pair:m1"]),
                row("MAS-EN-1", "other", "other", "other", tags=["pair:m1"]),
                row("MAS-TH-2", "other", "other", "other", language="th", tags=["pair:m2"]),
                row("MAS-EN-2", "other", "other", "other", tags=["pair:m2"])]
        pairs = sim.pair_metrics(rows)
        self.assertEqual(pairs["pairs"], 2)
        self.assertEqual(pairs["ai_same_category"]["numerator"], 1)
        self.assertEqual(pairs["same_send"]["agree"]["numerator"], 1)
        self.assertEqual(pairs["ai_differs"], [{"pair": "m1", "th": "billing", "en": "other"}])
        base = row("AS-EN-CLR-01", "access", "access", "access")
        attacked = [row("BIPIA-001", "access", "access", "other", tags=["open_injection", "base:AS-EN-CLR-01"]),
                    row("BIPIA-002", "access", "access", None, status="unavailable",
                        tags=["open_injection", "base:AS-EN-CLR-01"]),
                    row("BIPIA-003", "access", "access", "access", tags=["open_injection", "base:MISSING"])]
        result = sim.injection_metrics(attacked, {"AS-EN-CLR-01": base})
        self.assertEqual(result["base_found"]["numerator"], 2)
        self.assertEqual(result["ai_lost_answer"], {"numerator": 1, "denominator": 2, "rate": 0.5})
        self.assertEqual(result["ai_category_flipped"]["numerator"], 1)
        self.assertIsNone(sim.pair_metrics([base]))


class ReportTests(unittest.TestCase):
    def test_refuses_anything_but_a_complete_report(self):
        good = report([row("A", "access", "access", "access")])
        sim.check_report(good)
        with self.assertRaises(ValueError):
            sim.check_report({"schema": "neuron-flow-shadow-eval-baseline-v1", "cases": []})
        old = report([{k: v for k, v in row("A", "access", "access", "access").items() if k != "masked"}])
        with self.assertRaisesRegex(ValueError, "masked"):
            sim.check_report(old)
        duplicate = report([row("A", "access", "access", "access"), row("A", "access", "access", "access")])
        with self.assertRaises(ValueError):
            sim.check_report(duplicate)

    def test_main_fails_when_a_real_job_did_not_wait_for_a_person(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            path = Path(folder) / "r.json"
            path.write_text(json.dumps(report([row("A", "access", "access", "access")])), encoding="utf-8")
            self.assertEqual(sim.main(["--report", str(path), "--out", str(Path(folder) / "o.json")]), 0)
            bad = report([row("A", "access", "access", "access", decision="APPROVED")])
            path.write_text(json.dumps(bad), encoding="utf-8")
            self.assertEqual(sim.main(["--report", str(path)]), 1)

    def test_end_to_end_on_the_hard_set_with_the_mock(self):
        golden = triage_shadow_eval.load_golden(HARD_SET)
        result = triage_shadow_eval.evaluate(golden, LLMConfig.from_env({}), limit=6)
        simulated = sim.simulate([result])
        self.assertEqual(simulated["total"]["real_system"]["waiting_for_person"]["numerator"], 6)
        self.assertEqual(simulated["total"]["real_system"]["decided_without_person"], 0)
        text = sim.summary_markdown(simulated)
        self.assertIn("ระบบจริงไม่มีปุ่มนี้", text)
        self.assertIn("6/6 (100%)", text)


class NotWiredTests(unittest.TestCase):
    """The button exists on paper only: no service code may import or name the simulation (rule 4)."""

    def test_no_module_outside_app_eval_imports_the_simulation(self):
        offenders = []
        for path in (ROOT / "app").rglob("*.py"):
            if path.parent.name == "eval":
                continue
            text = path.read_text(encoding="utf-8")
            if "autosend" in text or "auto_send" in text:
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_the_simulation_imports_no_runtime_service_or_network_code(self):
        tree = ast.parse((ROOT / "app" / "eval" / "autosend_sim.py").read_text(encoding="utf-8"))
        names = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        names += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        forbidden = [n for n in names if re.match(r"(app\.(services|api|web|exchange|persistence|llm)|"
                                                  r"urllib|http|socket|subprocess|neuron_flow\.runtime)", n)]
        self.assertEqual(forbidden, [])


class HardSetTests(unittest.TestCase):
    def setUp(self):
        self.cases = triage_shadow_eval.load_golden(HARD_SET)["cases"]

    def test_shape(self):
        self.assertEqual(len(self.cases), 128)
        self.assertEqual(sum(c["language"] == "th" for c in self.cases), 64)
        self.assertEqual(sum("clear" in c["tags"] for c in self.cases), 20)
        ids = [c["case_id"] for c in self.cases]
        self.assertTrue(all(re.fullmatch(r"AS-(EN|TH)-[A-Z]{3}-\d{2}", i) for i in ids))

    def test_every_needs_person_case_says_why(self):
        reasons = {"routing_injection", "security", "legal_privacy", "safety"}
        for case in self.cases:
            if "needs_person" in case["tags"]:
                self.assertTrue(reasons & set(case["tags"]), case["case_id"])
            if reasons & set(case["tags"]):
                self.assertIn("needs_person", case["tags"], case["case_id"])
        self.assertEqual(sum("needs_person" in c["tags"] for c in self.cases), 38)

    def test_personal_data_is_invented_and_masked(self):
        for case in self.cases:
            for address in re.findall(r"[\w.]+@[\w.]+", case["summary"]):
                self.assertTrue(address.endswith("@example.com"), case["case_id"])
            for phone in re.findall(r"\d{3}-\d{3}-\d{4}", case["summary"]):
                self.assertIn("-555-", phone, case["case_id"])
            if "personal_data" in case["tags"]:
                self.assertTrue(mask(case["summary"]).counts, case["case_id"])


if __name__ == "__main__":
    unittest.main()
