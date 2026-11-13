"""The local open-model provider (ADR-026): an OpenAI-format server we run ourselves (llama.cpp on the GitHub runner).

Configuration and the optional key, the HTTP client against a local fake, both workflows end to end through the
unchanged Core runtime (including a server that is down), the connection check, the run page's note, and the
*Local open model eval* workflow file's promises (read as text: the standard library has no YAML parser)."""
import importlib.util
import json
import os
import re
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock as patch

from neuron_flow import Runtime
from app.domains.case_triage import build_shadow_workflow, shadow_registry
from app.domains.study_guide import build_study_workflow, study_registry
from app.eval import common
from app.llm import (LLMConfig, LLMConfigError, LLMTransientError, load_prompt, mask, structured_answer)
from app.llm.config import DEFAULT_LOCAL_BASE_URL, OPTIONAL_KEY_PROVIDERS
from app.llm.providers import openai_compat
from tests.fake_openai import FakeServer, api_error, completion

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "local-model-eval.yml"
MODEL = "typhoon2.5-qwen3-4b-q4_k_m:0123456789ab"  # <name>:<first 12 hex digits of the file's SHA-256>
KEY = "local-test-SECRET-456"
PROMPT = load_prompt("triage_classify_v2")
GOOD = {"category": "upload", "confidence": "high", "attention": "none", "rationale": "The customer cannot attach a file."}
UPLOAD = "I cannot upload an attachment to my ticket"
STUDY_TEXT = "อยากเรียนวิธีเขียนคำสั่งให้ AI ตอบดีขึ้น"
NO_KEYS = {"NEURON_FLOW_LOCAL_API_KEY": "", "TYPHOON_API_KEY": "", "ANTHROPIC_API_KEY": ""}


def local(base_url, **overrides):
    return LLMConfig(provider="local", model=overrides.pop("model", MODEL), base_url=base_url,
                     request_timeout_s=overrides.pop("request_timeout_s", 5), **overrides)


