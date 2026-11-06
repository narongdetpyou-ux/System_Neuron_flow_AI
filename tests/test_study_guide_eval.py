"""The study guide's scorecard (roadmap 3.3): the request set, the arithmetic, the promises, the eval gate, the CLI."""

import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from neuron_flow.model import decode

from app.domains.study_guide import load_library
from app.domains.study_guide.library import OUT_OF_SCOPE
from app.eval import study_guide_eval as ev

LIBRARY = load_library()
GOLDEN = ev.load_golden()
BASELINE = Path(__file__).resolve().parent / "baselines" / "study_guide_eval_mock.json"
UPDATE_HINT = ("If the change is on purpose, regenerate the baseline in the same pull request with\n"
               "  python -m app.eval.study_guide_eval --write-baseline tests/baselines/study_guide_eval_mock.json\n"
               "and explain why in the PR description (roadmap 3.3, 5.2).")


def row(case_id, expected, detected, *, language="en", tags=("plain",), status="ok", resources=("r1",),
        outside=0, answer="guide"):
    return {"case_id": case_id, "language": language, "tags": list(tags), "message": f"message {case_id}",
            "source_sha256": case_id * 4, "expected": list(expected), "job_status": "SUCCEEDED",
            "detect_status": status, "detect_reason": None if status == "ok" else "provider_unavailable",
            "detected_topic": detected if status == "ok" else None, "confidence": "high" if status == "ok" else None,
            "detected_language": language if status == "ok" else None, "detect_attempts": 1,
            "detect_latency_ms": 5.0 if status == "ok" else None, "explain_status": "ok", "explain_reason": None,
            "answer_status": answer, "explanation_source": "ai", "resource_ids": list(resources),
            "links_outside_library": outside, "confirm_asked": status == "ok", "input_tokens": 10,
            "output_tokens": 2, "usage_estimated": True}


class RequestSetTests(unittest.TestCase):
    def test_the_request_set_covers_what_the_roadmap_asks_for(self):
        cases = GOLDEN["cases"]
        self.assertGreaterEqual(len(cases), 60)
        self.assertEqual({c["language"] for c in cases}, {"th", "en"})
        counts = {tag: sum(tag in c["tags"] for c in cases) for tag in ev.TAGS}
        for tag, minimum in (("metaphor", 15), ("paraphrase", 10), ("out_of_scope", 15), ("injection", 5)):
            self.assertGreaterEqual(counts[tag], minimum, tag)
        for topic in LIBRARY.topics:  # every topic is asked about in both languages
            asked = [c for c in cases if topic.id in c["expected"]]
            self.assertEqual({c["language"] for c in asked}, {"th", "en"}, topic.id)
        owner = [c for c in cases if "owner_example" in c["tags"]]
        self.assertEqual([c["message"] for c in owner], ["อยากให้ระบบเป็นเหมือนบรรณารักษ์ที่รู้ใจ"])
        self.assertEqual(len({c["case_id"] for c in cases}), len(cases))

    def test_no_request_is_a_catalog_example(self):
        examples = {" ".join(p.casefold().split()) for t in LIBRARY.topics for p in t.examples_th + t.examples_en}
        for case in GOLDEN["cases"]:
            self.assertNotIn(" ".join(case["message"].casefold().split()), examples, case["case_id"])

    def test_bad_request_files_are_refused(self):
        good = json.loads(ev.DEFAULT_GOLDEN.read_text("utf-8"))
        first = good["cases"][0]
        example = LIBRARY.topics[0].examples_th[0]
        broken = {
            "schema": dict(good, schema="other"),
            "other library": dict(good, library="v2"),
            "extra key": dict(good, owner="me"),
            "no cases": dict(good, cases=[]),
            "repeated id": dict(good, cases=[first, first]),
            "unknown topic": dict(good, cases=[{**first, "expected": ["cooking"]}]),
            "out of scope with a topic": dict(good, cases=[{**first, "expected": [OUT_OF_SCOPE, "ai_basics"]}]),
            "tag without the label": dict(good, cases=[{**first, "tags": ["out_of_scope"]}]),
            "unknown tag": dict(good, cases=[{**first, "tags": ["tricky"]}]),
            "language mismatch": dict(good, cases=[{**first, "language": "en"}]),
            "too short": dict(good, cases=[{**first, "message": "AI"}]),
            "catalog example": dict(good, cases=[{**first, "message": example}]),
            "bad id": dict(good, cases=[{**first, "case_id": "th-1"}]),
        }
        with tempfile.TemporaryDirectory() as folder:
            for name, document in broken.items():
                with self.subTest(name):
                    path = Path(folder) / "bad.json"
                    path.write_text(json.dumps(document, ensure_ascii=False), "utf-8")
                    with self.assertRaises(ValueError):
                        ev.load_golden(path)


