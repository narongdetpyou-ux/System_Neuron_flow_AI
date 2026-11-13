"""The local model lane's own tools (ADR-026, ADR-034), against ``tests/fake_llama_server.py``, so CI tests them without a
model file:

* ``tests/local_model_e2e.py``: the real service with the ``local`` provider passes every check against a well-behaved
  server, keeps the case waiting for a person through a timeout, a server that does not answer and the server's faults,
  masks the phone number before it reaches the model, and fails when the server serves another model or another file;
  its contract check catches a broken proposal; the service it starts gets no secret;
* ``.github/scripts/local_model_lane.py``: one model from start to stop, with the load time, the first answer, the
  scorecard, memory and speed, and a server that does not start;
* ``tests/local_model_compare.py``: the figures and the case-by-case differences, a set that is not comparable, and the
  figures without cases found in the training data;
* ``tests/training_overlap.py``: a case inside a JSON-escaped prompt, a lightly edited case, and a report that never
  shows the training text.
"""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import shlex
import sys
import tempfile
import unittest
from pathlib import Path

from tests import local_model_compare, local_model_e2e, training_overlap
from tests.fake_llama_server import FakeLlamaServer

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("local_model_lane", ROOT / ".github" / "scripts" / "local_model_lane.py")
lane = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lane)
SAVED = ROOT / "docs" / "evidence" / "2026-11-11-attention-raw"
PHONE = "089-555-0143"  # the synthetic phone number in AS-TH-PII-01


def model_file(directory):
    path = Path(directory) / "model.gguf"
    path.write_bytes(b"GGUF" + bytes(range(256)) * 16)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return path, digest, f"fake-model:{digest[:12]}"


def quiet(function, *args):
    with contextlib.redirect_stdout(io.StringIO()):
        return function(*args)


