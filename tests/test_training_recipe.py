"""Own-model track T3: the training recipe, the rendered examples, the receipt and the GPU script (ADR-037).

The main guard is train/serve sameness: every training example's messages are compared, byte for byte, with what the
service would send for that case, and the recipe with how the local lane serves the model (thinking off, greedy
decoding, the same llama.cpp commit and quantization). The training script itself cannot run here (it needs a GPU and
the libraries in training/requirements-train.txt), so its dry run, its encoding of one example and its imports are
tested, and nothing else in the repository may import it.
"""

import ast
import contextlib
import copy
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

from app.llm.config import DEFAULT_MODELS, LLMConfig
from app.llm.gateway import parse_answer
from app.llm.prompts import load_prompt
from app.llm.providers.openai_compat import build_request_body
from app.llm.redaction import mask
from training import check_set, receipt, render, train_qlora

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = (ROOT / ".github" / "workflows" / "local-model-eval.yml").read_text(encoding="utf-8")
HEAVY = {"torch", "transformers", "peft", "huggingface_hub", "bitsandbytes", "accelerate"}


def cases():
    return check_set.load_set(check_set.DEFAULT_SET)["cases"]


class RenderTests(unittest.TestCase):
    def test_every_example_is_what_the_service_would_send(self):
        prompt = load_prompt(check_set.PROMPT_ID)
        config = LLMConfig(provider="local", model=DEFAULT_MODELS["local"])
        for case, example in zip(cases(), render.examples(cases(), 0.1)):
            with self.subTest(case=case["case_id"]):
                sent = build_request_body(config, prompt, mask(case["summary"]).text)["messages"]
                self.assertEqual(example["messages"][:2], sent)
                self.assertEqual(example["messages"][2]["role"], "assistant")
                answer = parse_answer(example["messages"][2]["content"], prompt.output_schema)
                self.assertEqual(answer, {key: case[key] for key in ("attention", "category", "confidence",
                                                                     "rationale")})

    def test_the_answer_keeps_the_order_the_format_words_ask_for(self):
        prompt = load_prompt(check_set.PROMPT_ID)
        content = render.answer_text(cases()[0], prompt)
        self.assertEqual(list(json.loads(content)), list(prompt.output_schema["properties"]))
        system = render.serving_messages(cases()[0]["summary"], prompt)[0]["content"]
        self.assertIn("exactly these keys, in this order", system)

    def test_rendering_is_deterministic_and_the_split_is_fixed_by_the_case_id(self):
        first, digest = render.render(check_set.DEFAULT_SET, 0.1)
        second, again = render.render(check_set.DEFAULT_SET, 0.1)
        self.assertEqual((first, digest), (second, again))
        splits = [json.loads(line)["split"] for line in first.splitlines()]
        self.assertEqual(len(splits), 240)
        self.assertTrue(0 < splits.count("eval") < 48)
        self.assertEqual(render.split_of("TR-EN-ACC-001", 0.1), render.split_of("TR-EN-ACC-001", 0.1))
        none_held = render.render(check_set.DEFAULT_SET, 0.0)[0]
        self.assertNotIn('"split": "eval"', none_held)

    def test_no_message_is_written_by_hand(self):
        source = (ROOT / "training" / "render.py").read_text(encoding="utf-8")
        self.assertIn("build_request_body(", source)
        self.assertNotRegex(source, r"""["']role["']\s*:\s*["'](system|user)["']""")


