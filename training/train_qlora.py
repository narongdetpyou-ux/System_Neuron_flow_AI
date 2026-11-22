"""Train one round of our own model where a GPU is (own-model track T3; run in T5 after owner decision D10).

Never part of the service: the image never copies ``training/``, and no module of ``app/`` imports this one. The heavy
libraries (PyTorch, Transformers, PEFT, bitsandbytes; pinned in ``training/requirements-train.txt``) are imported only
inside the functions that train, so ``--dry-run`` and the tests run with the standard library.

What one run does, in order, stopping at the first problem:

1. **Check** the recipe (``receipt.check_recipe``) and the training set (``check_set.run``: records, manifest, no
   overlap with any exam set). Nothing trains on a set that fails.
2. **Render** the examples with the serving code (``render``), so the model learns exactly the messages it will get.
3. **Train** a LoRA adapter on the base model loaded in 4 bits (QLoRA), learning only the answer tokens. Each
   example's prompt must be an exact prefix of the full conversation under the model's chat template with thinking
   off, or the run stops: a template that rewrites the prompt would teach another format than the one served.
4. **Merge** the adapter into the base model, then **export** a GGUF file with the local lane's pinned llama.cpp
   commit, quantized as the lane serves (Q4_K_M).
5. **Write** ``training_receipt.json``: every input and output by SHA-256, the library versions, the GPU, the losses
   and the serving contract (``receipt.serving_contract``), whether the run completed or failed.

Run: ``python -m training.train_qlora --dry-run`` (checks and plans only), or ``python -m training.train_qlora --out
<folder>`` on a machine with a GPU and the pinned libraries.
"""

import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

from . import check_set, receipt, render

LIBRARIES = ("torch", "transformers", "peft", "bitsandbytes", "accelerate")
REQUIREMENTS = Path(__file__).with_name("requirements-train.txt")


def pinned_versions():
    """``{name: version}`` from ``requirements-train.txt`` (lines ``name==version``)."""
    pins = {}
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if "==" in line:
            name, version = line.split("==", 1)
            pins[name.strip()] = version.strip()
    return pins


def plan(recipe_path, set_path):
    """``(plan, problems)``: what a run would do, and why it must not start (empty when it may)."""
    recipe = receipt.load_recipe(recipe_path)
    problems = [f"recipe: {p}" for p in receipt.check_recipe(recipe)]
    passed, record_problems, manifest_problems, results, cases = check_set.run(set_path)
    if not passed:
        problems.append(f"training set: {len(record_problems)} record problems, {len(manifest_problems)} manifest "
                        f"problems, {sum(len(r['exact']) + len(r['near']) for r in results)} overlaps with exam sets")
    text, digest = render.render(set_path, recipe["training"]["eval_share"])
    examples = [json.loads(line) for line in text.splitlines()]
    return {"recipe": recipe, "recipe_sha256": receipt.sha256_file(recipe_path),
            "training_set": str(set_path), "training_set_sha256": receipt.sha256_file(set_path), "cases": len(cases),
            "rendered_text": text, "rendered_sha256": digest, "examples": examples,
            "train": sum(e["split"] == "train" for e in examples), "eval": sum(e["split"] == "eval" for e in examples),
            "serving_contract": receipt.serving_contract()}, problems


def library_versions():
    versions = {}
    for name in LIBRARIES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def _encode(tokenizer, example, kwargs, max_length):
    """Token ids with labels on the answer only; refuses a chat template that does not extend the prompt."""
    messages = example["messages"]
    prompt_ids = tokenizer.apply_chat_template(messages[:2], tokenize=True, add_generation_prompt=True, **kwargs)
    full_ids = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=False, **kwargs)
    if full_ids[:len(prompt_ids)] != prompt_ids:
        raise RuntimeError(f"{example['case_id']}: the chat template changes the prompt when the answer is added")
    if len(full_ids) > max_length:
        raise RuntimeError(f"{example['case_id']}: {len(full_ids)} tokens, more than max_seq_length {max_length}")
    return {"input_ids": full_ids, "attention_mask": [1] * len(full_ids),
            "labels": [-100] * len(prompt_ids) + full_ids[len(prompt_ids):]}