class EndToEndTests(unittest.TestCase):
    def test_every_promise_holds_against_a_well_behaved_server(self):
        with tempfile.TemporaryDirectory() as work:
            path, digest, model_id = model_file(work)
            out = Path(work) / "e2e.json"
            with FakeLlamaServer(alias=model_id, model_path=str(path)) as fake:
                code = quiet(local_model_e2e.main, [
                    "--llm-base-url", fake.base_url + "/v1", "--model-id", model_id, "--model-file", str(path),
                    "--model-sha256", digest, "--cases", "quick", "--phases", "service,failures,faults",
                    "--fake-control", "--faults", "invalid_json,http_503,content_filter", "--job-timeout-s", "60",
                    "--json", str(out)])
                sent = json.dumps([r["body"] for r in fake.chat_requests()], ensure_ascii=False)
                headers = [r["headers"] for r in fake.chat_requests()]
            document = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(code, 0, [c for c in document["checks"] if not c["ok"]])
        self.assertEqual(document["failed"], 0)
        self.assertEqual([r["status"] for r in document["cases"]], ["REVIEW_REQUIRED"] * 4)
        ids = {check["id"] for check in document["checks"]}
        for wanted in ("status_ai", "server_model_id", "server_model_file", "server_model_sha256", "inbox",
                       "decision_0", "decision_0_repeat", "decision_1", "decision_2", "stale_version",
                       "masked_before_ai", "duplicate"):
            self.assertIn(wanted, ids)
        self.assertTrue(any(i.endswith(":apply") for i in ids))
        self.assertTrue(any(i.endswith(":receipt") for i in ids))
        scenarios = {row["scenario"]: (row["ai_status"], row["ai_reason"], row["attempt"]) for row in document["scenarios"]}
        self.assertEqual(scenarios, {"timeout": ("unavailable", "provider_unavailable", 2),
                                     "unreachable": ("unavailable", "provider_unavailable", 2),
                                     "invalid_json": ("unavailable", "invalid_model_output", 2),
                                     "http_503": ("ok", None, 2),
                                     "content_filter": ("unavailable", "model_declined", 1)})
        self.assertNotIn(PHONE, sent)  # masked before the AI call
        self.assertIn("[PHONE]", sent)
        self.assertFalse(any("authorization" in h for h in headers))  # no key is needed or sent on this machine

    def test_another_model_or_another_file_fails_the_check(self):
        with tempfile.TemporaryDirectory() as work:
            path, digest, model_id = model_file(work)
            other = Path(work) / "other.gguf"
            other.write_bytes(b"not the pinned bytes")
            out = Path(work) / "e2e.json"
            with FakeLlamaServer(alias="some-other-model:0123456789ab", model_path=str(other)) as fake:
                code = quiet(local_model_e2e.main, [
                    "--llm-base-url", fake.base_url + "/v1", "--model-id", model_id, "--model-file", str(other),
                    "--model-sha256", digest, "--cases", "quick", "--phases", "service", "--json", str(out)])
            failed = {c["id"] for c in json.loads(out.read_text(encoding="utf-8"))["checks"] if not c["ok"]}
        self.assertEqual(code, 1)
        self.assertEqual(failed, {"server_model_id", "server_model_sha256"})

    def test_the_contract_check_catches_a_broken_proposal(self):
        good = {"decision": "PENDING_HUMAN_REVIEW", "review_required": True, "mode": "shadow",
                "suggestion_source": "rules:keywords-v2:abc", "suggested_category": "access",
                "suggested_queue": "access_review", "agreement": "disagree", "review_priority": "elevated",
                "review_reasons": ["ai_flag_security", "rules_llm_disagree"],
                "second_opinion": {"status": "ok", "category": "billing", "attention": "security", "confidence": "high"}}
        self.assertEqual(local_model_e2e.proposal_problems(good), [])
        broken = {
            "not pending a person": {"decision": "APPROVED"},
            "priority does not follow": {"review_priority": "normal"},
            "attention flag": {"review_reasons": ["rules_llm_disagree"]},
            "disagreement reason": {"review_reasons": ["ai_flag_security"]},
            "outside the answer schema": {"second_opinion": {**good["second_opinion"], "attention": "urgent"}},
            "not the rules'": {"suggestion_source": "ai:local"},
            "category or queue": {"suggested_queue": "billing_review"},
            "no known reason": {"second_opinion": {"status": "unavailable", "reason": "tired"},
                                "agreement": "llm_unavailable", "review_reasons": ["llm_unavailable"],
                                "review_priority": "normal"},
        }
        for problem, change in broken.items():
            found = "; ".join(local_model_e2e.proposal_problems({**good, **change}))
            self.assertIn(problem, found, problem)

    def test_the_service_it_starts_gets_no_secret(self):
        env = local_model_e2e.service_environment(
            {"PATH": "/bin", "HOME": "/h", "NF_MODEL_URL": "u", "NF_MODEL_TOKEN": "t", "TYPHOON_API_KEY": "k",
             "GITHUB_TOKEN": "g", "SENTRY_DSN": "d", "NEURON_FLOW_LLM_PROVIDER": "typhoon", "PORT": "1"},
            NEURON_FLOW_LLM_PROVIDER="local", PORT=8001)
        self.assertEqual(env, {"PATH": "/bin", "HOME": "/h", "NEURON_FLOW_LLM_PROVIDER": "local", "PORT": "8001"})