class RecipeTests(unittest.TestCase):
    def setUp(self):
        self.recipe = receipt.load_recipe()

    def test_the_recipe_passes_its_checks(self):
        self.assertEqual(receipt.check_recipe(self.recipe), [])

    def test_the_recipe_pins_the_approved_training_set(self):
        manifest = json.loads(check_set.manifest_path(check_set.DEFAULT_SET).read_text(encoding="utf-8"))
        self.assertEqual(self.recipe["task"]["training_set_sha256"], manifest["sha256"])
        self.assertEqual(ROOT / self.recipe["task"]["training_set"], check_set.DEFAULT_SET)

    def test_the_recipe_matches_how_the_local_lane_serves(self):
        env = dict(re.findall(r"^\s+(LLAMA_CPP_TAG|LLAMA_CPP_COMMIT|MODEL_FILE): (\S+)$", WORKFLOW, re.M))
        export, serving = self.recipe["export"], self.recipe["serving"]
        self.assertEqual((export["llama_cpp_tag"], export["llama_cpp_commit"]),
                         (env["LLAMA_CPP_TAG"], env["LLAMA_CPP_COMMIT"]))
        self.assertIn(export["gguf_quant"].lower(), env["MODEL_FILE"].lower())
        server = WORKFLOW[WORKFLOW.index("llama-server -m"):WORKFLOW.index("--no-webui")]
        for flag, value in (("--reasoning", serving["reasoning"]), ("--temp", serving["temperature"]),
                            ("--repeat-penalty", serving["repeat_penalty"]), ("--seed", serving["seed"]),
                            ("--ctx-size", serving["ctx_size"])):
            with self.subTest(flag=flag):
                self.assertRegex(server, rf"{re.escape(flag)} {re.escape(str(value))}\b")
        self.assertEqual(self.recipe["chat_template_kwargs"], {"enable_thinking": False})

    def test_the_base_model_revision_is_the_one_on_record(self):
        record = (ROOT / "docs" / "own_model_plan.md").read_text(encoding="utf-8")  # section 14, the record
        revision = re.search(r"`typhoon-ai/typhoon2\.5-qwen3-4b` \(revision\s+`([0-9a-f]{40})`\)", record).group(1)
        self.assertEqual(self.recipe["base_model"], {**self.recipe["base_model"], "repo": "typhoon-ai/typhoon2.5-qwen3-4b",
                                                     "revision": revision})

    def test_a_recipe_that_would_train_another_format_is_refused(self):
        for path, value, words in ((("chat_template_kwargs",), {"enable_thinking": True}, "thinking off"),
                                   (("serving", "temperature"), 0.7, "temperature 0"),
                                   (("task", "training_set_sha256"), "0" * 64, "approve the new set first"),
                                   (("base_model", "revision"), "ce0a7416", "40-digit"),
                                   (("training", "loss_on"), "everything", "assistant_only"),
                                   (("training", "eval_share"), 0.5, "eval_share"),
                                   (("training", "learning_rate"), 0.5, "learning_rate"),
                                   (("export", "gguf_quant"), "Q8_0", "Q4_K_M"),
                                   (("task", "prompt_id"), "triage_classify_v1", "prompt_id")):
            bad = copy.deepcopy(self.recipe)
            target = bad
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path):
                self.assertTrue(any(words in p for p in receipt.check_recipe(bad)), receipt.check_recipe(bad))


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.plan, problems = train_qlora.plan(receipt.RECIPE, check_set.DEFAULT_SET)
        self.assertEqual(problems, [])

    def completed(self):
        digest = "ab" * 32
        run = {"base_files": {"model.safetensors": "cd" * 32, "config.json": "ef" * 32}, "gpu": "test GPU",
               "dtype": "float16", "train_seconds": 12.5, "steps": 3, "losses": [{"epoch": 1.0, "loss": 1.2}],
               "adapter": {"sha256": "12" * 32},
               "gguf": {"file": "m.gguf", "name": "nf-triage-4b-r1-q4_k_m", "sha256": digest, "bytes": 2_500_000_000,
                        "model_id": f"nf-triage-4b-r1-q4_k_m:{digest[:12]}", "llama_cpp_commit": "f" * 40,
                        "quant": "Q4_K_M"}}
        return train_qlora.build_receipt(self.plan, run, None, "2026-11-22T00:00:00+00:00")

    def test_a_completed_receipt_is_valid_and_names_its_inputs(self):
        record = self.completed()
        self.assertEqual(receipt.validate(record), [])
        self.assertEqual(record["status"], "COMPLETED")
        self.assertEqual(record["training_set"]["sha256"], self.plan["training_set_sha256"])
        self.assertEqual(record["serving_contract"], receipt.serving_contract())
        self.assertEqual(set(record["environment"]["pinned"]), {"transformers", "peft", "bitsandbytes", "accelerate"})

    def test_a_failed_run_still_writes_a_valid_receipt(self):
        record = train_qlora.build_receipt(self.plan, None, "RuntimeError: out of memory", None)
        self.assertEqual(record["status"], "FAILED")
        self.assertEqual(receipt.validate(record), [])

    def test_inconsistent_receipts_are_refused(self):
        for mutate, words in ((lambda r: r.update(schema="other"), "schema"),
                              (lambda r: r.update(status="DONE"), "status"),
                              (lambda r: r["recipe"].update(sha256="xyz"), "recipe.sha256"),
                              (lambda r: r["outputs"]["gguf"].update(model_id="nf:000000000000"), "model_id"),
                              (lambda r: r["outputs"]["gguf"].update(bytes=0), "bytes"),
                              (lambda r: r["base_model"].update(files={}), "base_model.files"),
                              (lambda r: r["serving_contract"].pop("checks"), "serving_contract"),
                              (lambda r: r["outputs"]["adapter"].update(sha256=""), "adapter")):
            record = self.completed()
            mutate(record)
            with self.subTest(words=words):
                self.assertTrue(any(words in p for p in receipt.validate(record)), receipt.validate(record))

    def test_a_model_trained_for_another_prompt_or_checks_is_found(self):
        record = self.completed()
        self.assertEqual(receipt.serving_mismatches(record), [])
        record["serving_contract"]["prompt_sha256"] = "0" * 64
        record["serving_contract"]["checks"] = "answer-checks-v2"
        found = {field for field, _trained, _now in receipt.serving_mismatches(record)}
        self.assertEqual(found, {"prompt_sha256", "checks"})