def reply(answer=GOOD):
    return 200, completion(answer, model=MODEL)


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class ConfigTests(unittest.TestCase):
    def test_defaults_and_environment(self):
        config = LLMConfig.from_env({"NEURON_FLOW_LLM_PROVIDER": "local"})
        self.assertEqual((config.model, config.base_url, config.effort, config.key_env),
                         ("typhoon2.5-qwen3-4b-q4_k_m", None, None, "NEURON_FLOW_LOCAL_API_KEY"))
        self.assertEqual(DEFAULT_LOCAL_BASE_URL, "http://127.0.0.1:8080/v1")
        custom = LLMConfig.from_env({"NEURON_FLOW_LLM_PROVIDER": "local", "NEURON_FLOW_LLM_MODEL": MODEL,
                                     "NEURON_FLOW_LOCAL_BASE_URL": "http://127.0.0.1:9000/v1",
                                     "NEURON_FLOW_TYPHOON_BASE_URL": "https://wrong.example/v1"})
        self.assertEqual((custom.model, custom.base_url), (MODEL, "http://127.0.0.1:9000/v1"))
        # Another provider's endpoint setting does not leak into this one, nor this one into Typhoon.
        self.assertIsNone(LLMConfig.from_env({"NEURON_FLOW_LLM_PROVIDER": "local",
                                              "NEURON_FLOW_TYPHOON_BASE_URL": "https://x.example"}).base_url)
        self.assertIsNone(LLMConfig.from_env({"NEURON_FLOW_LLM_PROVIDER": "typhoon",
                                              "NEURON_FLOW_LOCAL_BASE_URL": "http://127.0.0.1:1/v1"}).base_url)

    def test_only_this_machine_may_use_plain_http(self):
        for url in ("http://127.0.0.1:8080/v1", "http://localhost:9000/v1", "https://models.example/v1"):
            self.assertEqual(local(url).base_url, url)
        for url in ("http://10.0.0.5:8080/v1", "http://models.example/v1", "https://u:p@models.example/v1",
                    "https://models.example/v1?k=1", "ftp://127.0.0.1/v1"):
            with self.assertRaises(LLMConfigError, msg=url):
                local(url)

    def test_model_ids_and_wrong_settings(self):
        self.assertEqual(LLMConfig(provider="local", model=MODEL).model, MODEL)
        for model in ("models/typhoon.gguf", "x" * 101, "mock-keyword-1", ":abc", ""):
            with self.assertRaises(LLMConfigError, msg=model):
                LLMConfig(provider="local", model=model)
        with self.assertRaisesRegex(LLMConfigError, "effort"):
            LLMConfig.from_env({"NEURON_FLOW_LLM_PROVIDER": "local", "NEURON_FLOW_LLM_EFFORT": "low"})
        with self.assertRaisesRegex(LLMConfigError, "mock_scenario"):
            openai_compat.complete(local("http://127.0.0.1:1/v1"), PROMPT, "x", scenario="transient")

    def test_no_key_is_needed_and_the_version_names_the_file(self):
        self.assertEqual(OPTIONAL_KEY_PROVIDERS, frozenset({"local"}))
        config = LLMConfig(provider="local", model=MODEL)
        config.check_ready(NO_KEYS)  # a server on this machine needs no key
        with patch.patch.dict(os.environ, NO_KEYS):
            shadow_registry(config)
            study_registry(config)
        # Typhoon and Claude still refuse to start without theirs.
        for provider, name in (("typhoon", "TYPHOON_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY")):
            with self.assertRaisesRegex(LLMConfigError, name):
                LLMConfig(provider=provider, model="m-1").check_ready(NO_KEYS)
        self.assertEqual(LLMConfig.from_params(config.to_params()), config)
        tag = config.version_tag(PROMPT)
        self.assertTrue(tag.startswith(f"llm=local/{MODEL};prompt=triage_classify_v2@sha256:"), tag)
        self.assertTrue(tag.endswith(";format=json-instruction-v1"), tag)
        other_file = LLMConfig(provider="local", model="typhoon2.5-qwen3-4b-q4_k_m:ba9876543210")
        self.assertNotEqual(tag, other_file.version_tag(PROMPT))


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.patch.dict(os.environ, NO_KEYS)
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_request_without_a_key_has_no_authorization_header(self):
        with FakeServer([reply()]) as fake:
            result = structured_answer(local(fake.base_url + "/v1"), PROMPT, mask('Upload "fails"'))
        self.assertEqual(result["answer"], GOOD)
        self.assertEqual(result["served_model"], MODEL)
        sent = fake.requests[0]
        headers = {k.lower(): v for k, v in sent["headers"].items()}
        self.assertEqual(sent["path"], "/v1/chat/completions")
        self.assertNotIn("authorization", headers)
        body = sent["body"]
        self.assertEqual((body["model"], body["max_tokens"]), (MODEL, 2048))
        # The server turns the schema into a grammar; the same words as for Typhoon are added too.
        self.assertEqual(body["response_format"]["json_schema"]["schema"], PROMPT.output_schema)
        self.assertEqual(body["messages"][0]["content"],
                         PROMPT.system + "\n\n" + openai_compat.format_instruction(PROMPT.output_schema))
        for forbidden in ("temperature", "top_p", "seed", "tools", "tool_choice", "stream"):
            self.assertNotIn(forbidden, body)

    def test_a_key_is_sent_when_set_and_never_returned(self):
        with patch.patch.dict(os.environ, {"NEURON_FLOW_LOCAL_API_KEY": KEY}), FakeServer([reply()]) as fake:
            result = structured_answer(local(fake.base_url), PROMPT, mask("upload fails"))
        headers = {k.lower(): v for k, v in fake.requests[0]["headers"].items()}
        self.assertEqual(headers["authorization"], f"Bearer {KEY}")
        self.assertNotIn(KEY, json.dumps(result))

    def test_a_rejected_key_is_a_setup_error_that_names_the_variable(self):
        with FakeServer([api_error(401, "invalid_api_key")]) as fake:
            with self.assertRaisesRegex(LLMConfigError, "NEURON_FLOW_LOCAL_API_KEY"):
                structured_answer(local(fake.base_url), PROMPT, mask("x"))

    def test_default_endpoint_is_this_machine(self):
        captured = {}

        class Stop(Exception):
            pass

        def fake_open(request, timeout):
            captured.update(url=request.full_url, timeout=timeout,
                            auth=request.get_header("Authorization"))
            raise Stop

        with patch.patch.object(openai_compat.OPENER, "open", fake_open):
            with self.assertRaises(Stop):
                structured_answer(LLMConfig(provider="local", model=MODEL), PROMPT, mask("x"))
        self.assertEqual(captured, {"url": "http://127.0.0.1:8080/v1/chat/completions", "timeout": 30.0,
                                    "auth": None})

    def test_a_server_that_is_down_or_slow_is_temporary(self):
        with self.assertRaises(LLMTransientError):
            structured_answer(local(f"http://127.0.0.1:{free_port()}/v1"), PROMPT, mask("x"))
        with FakeServer([(200, completion(GOOD, model=MODEL), 1.5)]) as fake:
            with self.assertRaises(LLMTransientError):
                structured_answer(local(fake.base_url, request_timeout_s=0.5), PROMPT, mask("x"))
        for status in (500, 503):  # llama-server answers 503 while the model is still loading
            with FakeServer([api_error(status, "unavailable_error")]) as fake:
                with self.assertRaises(LLMTransientError):
                    structured_answer(local(fake.base_url), PROMPT, mask("x"))