class LaneTests(unittest.TestCase):
    def test_one_model_from_start_to_stop(self):
        with tempfile.TemporaryDirectory() as work:
            path, digest, model_id = model_file(work)
            out, summary = Path(work) / "lane", Path(work) / "summary.md"
            server = f"{shlex.quote(sys.executable)} tests/fake_llama_server.py --fake-delay-s 0.2 --fake-loading-s 0.6"
            with patch_environ({"NF_MODEL_URL": "https://secret.example/model", "TYPHOON_API_KEY": "k"}):
                code = quiet(lane.main, ["--server-cmd", server, "--model-path", str(path), "--model-id", model_id,
                                         "--model-sha256", digest, "--port", str(local_model_e2e.free_port()),
                                         "--triage-sets", "synthetic", "--limit", "2", "--e2e", "none",
                                         "--out-dir", str(out), "--summary", str(summary), "--quiet"])
            record = json.loads((out / "lane-fake-model.json").read_text(encoding="utf-8"))
            report = json.loads((out / "shadow-fake-model-synthetic.json").read_text(encoding="utf-8"))
            text = summary.read_text(encoding="utf-8")
        self.assertEqual(code, 0, record["steps"])
        self.assertGreaterEqual(record["load_s"], 0.5)  # waited while the server answered 503
        self.assertIsNotNone(record["first_answer"]["answer"])
        self.assertGreaterEqual(record["first_answer"]["ms"], 200)
        self.assertEqual([step["step"] for step in record["steps"]], ["connection check", "triage scorecard: synthetic"])
        self.assertTrue(all(step["exit"] == 0 for step in record["steps"]))
        self.assertGreater(record["server"]["memory"]["peak_rss_kb"], 0)
        self.assertIn("generated_tokens_per_s", record["server"]["metrics"])
        self.assertEqual(record["server"]["props"]["model_file"], "model.gguf")
        self.assertEqual((report["provenance"]["llm"]["provider"], report["provenance"]["llm"]["model"],
                          report["provenance"]["golden"]["cases"]), ("local", model_id, 2))
        self.assertIn("หน่วยความจำสูงสุด", text)
        self.assertNotIn("secret.example", text)

    def test_a_server_that_does_not_start_is_reported(self):
        with tempfile.TemporaryDirectory() as work:
            path, _digest, model_id = model_file(work)
            out = Path(work) / "lane"
            code = quiet(lane.main, ["--server-cmd", "false", "--model-path", str(path), "--model-id", model_id,
                                     "--port", str(local_model_e2e.free_port()), "--triage-sets", "none",
                                     "--e2e", "none", "--out-dir", str(out)])
            record = json.loads((out / "lane-fake-model.json").read_text(encoding="utf-8"))
        self.assertEqual(code, 1)
        self.assertEqual(record["steps"][0]["step"], "start the model server")

    def test_metrics_environment_and_sets(self):
        metrics = lane.parse_metrics("# HELP x\nllamacpp:prompt_tokens_total 1000\nllamacpp:prompt_seconds_total 4\n"
                                     "llamacpp:tokens_predicted_total 50\nllamacpp:tokens_predicted_seconds_total 5\n"
                                     'llamacpp:requests_processing{slot="0"} 1\n')
        self.assertEqual((metrics["prompt_tokens_per_s"], metrics["generated_tokens_per_s"]), (250.0, 10.0))
        env = lane.child_environment({"PATH": "/bin", "NF_MODEL_URL": "u", "HF_TOKEN": "t", "NEURON_FLOW_X": "1"}, A=1)
        self.assertEqual(env, {"PATH": "/bin", "A": "1"})
        self.assertEqual(lane.chosen_sets("all"), list(lane.SETS))
        self.assertEqual(lane.chosen_sets("none"), [])
        with self.assertRaises(SystemExit):
            lane.chosen_sets("synthetic,unknown")
        for name, relative in lane.SETS.items():  # every set the lane names exists, and the comparison knows it
            golden = json.loads((ROOT / relative).read_text(encoding="utf-8"))
            self.assertIn(golden["name"], local_model_compare.SET_NAMES, name)
            self.assertIn(golden["name"], training_overlap.SETS, name)
        self.assertIn("--no-webui", lane.SERVER_FLAGS)
        self.assertNotIn("0.0.0.0", (ROOT / ".github" / "scripts" / "local_model_lane.py").read_text(encoding="utf-8"))


class CompareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = json.loads((SAVED / "typhoon-v2-hard.json").read_text(encoding="utf-8"))

    def reports(self, work, candidate):
        paths = {}
        for label, document in (("cand", candidate), ("base", self.base)):
            paths[label] = Path(work) / f"{label}-hard.json"
            paths[label].write_text(json.dumps(document), encoding="utf-8")
        return [local_model_compare.load_reports(f"{label}={path}") for label, path in paths.items()]

    def test_figures_and_case_differences(self):
        candidate = copy.deepcopy(self.base)
        rows = {r["case_id"]: r for r in candidate["cases"]}
        wrong = [r for r in self.base["cases"] if r["llm_category"] != r["expected"]][:2]
        right = [r for r in self.base["cases"] if r["llm_category"] == r["expected"] and "needs_person" not in r["tags"]][:1]
        for r in wrong:
            rows[r["case_id"]]["llm_category"] = r["expected"]
        rows[right[0]["case_id"]]["llm_category"] = next(c for c in ("access", "other") if c != right[0]["expected"])
        rows[right[0]["case_id"]]["llm_attention"] = "security"
        with tempfile.TemporaryDirectory() as work:
            document = local_model_compare.compare(self.reports(work, candidate))
        entry = document["sets"][0]
        self.assertTrue(entry["comparable"])
        diff = entry["diff"]
        self.assertEqual(diff["only_candidate_right"], [r["case_id"] for r in wrong])
        self.assertEqual(diff["only_baseline_right"], [right[0]["case_id"]])
        self.assertIn(right[0]["case_id"], diff["ordinary_flag_only_candidate"])
        base_right = entry["models"]["base"]["ai_right_of_all"]["numerator"]
        self.assertEqual(entry["models"]["cand"]["ai_right_of_all"]["numerator"], base_right + 1)
        self.assertEqual(entry["models"]["base"]["needs_person_raised"]["denominator"], 38)
        self.assertIn("ถูกเฉพาะตัวที่ทดสอบ (2)", local_model_compare.markdown(document))

    def test_another_prompt_is_not_comparable_and_training_cases_can_be_left_out(self):
        candidate = copy.deepcopy(self.base)
        candidate["provenance"]["prompt"]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as work:
            document = local_model_compare.compare(self.reports(work, candidate))
            self.assertFalse(document["sets"][0]["comparable"])
            self.assertNotIn("diff", document["sets"][0])
            seen = frozenset(r["case_id"] for r in self.base["cases"][:10])
            document = local_model_compare.compare(self.reports(work, copy.deepcopy(self.base)), seen)
        figures = document["sets"][0]["models"]["cand"]
        self.assertEqual((figures["training_cases_here"], figures["without_training_cases"]["cases"]), (10, 118))


class OverlapTests(unittest.TestCase):
    def test_cases_inside_prompts_and_light_edits_are_found_and_the_text_is_never_shown(self):
        hard = json.loads((ROOT / "app" / "eval" / "golden" / "case_triage_autosend_hard_v1.json").read_text("utf-8"))
        dev = json.loads((ROOT / "app" / "eval" / "golden" / "case_triage_synthetic_v1.json").read_text("utf-8"))
        thai = next(c for c in hard["cases"] if c["language"] == "th")
        lines = [json.dumps({"messages": [{"role": "user", "content": "Classify:\n" + json.dumps({"case_text": thai["summary"]})},
                                          {"role": "assistant", "content": "{}"}]}),  # escaped as \\u0e..
                 json.dumps({"text": dev["cases"][0]["summary"].upper() + " !!"}),
                 json.dumps({"text": "PRIVATE-TRAINING-TEXT nothing like any case in the sets"})]
        texts = training_overlap.training_texts("\n".join(lines).encode())
        document = {"near": 0.8, "training": {"bytes": 1, "sha256": "0" * 64, "texts": len(texts)},
                    "sets": training_overlap.overlap(texts)}
        self.assertEqual(document["sets"]["case_triage_autosend_hard_v1"]["exact"], [thai["case_id"]])
        self.assertIn(dev["cases"][0]["case_id"], document["sets"]["case_triage_synthetic_v1"]["exact"]
                      + document["sets"]["case_triage_synthetic_v1"]["near"])
        self.assertEqual(document["sets"]["case_triage_heldout_v1"]["exact"], [])
        shown = training_overlap.markdown(document)
        self.assertNotIn("PRIVATE-TRAINING-TEXT", shown)
        self.assertNotIn(thai["summary"], shown)
        self.assertEqual(training_overlap.training_texts(b"one plain training line, long enough\n"),
                         ["one plain training line, long enough"])


@contextlib.contextmanager
def patch_environ(values):
    saved = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