class MetricsTests(unittest.TestCase):
    def test_topic_accuracy_and_out_of_scope_precision_and_recall(self):
        rows = [row("A", ["ai_agents"], "ai_agents"),                      # right topic
                row("B", ["ai_agents", "system_design"], "system_design"),  # one of two accepted topics
                row("C", ["ai_agents"], "plain_language"),                 # wrong topic
                row("D", ["ai_agents"], OUT_OF_SCOPE, answer="out_of_scope", resources=()),  # turned away
                row("E", [OUT_OF_SCOPE], OUT_OF_SCOPE, answer="out_of_scope", resources=(), tags=("out_of_scope",)),
                row("F", [OUT_OF_SCOPE], "ai_basics", tags=("out_of_scope",)),  # stretched to fit
                row("G", ["ai_agents"], None, status="unavailable", answer="not_understood", resources=())]
        m = ev.compute_metrics(rows)
        self.assertEqual(m["detection_answered"], {"numerator": 6, "denominator": 7, "rate": 0.8571})
        self.assertEqual((m["topic_correct"]["numerator"], m["topic_correct"]["denominator"]), (2, 4))
        self.assertEqual((m["correct"]["numerator"], m["correct"]["denominator"]), (3, 6))
        self.assertEqual((m["out_of_scope_precision"]["numerator"], m["out_of_scope_precision"]["denominator"]), (1, 2))
        self.assertEqual((m["out_of_scope_recall"]["numerator"], m["out_of_scope_recall"]["denominator"]), (1, 2))
        self.assertEqual((m["in_scope_turned_away"]["numerator"], m["in_scope_turned_away"]["denominator"]), (1, 4))
        self.assertEqual([item["case_id"] for item in m["mistakes"]], ["C", "D", "F", "G"])
        self.assertEqual(m["mistakes"][-1]["got"], "detection_unavailable")
        self.assertTrue(m["promises_kept"])

    def test_a_broken_promise_is_reported(self):
        outside = ev.compute_metrics([row("A", ["ai_agents"], "ai_agents", outside=1)])
        self.assertEqual(outside["links_outside_library"], {"count": 1, "links_shown": 1})
        self.assertFalse(outside["promises_kept"])
        six = ev.compute_metrics([row("A", ["ai_agents"], "ai_agents", resources=[f"r{n}" for n in range(6)])])
        self.assertEqual(six["answers_over_five"]["cases"], ["A"])
        self.assertFalse(six["promises_kept"])
        unfinished = dict(row("A", ["ai_agents"], "ai_agents"), job_status="FAILED")
        self.assertFalse(ev.compute_metrics([unfinished])["promises_kept"])

    def test_empty_denominators_stay_empty(self):
        m = ev.compute_metrics([row("E", [OUT_OF_SCOPE], OUT_OF_SCOPE, answer="out_of_scope", resources=(),
                                    tags=("out_of_scope",))])
        self.assertEqual(m["topic_correct"], {"numerator": 0, "denominator": 0, "rate": None})


class MockRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = ev.evaluate(GOLDEN)

    def test_every_promise_holds_on_every_answer(self):
        m = self.report["metrics"]
        self.assertEqual(m["jobs_completed"]["numerator"], len(GOLDEN["cases"]))
        self.assertEqual(m["links_outside_library"]["count"], 0)
        self.assertEqual(m["answers_over_five"]["count"], 0)
        self.assertEqual(m["injection"]["links_outside_library"], 0)
        self.assertTrue(m["promises_kept"])
        for r in self.report["cases"]:  # the attack's link appears in the request itself, and nowhere else
            self.assertNotIn("evil.example", json.dumps({k: v for k, v in r.items() if k != "message"}))
            for resource_id in r["resource_ids"]:
                self.assertIn(resource_id, {res.id for res in LIBRARY.resources})

    def test_the_report_and_summary_are_honest_about_the_mock(self):
        text = ev.summary_markdown(self.report)
        self.assertIn("AI จำลอง", text)
        self.assertIn("ลิงก์นอกคลัง", text)
        self.assertIn("เป็นจริงทุกคำตอบ", text)
        self.assertEqual(self.report["provenance"]["library"], LIBRARY.tag)

    def test_the_committed_baseline_matches_a_fresh_mock_run(self):
        reference = ev.as_baseline(decode(BASELINE.read_bytes()))
        changes = ev.answer_changes(reference, ev.baseline_view(self.report))
        self.assertEqual(changes, [], "\n".join(["Per-request answers changed:", *changes, UPDATE_HINT]))
        self.assertEqual(ev.baseline_json(reference), BASELINE.read_text("utf-8"),
                         "the baseline file is not in the stable one-request-per-line format")

    def test_the_gate_names_every_kind_of_change(self):
        reference = ev.baseline_view(self.report)
        changed = copy.deepcopy(reference)
        changed["cases"][0]["detected_topic"] = "system_design"
        changed["cases"][1]["resource_ids"] = ["thai_mooc"]
        changed["library"]["tag"] = "v1@sha256:" + "0" * 64
        changed["prompts"]["detect_sha256"] = "1" * 64
        changed["cases"].pop()
        lines = ev.answer_changes(reference, changed)
        text = "\n".join(lines)
        for expected in ("detected_topic", "resource_ids", "library tag", "prompt detect_sha256",
                         "in the baseline but not in this run"):
            self.assertIn(expected, text)
        self.assertIn("app.eval.study_guide_eval --write-baseline", ev.gate_markdown(lines, "b.json", 3))

    def test_malformed_baselines_are_refused(self):
        good = decode(BASELINE.read_bytes())
        for bad in (dict(good, schema="other"), dict(good, cases=good["cases"][:1] * 2),
                    {k: v for k, v in good.items() if k != "library"}):
            with self.assertRaises(ValueError):
                ev.as_baseline(bad)
        self.assertEqual(ev.as_baseline(self.report)["schema"], ev.BASELINE_SCHEMA)  # a full report works too


class CommandLineTests(unittest.TestCase):
    def run_main(self, *args):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = ev.main(list(args))
        return code, out.getvalue()

    def test_compare_passes_fails_and_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            summary, baseline = Path(folder, "summary.md"), Path(folder, "baseline.json")
            code, _ = self.run_main("--limit", "4", "--write-baseline", str(baseline), "--summary", str(summary))
            self.assertEqual(code, 0)
            code, _ = self.run_main("--limit", "4", "--compare-with", str(baseline))
            self.assertEqual(code, 0)
            document = json.loads(baseline.read_text("utf-8"))
            document["cases"][0]["detected_topic"] = "system_design"
            baseline.write_text(json.dumps(document), "utf-8")
            code, out = self.run_main("--limit", "4", "--compare-with", str(baseline))
            self.assertEqual(code, 3)
            self.assertIn("ไม่ผ่าน", out)
            self.assertIn("ผลวัดผู้ช่วยแนะนำแหล่งเรียน", summary.read_text("utf-8"))

    def test_a_broken_promise_fails_the_run(self):
        broken = {**ev.compute_metrics([row("A", ["ai_agents"], "ai_agents", outside=1)])}
        real = ev.compute_metrics
        with mock.patch.object(ev, "compute_metrics", side_effect=lambda rows: {**real(rows), **{
                "links_outside_library": broken["links_outside_library"], "promises_kept": False}}):
            code, out = self.run_main("--limit", "2")
        self.assertEqual(code, 1)
        self.assertIn("ไม่เป็นจริง", out)


if __name__ == "__main__":
    unittest.main()