class EndToEndTests(unittest.TestCase):
    def test_triage_shadow_mode_with_a_local_server_and_no_key(self):
        with patch.patch.dict(os.environ, NO_KEYS), FakeServer([reply()]) as fake, \
                tempfile.TemporaryDirectory() as work:
            config = local(fake.base_url)
            with Runtime(work, agents=shadow_registry(config)) as rt:
                rt.submit(build_shadow_workflow("local_job", {"case_id": "LOCAL-1", "summary": UPLOAD}, config))
                snapshot = rt.run("local_job")
        self.assertEqual(snapshot["status"], "SUCCEEDED")
        llm = snapshot["steps"]["classify_llm"]["output"]
        self.assertEqual((llm["status"], llm["category"], llm["served_model"]), ("ok", "upload", MODEL))
        self.assertEqual((llm["provenance"]["provider"], llm["provenance"]["model"]), ("local", MODEL))
        prepared = snapshot["steps"]["prepare"]["output"]
        self.assertEqual((prepared["decision"], prepared["review_required"]), ("PENDING_HUMAN_REVIEW", True))

    def test_a_server_that_is_down_still_lets_the_case_reach_review(self):
        config = local(f"http://127.0.0.1:{free_port()}/v1", request_timeout_s=1)
        with patch.patch.dict(os.environ, NO_KEYS), tempfile.TemporaryDirectory() as work:
            with Runtime(work, agents=shadow_registry(config)) as rt:
                rt.submit(build_shadow_workflow("local_down", {"case_id": "LOCAL-2", "summary": UPLOAD}, config))
                snapshot = rt.run("local_down")
        self.assertEqual(snapshot["status"], "SUCCEEDED")
        step = snapshot["steps"]["classify_llm"]
        self.assertEqual((step["output"]["status"], step["output"]["reason"], step["attempts"]),
                         ("unavailable", "provider_unavailable", 2))  # retried once, then "unavailable"
        compare = snapshot["steps"]["compare"]["output"]
        self.assertEqual(compare["agreement"], "llm_unavailable")
        self.assertEqual(snapshot["steps"]["prepare"]["output"]["decision"], "PENDING_HUMAN_REVIEW")

    def test_study_guide_both_calls_go_to_the_local_server_with_masked_text(self):
        detect = {"topic": "prompt_writing", "confidence": "high", "language": "th",
                  "restatement": "คุณอยากเรียนการเขียนคำสั่งให้ AI"}
        explain = {"summary": "เริ่มจากพื้นฐานของการเขียนคำสั่งก่อน", "note_1": "ทำไมเรื่องนี้สำคัญ",
                   "note_2": "แก่นของสิ่งที่คุณถาม"}
        with patch.patch.dict(os.environ, NO_KEYS), FakeServer([reply(detect), reply(explain)]) as fake, \
                tempfile.TemporaryDirectory() as work:
            config = local(fake.base_url)
            with Runtime(work, agents=study_registry(config)) as rt:
                rt.submit(build_study_workflow("local_study", {"message": STUDY_TEXT + " โทร 081-234-5678"}, config))
                snapshot = rt.run("local_study")
        self.assertEqual(snapshot["status"], "SUCCEEDED")
        answer = snapshot["steps"]["answer"]["output"]
        self.assertEqual((answer["status"], answer["details"]["explanation_source"]), ("guide", "ai"))
        self.assertEqual(len(fake.requests), 2)
        sent = json.dumps([request["body"] for request in fake.requests], ensure_ascii=False)
        self.assertNotIn("081-234-5678", sent)
        self.assertIn("[PHONE]", sent)


