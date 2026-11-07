"""Build (or verify) the open-dataset part of the robustness set from pinned upstream files.

Standard library only, and it imports nothing from this repository, so it can run isolated
(``python -I``) on files downloaded from the internet.

Flow:
1. every upstream file is pinned by repository, commit and path (``SOURCES`` below);
2. ``build --clones DIR`` reads shallow clones in ``DIR/<owner>_<repo>/repo`` (each must be at the pinned
   commit), records each file's SHA-256 and writes ``open_extract_v1.json`` deterministically;
3. ``verify`` downloads every recorded file from ``raw.githubusercontent.com`` at the pinned commit, checks
   its SHA-256, rebuilds the extract from those bytes and compares it with the committed file. Exit 1 on
   any difference. Use it when a source is questioned, or before changing the extract.

What is taken (selection rules are code, so the same upstream files always give the same extract):
* BLNS (MIT): every string of ``blns.json``;
* JSONTestSuite (MIT): every file in ``test_parsing/`` (y_ must be accepted, n_ rejected, i_ either way),
  stored zlib-compressed and base64-encoded because many are not valid UTF-8 on purpose;
* CLINC150 (CC BY 3.0) and BANKING77 (CC BY 4.0): short English requests, re-labelled into this project's
  four triage categories by ``CLINC_MAP`` / ``BANKING_MAP``. Those labels are the developer's mapping, not the
  datasets' own labels (a change under the licences' attribution terms, stated in NOTICE.md).
"""

import argparse
import base64
import csv
import hashlib
import io
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "open_extract_v1.json"

SOURCES = {
    "blns": {"name": "Big List of Naughty Strings", "repo": "minimaxir/big-list-of-naughty-strings",
             "commit": "db33ec7b1d5d9616a88c76394b7d0897bd0b97eb", "license": "MIT",
             "copyright": "Copyright (c) 2015-2020 Max Woolf", "paths": ["blns.json"]},
    "jsontestsuite": {"name": "JSON Parsing Test Suite", "repo": "nst/JSONTestSuite",
                      "commit": "1ef36fa01286573e846ac449e8683f8833c5b26a", "license": "MIT",
                      "copyright": "Copyright (c) 2016 Nicolas Seriot", "paths": ["test_parsing/"]},
    "clinc150": {"name": "CLINC150 (An Evaluation Dataset for Intent Classification and Out-of-Scope Prediction)",
                 "repo": "clinc/oos-eval", "commit": "828f8093932c8fe6ca7936c3d2e52903b1c523de",
                 "license": "CC BY 3.0", "copyright": "Larson et al., EMNLP 2019 (Clinc)",
                 "paths": ["data/data_full.json"]},
    "banking77": {"name": "BANKING77", "repo": "PolyAI-LDN/task-specific-datasets",
                  "commit": "57ec275d8078af65b7731c2a98be812d844a6d6b", "license": "CC BY 4.0",
                  "copyright": "Casanueva et al., 2020 (PolyAI)", "paths": ["banking_data/test.csv"]},
}

# Words that trigger the v1 keyword rules (app/domains/case_triage/agents.py) on 2026-11-07. Used only to pick
# open requests that are likely edge cases for those rules; the benchmark itself runs the real rules.
TRIGGER_WORDS = ("password", "sign in", "login", "account access", "upload", "attachment", "file transfer",
                 "payment", "billing", "invoice")

# Our four categories for a generic online-service help desk: access (signing in, passwords, PINs, blocked
# accounts, identity checks to get in), upload (sending or attaching files), billing (paying us, being charged,
# refunds, bills), other (everything else). Intents not listed map to "other" (CLINC150 only).
CLINC_MAP = {"account_blocked": "access", "pin_change": "access",
             "pay_bill": "billing", "bill_due": "billing", "bill_balance": "billing", "min_payment": "billing",
             "card_declined": "billing"}
BANKING_MAP = {"passcode_forgotten": "access", "pin_blocked": "access", "change_pin": "access",
               "unable_to_verify_identity": "access",
               "declined_card_payment": "billing", "card_payment_fee_charged": "billing",
               "transaction_charged_twice": "billing", "request_refund": "billing",
               "Refund_not_showing_up": "billing", "extra_charge_on_statement": "billing",
               "direct_debit_payment_not_recognised": "billing",
               "card_arrival": "other", "atm_support": "other", "exchange_rate": "other", "age_limit": "other",
               "lost_or_stolen_phone": "other", "terminate_account": "other"}
PER_INTENT = 2   # the first N requests (file order) of each explicitly mapped intent
OOS_FIRST = 6    # the first N out-of-scope test requests of CLINC150


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def pack(data):
    return base64.b64encode(zlib.compress(data, 9)).decode("ascii")


def unpack(text):
    return zlib.decompress(base64.b64decode(text))


def _triggered(text):
    lowered = text.lower()
    return [word for word in TRIGGER_WORDS if word in lowered]


