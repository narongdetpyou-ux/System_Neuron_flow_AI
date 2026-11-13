"""Which of this repository's triage cases appear in a fine-tune's training data (ADR-034)?

A model scored on cases it was trained on looks better than it is. This compares every case of the five triage sets
with the training (and validation) examples, after normalizing text (NFKC, case, spaces, invisible characters):

* ``exact``: the case's text appears inside a training text;
* ``near``: at least ``--near`` (default 0.8) of the case's character 5-grams appear in one training text, which
  catches light edits.

The training data can be JSON Lines, one JSON document, or plain text; every string in it is read, and so is any JSON
object written inside a string (a prompt that embeds ``{"case_text": ...}``). It may come from a file
(``--training``, repeatable) or from a link in an environment variable (``--url-env NF_TRAINING_URL``, a repository
secret; a Google Drive share link works as for the model file, and the link is never printed).

What it writes says nothing about the training data except its size, its SHA-256 and how many texts it holds: per
set, the number of cases found and their ids (this repository's own, public ids). ``--ids-out`` writes those ids for
``tests/local_model_compare.py --training-cases``. Run with ``python -m tests.training_overlap``.
"""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import unicodedata

ROOT = Path(__file__).resolve().parent.parent
SETS = {"case_triage_synthetic_v1": "app/eval/golden/case_triage_synthetic_v1.json",
        "triage_edge_robustness_v1": "tests/robustness/triage_edge_golden_v1.json",
        "case_triage_heldout_v1": "app/eval/golden/case_triage_heldout_v1.json",
        "case_triage_autosend_hard_v1": "app/eval/golden/case_triage_autosend_hard_v1.json",
        "case_triage_attention_heldout_v1": "app/eval/golden/case_triage_attention_heldout_v1.json"}
INVISIBLE = re.compile(r"[​-‏⁠﻿­]")
GRAM = 5
MAX_BYTES = 50_000_000


def normalize(text):
    text = INVISIBLE.sub("", unicodedata.normalize("NFKC", text)).casefold()
    return " ".join(text.split())


def grams(text):
    return {text[i:i + GRAM] for i in range(max(1, len(text) - GRAM + 1))}


def strings(value):
    """Every string in a JSON value, and the strings of any JSON object written inside one."""
    if isinstance(value, str):
        yield value
        for line in value.splitlines():
            start, end = line.find("{"), line.rfind("}")
            if start != -1 and end > start:
                try:
                    inner = json.loads(line[start:end + 1])
                except ValueError:
                    continue
                if not isinstance(inner, str):
                    yield from strings(inner)
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def training_texts(raw):
    """The normalized texts of one training file (JSON Lines, one JSON document, or plain text)."""
    text = raw.decode("utf-8-sig", errors="replace")
    found = []
    try:
        found = list(strings(json.loads(text)))
    except ValueError:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                found += list(strings(json.loads(line)))
            except ValueError:
                found.append(line)
    return [t for t in dict.fromkeys(normalize(s) for s in found) if len(t) >= 8]


def overlap(texts, near=0.8, sets=SETS):
    indexed = [(t, grams(t)) for t in texts]
    result = {}
    for name, relative in sets.items():
        cases = json.loads((ROOT / relative).read_text(encoding="utf-8"))["cases"]
        exact, close, scores = [], [], {}
        for case in cases:
            wanted = normalize(case["summary"])
            if any(wanted in text for text, _ in indexed):
                exact.append(case["case_id"])
                continue
            mine = grams(wanted)
            best = max((len(mine & theirs) / len(mine) for _text, theirs in indexed), default=0.0)
            if best >= near:
                close.append(case["case_id"])
                scores[case["case_id"]] = round(best, 3)
        result[name] = {"cases": len(cases), "exact": exact, "near": close, "near_scores": scores}
    return result


