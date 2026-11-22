"""The training recipe and the training receipt (own-model track T3, ADR-037).

* **The recipe** (``training/recipe_v1.json``) pins one round of training: the training set by its SHA-256, the base
  model by repository and revision, the QLoRA settings, the seed, how the result is exported (merged, then a GGUF
  file built with the local lane's pinned llama.cpp commit) and how it must be served (thinking off, greedy
  decoding: the local lane's flags). A changed recipe is a new recipe version.
* **The serving contract** is what the trained model will be asked with: the prompt id and SHA-256, the answer-format
  words, the masking rules and the gateway's answer checks (the parts of an AI agent's version, rule 5). The training
  script writes it into the receipt; :func:`serving_mismatches` compares a receipt with the service as it is now, so
  T4 can refuse to examine or serve a model that was trained for another prompt or other checks.
* **The receipt** (``training_receipt.json``, written by ``training/train_qlora.py`` where training runs) names every
  input and output by SHA-256: recipe, training set, rendered examples, base model files, library versions, the GPU,
  the losses, the adapter and the GGUF file with its model id ``<name>:<first 12 hex digits>`` (ADR-026).
  :func:`validate` checks one before anything trusts it.

Standard library and the app's contracts only (rule 8).
"""

import hashlib
import json
from pathlib import Path
import re

from app.llm.config import ANSWER_CHECKS_VERSION, ANSWER_FORMATS
from app.llm.prompts import load_prompt
from app.llm.redaction import REDACTION_VERSION

from . import check_set

ROOT = Path(__file__).resolve().parent.parent
RECIPE = ROOT / "training" / "recipe_v1.json"
RECIPE_SCHEMA = "neuron-flow-training-recipe-v1"
RECEIPT_SCHEMA = "neuron-flow-training-receipt-v1"
SERVING_PROVIDER = "local"
STATUSES = ("COMPLETED", "FAILED")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_MODEL_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def load_recipe(path=RECIPE):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != RECIPE_SCHEMA:
        raise ValueError(f"{path} is not a recipe of schema {RECIPE_SCHEMA}")
    return data


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def serving_contract():
    """What the service asks a model with today: the AI agent version's parts that training must match."""
    prompt = load_prompt(check_set.PROMPT_ID)
    return {"prompt_id": prompt.id, "prompt_sha256": prompt.sha256, "answer_format": ANSWER_FORMATS[SERVING_PROVIDER],
            "redaction": REDACTION_VERSION, "checks": ANSWER_CHECKS_VERSION, "provider": SERVING_PROVIDER}


def check_recipe(recipe):
    """Problems with a recipe (an empty list when it can be used)."""
    problems = []
    task, base, qlora = recipe.get("task", {}), recipe.get("base_model", {}), recipe.get("qlora", {})
    train, export, serving = recipe.get("training", {}), recipe.get("export", {}), recipe.get("serving", {})
    if task.get("prompt_id") != check_set.PROMPT_ID:
        problems.append(f"task.prompt_id must be {check_set.PROMPT_ID}")
    set_path = ROOT / task.get("training_set", "")
    if not set_path.is_file():
        problems.append("task.training_set must name a committed training set")
    elif sha256_file(set_path) != task.get("training_set_sha256"):
        problems.append("task.training_set_sha256 is not the training set's SHA-256 (approve the new set first)")
    if not isinstance(base.get("repo"), str) or "/" not in base.get("repo", ""):
        problems.append("base_model.repo must be owner/name")
    if not _HEX40.fullmatch(str(base.get("revision", ""))):
        problems.append("base_model.revision must be a full 40-digit commit")
    if recipe.get("chat_template_kwargs") != {"enable_thinking": False}:
        problems.append("chat_template_kwargs must turn thinking off, as the local lane serves (--reasoning off)")
    if not (isinstance(qlora.get("lora_r"), int) and 1 <= qlora["lora_r"] <= 256):
        problems.append("qlora.lora_r must be a whole number from 1 to 256")
    if not (isinstance(train.get("epochs"), int) and 1 <= train["epochs"] <= 20):
        problems.append("training.epochs must be a whole number from 1 to 20")
    if not (isinstance(train.get("learning_rate"), (int, float)) and 0 < train["learning_rate"] < 0.01):
        problems.append("training.learning_rate must be above 0 and below 0.01")
    if not (isinstance(train.get("eval_share"), (int, float)) and 0 <= train["eval_share"] <= 0.3):
        problems.append("training.eval_share must be from 0 to 0.3")
    if not isinstance(train.get("seed"), int):
        problems.append("training.seed must be a whole number")
    if train.get("loss_on") != "assistant_only":
        problems.append("training.loss_on must be assistant_only: the model learns the answers, not the prompt")
    if not _MODEL_NAME.fullmatch(str(export.get("model_name", ""))):
        problems.append("export.model_name must be lower case letters, digits, '.', '_' or '-'")
    if export.get("gguf_quant") != "Q4_K_M":
        problems.append("export.gguf_quant must be Q4_K_M, as the local lane serves")
    if not _HEX40.fullmatch(str(export.get("llama_cpp_commit", ""))):
        problems.append("export.llama_cpp_commit must be a full 40-digit commit")
    if serving.get("reasoning") != "off" or serving.get("temperature") != 0:
        problems.append("serving must keep thinking off and temperature 0 (greedy), as the local lane does")
    return problems