def extract(files):
    """``files``: {source_id: {path: bytes}} -> the extract document (deterministic)."""
    manifest = {source_id: {path: sha256(data) for path, data in sorted(found.items())}
                for source_id, found in files.items()}
    blns = json.loads(files["blns"]["blns.json"].decode("utf-8"))
    suite = []
    for path, data in sorted(files["jsontestsuite"].items()):
        name = path.rsplit("/", 1)[-1]
        expect = {"y_": "accept", "n_": "reject", "i_": "either"}[name[:2]]
        suite.append({"name": name, "expect": expect, "sha256": sha256(data), "bytes": len(data),
                      "data_z": pack(data)})
    labelled = []
    clinc = json.loads(files["clinc150"]["data/data_full.json"].decode("utf-8"))
    picked = set()

    def add(source, split, index, text, intent, label, rule):
        key = (source, split, index)
        if key in picked:
            return
        picked.add(key)
        labelled.append({"id": f"{source.upper()}-{split}-{index:04d}", "source": source, "split": split,
                         "index": index, "text": text, "source_intent": intent, "label": label,
                         "selected_by": rule, "triggers": _triggered(text)})

    for split in ("test", "oos_test"):
        for index, (text, intent) in enumerate(clinc[split]):
            if _triggered(text):
                add("clinc150", split, index, text, intent, CLINC_MAP.get(intent, "other"), "contains_trigger_word")
    counts = {}
    for index, (text, intent) in enumerate(clinc["test"]):
        if intent in CLINC_MAP and counts.get(intent, 0) < PER_INTENT:
            counts[intent] = counts.get(intent, 0) + 1
            add("clinc150", "test", index, text, intent, CLINC_MAP[intent], f"first_{PER_INTENT}_of_mapped_intent")
    for index, (text, intent) in enumerate(clinc["oos_test"][:OOS_FIRST]):
        add("clinc150", "oos_test", index, text, intent, "other", f"first_{OOS_FIRST}_out_of_scope")
    rows = list(csv.DictReader(io.StringIO(files["banking77"]["banking_data/test.csv"].decode("utf-8"))))
    counts = {}
    for index, row in enumerate(rows):
        intent = row["category"]
        if intent in BANKING_MAP and counts.get(intent, 0) < PER_INTENT:
            counts[intent] = counts.get(intent, 0) + 1
            add("banking77", "test", index, row["text"].strip(), intent, BANKING_MAP[intent],
                f"first_{PER_INTENT}_of_mapped_intent")
    sources = [{"id": source_id, **{k: v for k, v in meta.items() if k != "paths"},
                "files": [{"path": path, "sha256": digest} for path, digest in manifest[source_id].items()]}
               for source_id, meta in SOURCES.items()]
    return {"schema": "neuron-flow-robustness-open-v1",
            "note": "Generated by tests/robustness/build_open_extract.py from pinned upstream files; do not edit by "
                    "hand. Licences and attribution: tests/robustness/NOTICE.md. Labels of CLINC150 and BANKING77 "
                    "requests are this project's mapping, not the datasets' own labels.",
            "sources": sources,
            "mappings": {"clinc150": CLINC_MAP, "banking77": BANKING_MAP, "default_clinc150": "other",
                         "trigger_words": list(TRIGGER_WORDS)},
            "corpora": {"blns": blns, "jsontestsuite": suite},
            "labelled": labelled}


def dump(document):
    return (json.dumps(document, ensure_ascii=False, indent=1, sort_keys=False) + "\n").encode("utf-8")


def read_clones(clones):
    files = {}
    for source_id, meta in SOURCES.items():
        root = Path(clones) / meta["repo"].replace("/", "_") / "repo"
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
        if head != meta["commit"]:
            raise SystemExit(f"{meta['repo']} is at {head}, expected the pinned {meta['commit']}")
        found = {}
        for path in meta["paths"]:
            target = root / path
            if path.endswith("/"):
                for item in sorted(target.iterdir()):
                    if item.is_file() and item.name[:2] in ("y_", "n_", "i_"):
                        found[path + item.name] = item.read_bytes()
            else:
                found[path] = target.read_bytes()
        files[source_id] = found
    return files


def download(committed):
    files = {}
    for source in committed["sources"]:
        found = {}
        for item in source["files"]:
            url = (f"https://raw.githubusercontent.com/{source['repo']}/{source['commit']}/"
                   + urllib.parse.quote(item["path"]))
            try:
                with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 (fixed https host)
                    data = response.read()
            except urllib.error.URLError as exc:
                raise SystemExit(f"{url}: download failed ({exc})") from None
            if sha256(data) != item["sha256"]:
                raise SystemExit(f"{url}: SHA-256 differs from the pinned value")
            found[item["path"]] = data
        files[source["id"]] = found
    return files


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="write the extract from local clones at the pinned commits")
    build.add_argument("--clones", required=True)
    build.add_argument("--out", default=str(OUT))
    sub.add_parser("verify", help="download the pinned files and compare with the committed extract")
    args = parser.parse_args(argv)
    if args.command == "build":
        Path(args.out).write_bytes(dump(extract(read_clones(args.clones))))
        print(f"wrote {args.out}")
        return 0
    committed_bytes = OUT.read_bytes()
    rebuilt = dump(extract(download(json.loads(committed_bytes))))
    if rebuilt != committed_bytes:
        print("The committed extract differs from one rebuilt from the pinned upstream files.")
        return 1
    print("OK: every upstream file matches its pinned SHA-256, and the extract rebuilds byte for byte.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