def fetch(url):
    """A small file from a private link (Google Drive share links work), with the model fetcher's rules."""
    spec = importlib.util.spec_from_file_location("fetch_model", ROOT / ".github" / "scripts" / "fetch_model.py")
    fetch_model = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fetch_model)
    address, kind, file_id = fetch_model.download_address(url)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        for value in (url, address, file_id):
            if value:
                print(f"::add-mask::{value}", flush=True)
    for _ in range(2):
        with fetch_model._open(address, 60) as response:
            raw = response.read(MAX_BYTES + 1)
            html = (response.headers.get("content-type") or "").lower().startswith("text/html")
        if len(raw) > MAX_BYTES:
            raise SystemExit("the training data is larger than 50 MB")
        if not html:
            return raw
        following = fetch_model._next_from_page(raw.decode("utf-8", "replace"), address, fetch_model.DRIVE_DOWNLOAD) \
            if kind == "google_drive" else None
        if following is None:
            raise SystemExit("the link answered with a web page, not the file (is it shared with \"Anyone with the link\"?)")
        address = following
    raise SystemExit("the link answered with a web page twice")


def markdown(document):
    lines = ["## เคสทดสอบที่อยู่ในข้อมูลฝึกด้วยหรือไม่ (training data overlap)", "",
             f"ข้อมูลฝึก {document['training']['bytes']:,} bytes, SHA-256 `{document['training']['sha256'][:16]}…`, "
             f"{document['training']['texts']} ข้อความ (ไม่แสดงเนื้อหา) · near = 5-gram ซ้ำอย่างน้อย {document['near']:.0%}", "",
             "| ชุดเคส | เคส | พบตรงทั้งข้อความ | พบใกล้เคียง |", "|---|---|---|---|"]
    for name, row in document["sets"].items():
        lines.append(f"| `{name}` | {row['cases']} | {len(row['exact'])} | {len(row['near'])} |")
    found = [(name, case_id) for name, row in document["sets"].items() for case_id in row["exact"] + row["near"]]
    if found:
        lines += ["", "เคสที่พบ (เป็นรหัสเคสของ repo นี้): " + ", ".join(f"`{c}`" for _n, c in found[:60])
                  + (" …" if len(found) > 60 else ""),
                  "", "> คะแนนของชุดที่มีเคสเหล่านี้สูงเกินจริงได้ ให้ดูตัวเลขแบบไม่นับเคสที่พบในตารางเทียบโมเดล  ",
                  "> *Scores on these cases can be inflated; read the comparison's figures without them.*"]
    else:
        lines += ["", "ไม่พบเคสของ repo ในข้อมูลฝึกชุดนี้ (*no repository case found in this training data*)"]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--training", action="append", default=[], type=Path)
    parser.add_argument("--url-env", help="an environment variable that holds a link to the training data")
    parser.add_argument("--near", type=float, default=0.8)
    parser.add_argument("--json")
    parser.add_argument("--ids-out")
    parser.add_argument("--summary")
    args = parser.parse_args(argv)
    blobs = [path.read_bytes() for path in args.training]
    if args.url_env:
        url = os.environ.get(args.url_env, "").strip()
        if not url:
            print(f"{args.url_env} is not set: nothing to check")
            return 0
        blobs.append(fetch(url))
    if not blobs:
        parser.error("give --training FILE or --url-env NAME")
    joined = b"\n".join(blobs)
    texts = [t for blob in blobs for t in training_texts(blob)]
    document = {"schema": "neuron-flow-training-overlap-v1", "near": args.near,
                "training": {"bytes": len(joined), "sha256": hashlib.sha256(joined).hexdigest(), "texts": len(texts)},
                "sets": overlap(texts, args.near)}
    text = markdown(document)
    print(text)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as stream:
            stream.write(text)
    if args.json:
        Path(args.json).write_text(json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if args.ids_out:
        ids = sorted({c for row in document["sets"].values() for c in row["exact"] + row["near"]})
        Path(args.ids_out).write_text(json.dumps(ids) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