class RunPageTests(unittest.TestCase):
    def test_connection_check_works_without_a_key(self):
        spec = importlib.util.spec_from_file_location("probe", ROOT / ".github" / "scripts" / "llm_probe.py")
        probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(probe)
        with FakeServer([reply()]) as fake, tempfile.NamedTemporaryFile("r", suffix=".md") as summary, \
                patch.patch.dict(os.environ, {**NO_KEYS, "NEURON_FLOW_LLM_PROVIDER": "local",
                                              "NEURON_FLOW_LLM_MODEL": MODEL,
                                              "NEURON_FLOW_LOCAL_BASE_URL": fake.base_url}):
            probe.main(summary.name)
            text = Path(summary.name).read_text(encoding="utf-8")
        self.assertIn("key present: not needed", text)
        self.assertIn("**answered**", text)
        self.assertIn(f"served model `{MODEL}`", text)
        headers = {k.lower() for k in fake.requests[0]["headers"]}
        self.assertNotIn("authorization", headers)

    def test_the_note_says_whose_numbers_these_are(self):
        note = "\n".join(common.provider_note({"provider": "local", "model": MODEL}))
        self.assertIn(MODEL, note)
        self.assertIn("ไม่ได้ส่งไปบริษัท AI ใด", note)
        self.assertIn("not to Claude", note)
        self.assertIn("Typhoon", "\n".join(common.provider_note({"provider": "typhoon", "model": "t"})))
        self.assertEqual(common.provider_note({"provider": "mock", "model": "mock-keyword-1"}), [])


