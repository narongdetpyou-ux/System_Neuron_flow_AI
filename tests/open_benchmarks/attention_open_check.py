"""Attention signals against open data nobody here wrote: a development half and a sealed half (ADR-032).

The phrase lists of ``app/domains/case_triage/signals.py`` find the wording they list. To improve them without
fooling ourselves, the pinned open files (``build_sets.py``; nothing downloaded is committed) are split by fixed
rules that were written before either half was read:

* **Security matters, by the datasets' own intent labels** (independent of this project):
  - BANKING77 ``test.csv``, intents ``SECURITY_BANKING``: a row is *development* when the first hex digit of
    the SHA-256 of its text is even, *sealed* when it is odd;
  - CLINC150, intents ``SECURITY_CLINC``: the ``train`` split is development, the ``test`` split is sealed.
* **Ordinary requests** (every other intent of the same files, and CLINC150's out-of-scope requests), split
  the same way: how often a signal is raised where the label says no security matter.
* **BIPIA's 75 text attacks**, 5 per category: positions 0, 2 and 4 of each category are development (45),
  positions 1 and 3 are sealed (30).

Rows of the 300-request BANKING77 sample that signals-v1 was measured on (and partly read) are left out of the
sealed half and counted on their own line, so the sealed figures are about text that was never looked at.

``--part development`` may list misses and needless flags (``--show``), for writing phrases. ``--part sealed``
prints counts only, never a text: measure it once per signals version, and never add a phrase because of it.

Run: ``python -m tests.open_benchmarks.attention_open_check --cache ~/open-bench-cache --part development``
"""

import argparse
import csv
import hashlib
import io
import json
import sys

from app.domains.case_triage.signals import find_signals, signal_version

from . import build_sets

SECURITY_BANKING = ("compromised_card", "lost_or_stolen_card", "lost_or_stolen_phone",
                    "card_payment_not_recognised", "direct_debit_payment_not_recognised",
                    "cash_withdrawal_not_recognised")
SECURITY_CLINC = ("report_fraud", "report_lost_card", "freeze_account")
PARTS = ("development", "sealed")


def _half(text):
    return PARTS[int(hashlib.sha256(text.encode("utf-8")).hexdigest()[0], 16) % 2]


def rows(files):
    """Every row as ``{source, part, kind, label, text}``; ``kind`` is security, ordinary, injection or sampled."""
    sources = build_sets.SOURCES
    out = []
    banking = files["banking77"][sources["banking77"]["path"]]
    sampled = {case["summary"] for case in build_sets.banking_cases(banking)}
    for row in csv.DictReader(io.StringIO(banking.decode("utf-8"))):
        text, intent = row["text"], row["category"]
        if not build_sets.usable(text):
            continue
        kind = "security" if intent in SECURITY_BANKING else "ordinary"
        part = _half(text)
        if part == "sealed" and text in sampled:
            kind = "sampled_" + kind  # measured (and partly read) with signals-v1: not sealed any more
        out.append({"source": "banking77", "part": part, "kind": kind, "label": intent, "text": text})
    clinc = json.loads(files["clinc150"][sources["clinc150"]["path"]])
    for split, part in (("train", "development"), ("test", "sealed")):
        for text, intent in clinc[split]:
            if build_sets.usable(text):
                out.append({"source": "clinc150", "part": part, "label": intent, "text": text,
                            "kind": "security" if intent in SECURITY_CLINC else "ordinary"})
        for text, _ in clinc["oos_" + split]:
            if build_sets.usable(text):
                out.append({"source": "clinc150", "part": part, "label": "out_of_scope", "text": text,
                            "kind": "ordinary"})
    bipia = json.loads(files["bipia"][sources["bipia"]["path"]])
    for category, attacks in bipia.items():
        for position, text in enumerate(attacks):
            out.append({"source": "bipia", "part": "development" if position % 2 == 0 else "sealed",
                        "kind": "injection", "label": category, "text": text})
    return out


def measure(items, part):
    """Counts for one part: per source and kind, how many rows had a signal of the kind that matters."""
    result = {}
    for item in items:
        if item["part"] != part:
            continue
        found = find_signals(item["text"])["signals"]
        wanted = "instruction" if item["kind"] == "injection" else "security"
        key = (item["source"], item["kind"])
        entry = result.setdefault(key, {"rows": 0, "wanted_signal": 0, "any_signal": 0, "by_label": {}})
        entry["rows"] += 1
        entry["wanted_signal"] += wanted in found
        entry["any_signal"] += bool(found)
        label = entry["by_label"].setdefault(item["label"], [0, 0])
        label[0] += 1
        label[1] += bool(found) if item["kind"].endswith("ordinary") else wanted in found
        item["found"] = found
    return result


def report(result, part):
    lines = [f"signals {signal_version()[:23]}… · part: {part}", ""]
    for (source, kind), entry in sorted(result.items()):
        what = "any signal (needless)" if kind.endswith("ordinary") else "the wanted signal"
        count = entry["any_signal"] if kind.endswith("ordinary") else entry["wanted_signal"]
        lines.append(f"{source:10} {kind:17} {count}/{entry['rows']} rows with {what}")
        if not kind.endswith("ordinary"):
            lines += [f"    {label}: {hit}/{total}" for label, (total, hit) in sorted(entry["by_label"].items())]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", help="folder of downloaded sources, named by SHA-256 (as build_sets.py)")
    parser.add_argument("--part", choices=PARTS, required=True)
    parser.add_argument("--show", action="store_true",
                        help="development only: list the misses and the needless flags, for writing phrases")
    parser.add_argument("--out", help="write the counts as JSON here (no text)")
    args = parser.parse_args(argv)
    if args.show and args.part != "development":
        parser.error("--show is for the development part only; the sealed part is never read")
    files = build_sets.fetch(args.cache)
    items = rows(files)
    result = measure(items, args.part)
    print(report(result, args.part))
    if args.show:
        for item in items:
            if item["part"] != "development":
                continue
            ordinary = item["kind"].endswith("ordinary")
            wanted = "instruction" if item["kind"] == "injection" else "security"
            if (ordinary and item["found"]) or (not ordinary and wanted not in item["found"]):
                print(f"{'FLAG' if ordinary else 'MISS'} {item['source']} {item['label']} {item['found']} "
                      f"{item['text'][:160]!r}")
    if args.out:
        document = {"schema": "neuron-flow-attention-open-check-v1", "signals": signal_version(), "part": args.part,
                    "counts": [{"source": source, "kind": kind, **entry,
                                "by_label": {label: {"rows": total, "found": hit}
                                             for label, (total, hit) in sorted(entry["by_label"].items())}}
                               for (source, kind), entry in sorted(result.items())]}
        with open(args.out, "w", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=1, sort_keys=True)
            stream.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