class FakeTokenizer:
    """Turns a chat into characters the way a template would; ``rewrite`` changes the prompt once an answer follows."""

    def __init__(self, rewrite=False):
        self.rewrite = rewrite

    def apply_chat_template(self, messages, tokenize, add_generation_prompt, enable_thinking):
        assert tokenize is True and enable_thinking is False
        text = "".join(f"<{m['role']}>{m['content']}" for m in messages[:2])
        if self.rewrite and len(messages) > 2:
            text = text.replace("<user>", "<USER>")
        text += "<assistant>"
        if len(messages) > 2:
            text += messages[2]["content"] + "<end>"
        return [ord(character) for character in text]


class TrainScriptTests(unittest.TestCase):
    def run_main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = train_qlora.main(list(args))
        return code, out.getvalue()

    def test_a_dry_run_checks_and_plans_without_any_training_library(self):
        code, out = self.run_main("--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("DRY RUN", out)
        self.assertIn("240 cases", out)
        self.assertFalse(HEAVY & set(sys.modules), sorted(HEAVY & set(sys.modules)))

    def test_a_run_stops_before_training_on_a_set_that_fails_its_checks(self):
        with tempfile.TemporaryDirectory() as folder:
            data = check_set.load_set(check_set.DEFAULT_SET)
            exam = json.loads((ROOT / "app/eval/golden/case_triage_heldout_v1.json").read_text(encoding="utf-8"))
            english = next(c for c in exam["cases"] if c["language"] == "en")
            data["cases"][0]["summary"] = english["summary"]  # an exam text copied into the training set
            path = Path(folder) / "bad_set.json"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            check_set.manifest_path(path).write_text(json.dumps(check_set.build_manifest(path)), encoding="utf-8")
            code, out = self.run_main("--set", str(path), "--out", str(Path(folder) / "out"))
        self.assertEqual(code, 1)
        self.assertIn("STOPPED: nothing was trained", out)
        self.assertIn("overlaps with exam sets", out)

    def test_only_the_answer_is_learned_and_a_rewriting_template_is_refused(self):
        example = next(render.examples(cases()[:1], 0.0))
        encoded = train_qlora._encode(FakeTokenizer(), example, {"enable_thinking": False}, 100_000)
        answer_start = encoded["labels"].index(next(label for label in encoded["labels"] if label != -100))
        learned = "".join(chr(i) for i in encoded["input_ids"][answer_start:])
        self.assertEqual(learned, example["messages"][2]["content"] + "<end>")
        self.assertEqual(len(encoded["labels"]), len(encoded["input_ids"]))
        with self.assertRaisesRegex(RuntimeError, "changes the prompt"):
            train_qlora._encode(FakeTokenizer(rewrite=True), example, {"enable_thinking": False}, 100_000)
        with self.assertRaisesRegex(RuntimeError, "max_seq_length"):
            train_qlora._encode(FakeTokenizer(), example, {"enable_thinking": False}, 10)

    def test_training_libraries_are_imported_only_inside_the_script_s_functions(self):
        tree = ast.parse((ROOT / "training" / "train_qlora.py").read_text(encoding="utf-8"))
        top = {alias.name.split(".")[0] for node in tree.body if isinstance(node, ast.Import) for alias in node.names}
        top |= {node.module.split(".")[0] for node in tree.body
                if isinstance(node, ast.ImportFrom) and node.module and node.level == 0}
        self.assertLessEqual(top, set(sys.stdlib_module_names))
        inside = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                  for alias in node.names} | {node.module.split(".")[0] for node in ast.walk(tree)
                                              if isinstance(node, ast.ImportFrom) and node.module and node.level == 0}
        self.assertLessEqual(inside - set(sys.stdlib_module_names), HEAVY)

    def test_the_training_libraries_never_reach_the_service(self):
        pins = train_qlora.pinned_versions()
        self.assertEqual(set(pins), {"transformers", "peft", "bitsandbytes", "accelerate"})
        for name in ("pyproject.toml", "Dockerfile", ".claude/hooks/session-start.sh"):
            text = (ROOT / name).read_text(encoding="utf-8").lower()
            for library in pins:
                with self.subTest(file=name, library=library):
                    self.assertNotIn(library, text)
        for path in [*(ROOT / "app").rglob("*.py"), *(ROOT / "neuron_flow").rglob("*.py")]:
            source = path.read_text(encoding="utf-8")
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertNotRegex(source, r"(?m)^\s*(from|import) (training|torch|transformers|peft)\b")


if __name__ == "__main__":
    unittest.main()