class WorkflowFileTests(unittest.TestCase):
    """The *Local open model eval* workflow's promises, checked on the file itself (and on the lane script and pin file
    it uses, ADR-034)."""

    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.lane = (ROOT / ".github" / "scripts" / "local_model_lane.py").read_text(encoding="utf-8")
        cls.fetch = (ROOT / ".github" / "scripts" / "fetch_model.py").read_text(encoding="utf-8")
        cls.pins = json.loads((ROOT / ".github" / "local_models.json").read_text(encoding="utf-8"))

    def env_value(self, name):
        found = re.search(rf"^\s+{name}:\s*\"?([^\"\n#]*)\"?\s*(#.*)?$", self.text, re.MULTILINE)
        self.assertIsNotNone(found, name)
        return found.group(1).strip()

    def test_it_uses_the_local_provider_and_only_the_private_links_secrets(self):
        self.assertEqual(self.env_value("NEURON_FLOW_LLM_PROVIDER"), "local")
        self.assertNotRegex(self.text, r"API_KEY\s*:")  # no AI provider's key variable is set at all
        timeout = float(self.env_value("NEURON_FLOW_LLM_TIMEOUT_S"))
        LLMConfig(provider="local", model=MODEL, request_timeout_s=timeout)  # within the client's limits
        # The only secrets: the owner's private link, its optional token, and the optional training-data link, each
        # read only on a run started by hand (never on a pull request).
        uses = re.findall(r"secrets\.([A-Z_]+)", self.text)
        self.assertEqual(set(uses), {"NF_MODEL_URL", "NF_MODEL_TOKEN", "NF_TRAINING_URL"})
        for line in (line for line in self.text.splitlines() if "secrets." in line):
            self.assertIn("github.event_name == 'workflow_dispatch' && secrets.", line)

    def test_the_server_listens_on_this_machine_only(self):
        self.assertIn('"--host", "127.0.0.1"', self.lane)
        for text in (self.text, self.lane):
            self.assertNotIn("0.0.0.0", text)
        self.assertIn('"--no-webui"', self.lane)

    def test_llama_cpp_and_every_model_file_are_pinned(self):
        self.assertRegex(self.env_value("LLAMA_CPP_COMMIT"), r"^[0-9a-f]{40}$")
        self.assertRegex(self.env_value("LLAMA_CPP_TAG"), r"^b\d+$")
        self.assertIn('if [ "$got" != "$LLAMA_CPP_COMMIT" ]', self.text)  # the tag must be that commit
        self.assertIn("--profile .github/local_models.json", self.text)
        self.assertEqual(set(self.pins["models"]), {self.env_value("BASE_MODEL"), self.env_value("FINETUNE_MODEL")})
        for name, entry in self.pins["models"].items():
            self.assertRegex(entry["sha256"], r"^[0-9a-f]{64}$", name)
            self.assertIsInstance(entry["size"], int, name)
            self.assertTrue(entry["file"].endswith(".gguf") and "*" not in entry["file"], name)
        base = self.pins["models"][self.env_value("BASE_MODEL")]
        self.assertRegex(base["source"]["revision"], r"^[0-9a-f]{40}$")  # a commit, not a branch
        self.assertIn(f"key: local-model-public-{self.env_value('BASE_MODEL')}-{base['sha256']}-v2", self.text)

    def test_a_file_that_is_not_published_is_never_cached_or_uploaded(self):
        caches = re.findall(r"uses: actions/cache@v\d+\n\s+with:\n\s+path: (\S+)", self.text)
        self.assertEqual(caches, ["~/llama-bin", "~/models/public"])
        self.assertIn('dest="$RUNNER_TEMP/private-models"', self.text)  # outside every cached folder
        self.assertIn('if grep -qx "cache=true" "$described"; then dest="$HOME/models/public"', self.text)
        self.assertFalse(self.pins["models"][self.env_value("FINETUNE_MODEL")]["cache"])
        upload = self.text.split("uses: actions/upload-artifact", 1)[1]
        self.assertIn("path: lane/*.json", upload)
        self.assertNotIn("gguf", upload)
        self.assertNotIn("models", upload)

    def test_the_model_id_names_the_file_and_is_the_servers_alias(self):
        self.assertIn('"model_id": f"{name}:{entry[\'sha256\'][:12]}"', self.fetch)
        self.assertIn('"--alias", model_id', self.lane)
        self.assertIn("NEURON_FLOW_LLM_MODEL=args.model_id", self.lane)
        for name in self.pins["models"]:
            LLMConfig(provider="local", model=f"{name}:0123456789ab")  # a valid model id

    def test_pull_requests_get_a_small_smoke_run_with_the_public_file(self):
        self.assertIn("github.event_name == 'pull_request' && '5' || inputs.limit", self.text)
        self.assertIn("github.event_name == 'pull_request' && 'typhoon2.5-qwen3-4b-q4_k_m' || inputs.model", self.text)
        on = self.text.split("\npermissions:", 1)[0]
        for path in ('".github/workflows/local-model-eval.yml"', '".github/scripts/fetch_model.py"', '"app/llm/**"',
                     '".github/local_models.json"', '".github/scripts/local_model_lane.py"', '"tests/local_model_e2e.py"'):
            self.assertIn(path, on)
        self.assertIn("workflow_dispatch:", on)

if __name__ == "__main__":
    unittest.main()