def validate(receipt):
    """Problems with a training receipt (an empty list when every field is present and consistent)."""
    problems = []
    if not isinstance(receipt, dict) or receipt.get("schema") != RECEIPT_SCHEMA:
        return [f"not a receipt of schema {RECEIPT_SCHEMA}"]
    if receipt.get("status") not in STATUSES:
        problems.append(f"status must be one of {', '.join(STATUSES)}")
    for path in ("recipe.sha256", "training_set.sha256", "rendered.sha256"):
        section, field = path.split(".")
        if not _HEX64.fullmatch(str((receipt.get(section) or {}).get(field, ""))):
            problems.append(f"{path} must be a SHA-256")
    contract = receipt.get("serving_contract")
    if not isinstance(contract, dict) or set(contract) != set(serving_contract()):
        problems.append("serving_contract must hold exactly " + ", ".join(sorted(serving_contract())))
    base = receipt.get("base_model") or {}
    if not _HEX40.fullmatch(str(base.get("revision", ""))):
        problems.append("base_model.revision must be a full 40-digit commit")
    if not isinstance((receipt.get("environment") or {}).get("libraries"), dict):
        problems.append("environment.libraries must give each library's version")
    if receipt.get("status") == "COMPLETED":
        if not isinstance(base.get("files"), dict) or not base["files"] or not all(
                _HEX64.fullmatch(str(value)) for value in base["files"].values()):
            problems.append("base_model.files must give every downloaded file's SHA-256")
        gguf = (receipt.get("outputs") or {}).get("gguf") or {}
        digest = str(gguf.get("sha256", ""))
        if not _HEX64.fullmatch(digest):
            problems.append("outputs.gguf.sha256 must be a SHA-256")
        elif gguf.get("model_id") != f"{gguf.get('name')}:{digest[:12]}":
            problems.append("outputs.gguf.model_id must be <name>:<first 12 hex digits of its SHA-256>")
        if not isinstance(gguf.get("bytes"), int) or gguf["bytes"] <= 0:
            problems.append("outputs.gguf.bytes must be the file's size")
        if not _HEX64.fullmatch(str(((receipt.get("outputs") or {}).get("adapter") or {}).get("sha256", ""))):
            problems.append("outputs.adapter.sha256 must be a SHA-256")
    return problems


def serving_mismatches(receipt, contract=None):
    """How the service today differs from what the model was trained for: ``[(field, trained, now)]``."""
    contract = contract or serving_contract()
    trained = receipt.get("serving_contract") or {}
    return [(field, trained.get(field), value) for field, value in contract.items() if trained.get(field) != value]