def train(the_plan, out):
    """Steps 3 and 4: the adapter, the merged model and the GGUF file. Returns the receipt's run and output parts."""
    import torch
    from huggingface_hub import snapshot_download
    from peft import LoraConfig, PeftModel, get_peft_model, prepare_model_for_kbit_training
    from transformers import (AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, Trainer,
                              TrainingArguments)

    recipe = the_plan["recipe"]
    base, qlora, settings = recipe["base_model"], recipe["qlora"], recipe["training"]
    torch.manual_seed(settings["seed"])
    bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    dtype = torch.bfloat16 if bf16 else torch.float16  # a GPU without bf16 (such as a T4) trains in fp16
    snapshot = Path(snapshot_download(base["repo"], revision=base["revision"]))
    base_files = {path.name: receipt.sha256_file(path) for path in sorted(snapshot.iterdir())
                  if path.is_file() and path.suffix in (".safetensors", ".json", ".txt", ".model", ".jinja")}

    tokenizer = AutoTokenizer.from_pretrained(snapshot)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    quant = BitsAndBytesConfig(load_in_4bit=qlora["load_in_4bit"], bnb_4bit_quant_type=qlora["quant_type"],
                               bnb_4bit_use_double_quant=qlora["double_quant"], bnb_4bit_compute_dtype=dtype)
    model = AutoModelForCausalLM.from_pretrained(snapshot, quantization_config=quant, torch_dtype=dtype,
                                                 device_map="auto")
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model = get_peft_model(model, LoraConfig(r=qlora["lora_r"], lora_alpha=qlora["lora_alpha"],
                                             lora_dropout=qlora["lora_dropout"], bias="none",
                                             target_modules=qlora["target_modules"], task_type="CAUSAL_LM"))

    kwargs = recipe["chat_template_kwargs"]
    encoded = {split: [_encode(tokenizer, e, kwargs, settings["max_seq_length"])
                       for e in the_plan["examples"] if e["split"] == split] for split in ("train", "eval")}

    def collate(batch):
        width = max(len(item["input_ids"]) for item in batch)
        pad = tokenizer.pad_token_id
        return {"input_ids": torch.tensor([i["input_ids"] + [pad] * (width - len(i["input_ids"])) for i in batch]),
                "attention_mask": torch.tensor([i["attention_mask"] + [0] * (width - len(i["attention_mask"]))
                                                for i in batch]),
                "labels": torch.tensor([i["labels"] + [-100] * (width - len(i["labels"])) for i in batch])}

    args = TrainingArguments(output_dir=str(out / "trainer"), num_train_epochs=settings["epochs"],
                             learning_rate=settings["learning_rate"], lr_scheduler_type=settings["lr_scheduler"],
                             warmup_ratio=settings["warmup_ratio"],
                             per_device_train_batch_size=settings["per_device_batch_size"],
                             per_device_eval_batch_size=settings["per_device_batch_size"],
                             gradient_accumulation_steps=settings["gradient_accumulation_steps"],
                             eval_strategy="epoch" if encoded["eval"] else "no", save_strategy="no",
                             logging_steps=5, bf16=bf16, fp16=not bf16, seed=settings["seed"],
                             data_seed=settings["seed"], report_to="none", remove_unused_columns=False)
    trainer = Trainer(model=model, args=args, train_dataset=encoded["train"],
                      eval_dataset=encoded["eval"] or None, data_collator=collate)
    started = time.monotonic()
    trainer.train()
    adapter_dir = out / "adapter"
    model.save_pretrained(adapter_dir)
    tokenizer.save_pretrained(adapter_dir)
    losses = [{key: entry[key] for key in ("epoch", "loss", "eval_loss") if key in entry}
              for entry in trainer.state.log_history if "loss" in entry or "eval_loss" in entry]
    train_seconds = round(time.monotonic() - started, 1)

    del trainer, model
    torch.cuda.empty_cache()
    merged = PeftModel.from_pretrained(AutoModelForCausalLM.from_pretrained(snapshot, torch_dtype=dtype,
                                                                            device_map="auto"),
                                       adapter_dir).merge_and_unload()
    merged_dir = out / "merged"
    merged.save_pretrained(merged_dir, safe_serialization=True)
    tokenizer.save_pretrained(merged_dir)
    gguf = export_gguf(recipe["export"], merged_dir, out)
    return {"dtype": "bfloat16" if bf16 else "float16", "train_seconds": train_seconds, "losses": losses,
            "steps": len(losses), "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "base_files": base_files,
            "adapter": {"sha256": receipt.sha256_file(adapter_dir / "adapter_model.safetensors")}, "gguf": gguf}


