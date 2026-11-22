"""Turn a training set into chat examples with the serving code itself (own-model track T3, ADR-037).

The biggest risk to a fine-tuned model is training it on text that differs from what it sees at run time: another
system text, another wrapping of the case, another answer layout. So nothing here writes a prompt by hand. Each
example's system and user messages are exactly what the ``local`` provider sends for that case
(``providers.openai_compat.build_request_body`` with the prompt file, its answer-format words and ``user_message``,
on the text ``mask()`` returns), and the assistant message is the answer as JSON, its fields in the order of the
prompt's answer schema. ``tests/test_training_recipe.py`` compares every example with a fresh serving request, byte
for byte, and fails if anyone builds a message another way.

Output: one JSON object per line, ``{"case_id": …, "split": "train" | "eval", "messages": [system, user, assistant]}``.
A fixed share of the cases (``eval_share`` in the recipe, chosen by each case id's SHA-256, never by hand) is held
out to watch the training loss; the real exam is T4's, on sets the model never sees.

Run: ``python -m training.render --out examples.jsonl`` (prints the count and the file's SHA-256).
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys

from app.llm.config import DEFAULT_MODELS, LLMConfig
from app.llm.prompts import load_prompt
from app.llm.providers.openai_compat import build_request_body
from app.llm.redaction import mask

from . import check_set

SERVING_PROVIDER = "local"  # how our own model is served (ADR-026)


def serving_messages(summary, prompt=None):
    """The system and user messages the ``local`` provider sends for this case text, as it sends them."""
    prompt = prompt or load_prompt(check_set.PROMPT_ID)
    config = LLMConfig(provider=SERVING_PROVIDER, model=DEFAULT_MODELS[SERVING_PROVIDER])
    body = build_request_body(config, prompt, mask(summary).text)
    return body["messages"]


def answer_text(case, prompt=None):
    """The answer the model should give, as JSON with the schema's field order."""
    prompt = prompt or load_prompt(check_set.PROMPT_ID)
    return json.dumps({field: case[field] for field in prompt.output_schema["properties"]}, ensure_ascii=False)


def split_of(case_id, eval_share):
    """``eval`` for a fixed share of the cases, by the case id's SHA-256 (stable across runs and machines)."""
    bucket = int(hashlib.sha256(case_id.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "eval" if bucket < eval_share else "train"


def examples(cases, eval_share):
    prompt = load_prompt(check_set.PROMPT_ID)
    for case in cases:
        messages = serving_messages(case["summary"], prompt)
        messages.append({"role": "assistant", "content": answer_text(case, prompt)})
        yield {"case_id": case["case_id"], "split": split_of(case["case_id"], eval_share), "messages": messages}


def render(set_path, eval_share):
    """``(lines, sha256)``: the JSONL text of every example and its SHA-256."""
    cases = check_set.load_set(set_path)["cases"]
    text = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in examples(cases, eval_share))
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--set", default=str(check_set.DEFAULT_SET))
    parser.add_argument("--eval-share", type=float, default=None, help="default: the recipe's")
    parser.add_argument("--out", required=True, help="where to write the JSONL examples")
    args = parser.parse_args(argv)
    from .receipt import load_recipe  # here, so render works on its own in tests
    share = args.eval_share if args.eval_share is not None else load_recipe()["training"]["eval_share"]
    text, digest = render(args.set, share)
    Path(args.out).write_text(text, encoding="utf-8")
    counts = {split: text.count(f'"split": "{split}"') for split in ("train", "eval")}
    print(f"{sum(counts.values())} examples ({counts['train']} train, {counts['eval']} eval), sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