def export_gguf(export, merged_dir, out):
    """Step 4's export: llama.cpp at the lane's pinned commit converts the merged model and quantizes it."""
    source = out / "llama.cpp"
    if not source.exists():
        subprocess.run(["git", "clone", "--depth", "1", "--branch", export["llama_cpp_tag"],
                        "https://github.com/ggml-org/llama.cpp", str(source)], check=True)
    head = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], check=True, capture_output=True,
                          text=True).stdout.strip()
    if head != export["llama_cpp_commit"]:
        raise RuntimeError(f"llama.cpp {export['llama_cpp_tag']} is commit {head}, not {export['llama_cpp_commit']}")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r",
                    str(source / "requirements" / "requirements-convert_hf_to_gguf.txt")], check=True)
    full = out / "model-bf16.gguf"
    subprocess.run([sys.executable, str(source / "convert_hf_to_gguf.py"), str(merged_dir), "--outtype", "bf16",
                    "--outfile", str(full)], check=True)
    build = out / "llama-build"
    subprocess.run(["cmake", "-S", str(source), "-B", str(build), "-DCMAKE_BUILD_TYPE=Release",
                    "-DLLAMA_BUILD_TESTS=OFF", "-DLLAMA_BUILD_EXAMPLES=OFF", "-DLLAMA_BUILD_SERVER=OFF",
                    "-DLLAMA_OPENSSL=OFF"], check=True)
    subprocess.run(["cmake", "--build", str(build), "--target", "llama-quantize", "-j"], check=True)
    final = out / f"{export['model_name']}.gguf"
    subprocess.run([str(build / "bin" / "llama-quantize"), str(full), str(final), export["gguf_quant"]], check=True)
    digest = receipt.sha256_file(final)
    return {"file": final.name, "name": export["model_name"], "sha256": digest, "bytes": final.stat().st_size,
            "model_id": f"{export['model_name']}:{digest[:12]}", "llama_cpp_commit": head,
            "quant": export["gguf_quant"]}


def build_receipt(the_plan, run=None, error=None, started_at=None):
    recipe = the_plan["recipe"]
    run = run or {}
    return {"schema": receipt.RECEIPT_SCHEMA, "status": "FAILED" if error or not run else "COMPLETED",
            "error": error, "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "recipe": {"name": recipe["name"], "sha256": the_plan["recipe_sha256"]},
            "training_set": {"file": the_plan["training_set"], "sha256": the_plan["training_set_sha256"],
                             "cases": the_plan["cases"]},
            "rendered": {"sha256": the_plan["rendered_sha256"], "train": the_plan["train"], "eval": the_plan["eval"]},
            "serving_contract": the_plan["serving_contract"],
            "base_model": {"repo": recipe["base_model"]["repo"], "revision": recipe["base_model"]["revision"],
                           "files": run.get("base_files", {})},
            "environment": {"python": platform.python_version(), "platform": platform.platform(),
                            "gpu": run.get("gpu"), "dtype": run.get("dtype"), "libraries": library_versions(),
                            "pinned": pinned_versions()},
            "run": {"seed": recipe["training"]["seed"], "train_seconds": run.get("train_seconds"),
                    "steps": run.get("steps"), "losses": run.get("losses", [])},
            "outputs": {"adapter": run.get("adapter"), "gguf": run.get("gguf")}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--recipe", default=str(receipt.RECIPE))
    parser.add_argument("--set", default=str(check_set.DEFAULT_SET))
    parser.add_argument("--out", default="training-output", help="folder for the adapter, models and receipt")
    parser.add_argument("--dry-run", action="store_true", help="check and plan only; needs no GPU or library")
    args = parser.parse_args(argv)
    the_plan, problems = plan(Path(args.recipe), Path(args.set))
    print(f"recipe {the_plan['recipe']['name']} ({the_plan['recipe_sha256'][:12]}), "
          f"training set {the_plan['cases']} cases ({the_plan['training_set_sha256'][:12]}), "
          f"{the_plan['train']} train and {the_plan['eval']} eval examples ({the_plan['rendered_sha256'][:12]}), "
          f"base {the_plan['recipe']['base_model']['repo']}@{the_plan['recipe']['base_model']['revision'][:12]}")
    for problem in problems:
        print(f"problem: {problem}")
    if problems:
        print("STOPPED: nothing was trained")
        return 1
    if args.dry_run:
        print("DRY RUN: the checks passed; nothing was trained")
        return 0
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "examples.jsonl").write_text(the_plan["rendered_text"], encoding="utf-8")
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        run, error = train(the_plan, out), None
    except Exception as exc:  # the receipt records a failed run too
        run, error = None, f"{type(exc).__name__}: {exc}"[:500]
    record = build_receipt(the_plan, run, error, started_at)
    path = out / "training_receipt.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"receipt {path} ({record['status']}), sha256 {receipt.sha256_file(path)}")
    for problem in receipt.validate(record):
        print(f"receipt problem: {problem}")
    return 0 if record["status"] == "COMPLETED" and not receipt.validate(record) else 1


if __name__ == "__main__":
    sys.exit(main())
