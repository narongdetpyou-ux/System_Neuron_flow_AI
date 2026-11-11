"""Build the open-benchmark case sets (roadmap 5.6) from pinned public files, at run time.

Standard library only, and it imports nothing from this repository, so it can run isolated
(``python -I``) on files downloaded from the internet. Nothing it downloads is committed: the case files
are rebuilt on every run, and ``manifest_v1.json`` (committed) holds the SHA-256 of every source and of
every case file it builds, so a run can prove it used the same cases.

Flow:
1. every source is pinned: a GitHub file by repository, commit, path and SHA-256, the MASSIVE release
   archive by URL and SHA-256 (``SOURCES`` below);
2. ``build --out DIR`` downloads each source (or reuses ``--cache DIR``), refuses any file whose SHA-256
   differs, and reads only the members it needs from the archive, in memory;
3. it draws a fixed sample with a version-independent order (SHA-256 of a seed and each item's position, never
   ``random``), stratified by intent or scenario, and maps each item into this project's four triage
   categories with the tables below;
4. it writes four ``neuron-flow-golden-v1`` case files and a manifest; ``--check`` compares that manifest
   with the committed one and exits 1 on any difference.

The labels are this project's mapping into ``access``, ``upload``, ``billing`` and ``other``, not the
datasets' own labels, and the mapping is code so the same files always give the same cases. Intents whose
place among the four categories is open to argument (money transfers, top-ups, cash withdrawals, card
security) are left out rather than forced into one.

Sets (sizes are maxima; ``manifest_v1.json`` has the counts):
* CLINC150 (CC BY 3.0): 300 English requests: 100 out-of-scope, 15 from each of the 7 mapped intents and 95
  from the other in-scope intents, one per intent;
* BANKING77 (CC BY 4.0): 300 English requests, round-robin over the mapped intents;
* MASSIVE 1.1 (CC BY 4.0): 150 test utterances in ``th-TH`` with the same 150 in ``en-US`` (the same id, so a
  pair), round-robin over its 18 scenarios. Every one is an assistant request outside this help desk, so
  every one is ``other``; the pairs measure whether Thai and English get the same answer;
* BIPIA (MIT): its 75 test text attacks (indirect prompt injection), each placed at the start or the end of
  one of the 20 ``clear`` cases of the hard auto-send set, which keeps the case's label. The tag
  ``base:<case_id>`` names that case, so the simulator can compare the two answers.
"""

import argparse
import csv
import hashlib
import io
import json
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
MANIFEST = HERE / "manifest_v1.json"
HARD_SET = ROOT / "app" / "eval" / "golden" / "case_triage_autosend_hard_v1.json"
SEED = "neuron-flow-open-bench-v1"
# The admission contract (app/domains/case_triage/contracts.py), copied because this file imports nothing;
# tests/test_open_benchmarks.py keeps the two equal.
SUMMARY_MIN_CHARS = 8
SUMMARY_MAX_CHARS = 500

SOURCES = {
    "clinc150": {"name": "CLINC150", "license": "CC BY 3.0", "repo": "clinc/oos-eval",
                 "commit": "828f8093932c8fe6ca7936c3d2e52903b1c523de", "path": "data/data_full.json",
                 "sha256": "36923c3705a59e08fe9c3883d8bc2dd966ef93e22cb78ac41171782a698d56e0"},
    "banking77": {"name": "BANKING77", "license": "CC BY 4.0", "repo": "PolyAI-LDN/task-specific-datasets",
                  "commit": "57ec275d8078af65b7731c2a98be812d844a6d6b", "path": "banking_data/test.csv",
                  "sha256": "d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d"},
    "massive": {"name": "MASSIVE 1.1", "license": "CC BY 4.0",
                "url": "https://amazon-massive-nlu-dataset.s3.amazonaws.com/amazon-massive-dataset-1.1.tar.gz",
                "sha256": "4cba5faa11c71437928e17cb1b9b3d8b8e727e7ea363a3a9a8045e19c0491577",
                "members": ["1.1/data/en-US.jsonl", "1.1/data/th-TH.jsonl"]},
    "bipia": {"name": "BIPIA", "license": "MIT", "repo": "microsoft/BIPIA",
              "commit": "a004b69ec0dd446e0afd461d98cb5e96e120a5d0", "path": "benchmark/text_attack_test.json",
              "sha256": "75750e7b4e8b34e8f9d88d89b357aeaaf02bd07f9e493ccd37eda74a0cd7c7f8"},
}

# Our four categories for a generic online-service help desk (the triage prompt's definitions): access
# (signing in, passwords, PINs, locked accounts, verification codes, access rights), upload (sending or
# attaching files), billing (payments, charges, invoices, receipts, refunds, subscriptions), other.
CLINC_MAP = {"account_blocked": "access", "pin_change": "access",
             "pay_bill": "billing", "bill_due": "billing", "bill_balance": "billing", "min_payment": "billing",
             "card_declined": "billing"}
# Money movements and card security: arguable between billing, access and other, so not used.
CLINC_EXCLUDED = frozenset({
    "transfer", "transactions", "balance", "spending_history", "direct_deposit", "routing", "payday", "income",
    "taxes", "w2", "rollover_401k", "report_fraud", "freeze_account", "report_lost_card", "damaged_card",
    "new_card", "replacement_card_duration", "expiration_date", "credit_limit", "credit_limit_change", "apr",
    "interest_rate", "redeem_rewards", "rewards_balance", "international_fees", "user_name", "change_user_name",
    "order_checks"})
BANKING_MAP = {
    "passcode_forgotten": "access", "pin_blocked": "access", "change_pin": "access",
    "unable_to_verify_identity": "access",
    "declined_card_payment": "billing", "card_payment_fee_charged": "billing",
    "transaction_charged_twice": "billing", "request_refund": "billing", "Refund_not_showing_up": "billing",
    "extra_charge_on_statement": "billing", "direct_debit_payment_not_recognised": "billing",
    "card_payment_not_recognised": "billing", "transfer_fee_charged": "billing",
    "cash_withdrawal_charge": "billing", "top_up_by_card_charge": "billing",
    "top_up_by_bank_transfer_charge": "billing", "exchange_charge": "billing", "pending_card_payment": "billing",
    "reverted_card_payment?": "billing",
    "card_arrival": "other", "atm_support": "other", "exchange_rate": "other", "age_limit": "other",
    "lost_or_stolen_phone": "other", "terminate_account": "other", "country_support": "other",
    "supported_cards_and_currencies": "other", "visa_or_mastercard": "other", "card_delivery_estimate": "other",
    "order_physical_card": "other", "get_physical_card": "other", "getting_spare_card": "other",
    "getting_virtual_card": "other", "get_disposable_virtual_card": "other", "disposable_card_limits": "other",
    "card_about_to_expire": "other", "apple_pay_or_google_pay": "other", "edit_personal_details": "other",
    "fiat_currency_support": "other", "exchange_via_app": "other", "card_swallowed": "other",
    "activate_my_card": "other"}

CLINC_OOS, CLINC_PER_MAPPED, CLINC_OTHER = 100, 15, 95
BANKING_TOTAL = 300
MASSIVE_PAIRS = 150

LABEL_NOTE = ("The category is this project's mapping (tests/open_benchmarks/build_sets.py), not the dataset's "
              "own label, and its authors do not endorse it. Text written for the dataset, not real customer "
              "data and not independent ground truth.")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def order_key(*parts):
    """A fixed pseudo-random order that does not depend on the Python version."""
    return sha256(":".join((SEED, *map(str, parts))).encode("utf-8"))


def usable(text):
    return isinstance(text, str) and SUMMARY_MIN_CHARS <= len(text.strip()) <= SUMMARY_MAX_CHARS


def stratified(items, group, total, *salt):
    """Round-robin over groups (in a fixed order), each group's items in a fixed order, until ``total``."""
    groups = {}
    for item in items:
        groups.setdefault(group(item), []).append(item)
    queues = [sorted(members, key=lambda it: order_key(*salt, "item", it["_key"]))
              for _name, members in sorted(groups.items(), key=lambda kv: order_key(*salt, "group", kv[0]))]
    picked = []
    while len(picked) < total and any(queues):
        for queue in queues:
            if queue and len(picked) < total:
                picked.append(queue.pop(0))
    return picked


def _case(case_id, language, category, tags, text):
    return {"case_id": case_id, "language": language, "expected_category": category, "tags": tags,
            "summary": text.strip()}


def clinc_cases(data):
    clinc = json.loads(data.decode("utf-8"))
    rows = [{"_key": f"{split}:{index}", "split": split, "index": index, "text": text, "intent": intent}
            for split in ("test", "oos_test") for index, (text, intent) in enumerate(clinc[split])
            if usable(text)]
    oos = sorted((r for r in rows if r["split"] == "oos_test"), key=lambda r: order_key("clinc", "oos", r["_key"]))
    mapped = [r for r in rows if r["split"] == "test" and r["intent"] in CLINC_MAP]
    others = [r for r in rows if r["split"] == "test" and r["intent"] not in CLINC_MAP
              and r["intent"] not in CLINC_EXCLUDED]
    picked = (oos[:CLINC_OOS]
              + stratified(mapped, lambda r: r["intent"], CLINC_PER_MAPPED * len(CLINC_MAP), "clinc", "mapped")
              + stratified(others, lambda r: r["intent"], CLINC_OTHER, "clinc", "other"))
    cases = []
    for r in picked:
        out_of_scope = r["split"] == "oos_test"
        cases.append(_case(f"CLINC-{'oos' if out_of_scope else 'test'}-{r['index']:04d}", "en",
                           "other" if out_of_scope else CLINC_MAP.get(r["intent"], "other"),
                           ["clinc150", "out_of_scope" if out_of_scope else f"intent:{r['intent']}"], r["text"]))
    return cases


def banking_cases(data):
    reader = csv.DictReader(io.StringIO(data.decode("utf-8")))
    rows = [{"_key": str(index), "index": index, "text": row["text"], "intent": row["category"]}
            for index, row in enumerate(reader) if row["category"] in BANKING_MAP and usable(row["text"])]
    return [_case(f"B77-test-{r['index']:04d}", "en", BANKING_MAP[r["intent"]],
                  ["banking77", f"intent:{r['intent']}"], r["text"])
            for r in stratified(rows, lambda r: r["intent"], BANKING_TOTAL, "banking77")]


def massive_cases(en_lines, th_lines):
    def test_rows(lines):
        rows = {}
        for line in lines.decode("utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if row["partition"] == "test":
                    rows[row["id"]] = row
        return rows

    english, thai = test_rows(en_lines), test_rows(th_lines)
    pairs = [{"_key": key, "id": key, "scenario": thai[key]["scenario"], "intent": thai[key]["intent"]}
             for key in sorted(set(english) & set(thai), key=int)
             if usable(english[key]["utt"]) and usable(thai[key]["utt"])
             and english[key]["intent"] == thai[key]["intent"]]
    cases = []
    for pair in stratified(pairs, lambda p: p["scenario"], MASSIVE_PAIRS, "massive"):
        tags = ["massive", f"scenario:{pair['scenario']}", f"intent:{pair['intent']}", f"pair:massive-{pair['id']}"]
        cases.append(_case(f"MAS-TH-{int(pair['id']):05d}", "th", "other", tags, thai[pair["id"]]["utt"]))
        cases.append(_case(f"MAS-EN-{int(pair['id']):05d}", "en", "other", tags, english[pair["id"]]["utt"]))
    return cases


def _slug(text):
    return "".join(ch if ch.isalnum() else "_" for ch in text.lower()).strip("_")


def bipia_cases(data, bases):
    """Each attack, in file order, at the end (even) or the start (odd) of a base case, round-robin."""
    attacks = [(category, attack) for category, items in json.loads(data.decode("utf-8")).items()
               for attack in items]
    cases = []
    for number, (category, attack) in enumerate(attacks, 1):
        base = bases[(number - 1) % len(bases)]
        position = "end" if number % 2 else "start"
        text = f"{base['summary']} {attack}" if position == "end" else f"{attack} {base['summary']}"
        if not usable(text):
            continue
        cases.append(_case(f"BIPIA-{number:03d}", base["language"], base["expected_category"],
                           ["bipia", "open_injection", f"base:{base['case_id']}",
                            f"attack:{_slug(category)}", f"position:{position}"], text))
    return cases


def hard_set_bases(path=HARD_SET):
    document = json.loads(Path(path).read_bytes().decode("utf-8"))
    bases = [c for c in document["cases"] if "clear" in c["tags"]]
    if len(bases) != 20:
        raise SystemExit(f"{path}: expected 20 clear cases, found {len(bases)}")
    return bases


def golden(name, source_ids, scope, cases):
    sources = "; ".join(f"{SOURCES[s]['name']} ({SOURCES[s]['license']})" for s in source_ids)
    return {"schema": "neuron-flow-golden-v1", "name": name,
            "label_scope": f"{scope} Source: {sources}, pinned in tests/open_benchmarks/manifest_v1.json "
                           f"(licences in tests/open_benchmarks/NOTICE.md). {LABEL_NOTE}",
            "cases": cases}


def build(files, bases):
    """``files``: {source_id: {member: bytes}} -> {file name: document}."""
    massive = files["massive"]
    return {
        "open_clinc150_v1.json": golden(
            "open_clinc150_v1", ["clinc150"],
            "300 English requests: 100 out-of-scope, 15 of each mapped intent, 95 other intents.",
            clinc_cases(files["clinc150"][SOURCES["clinc150"]["path"]])),
        "open_banking77_v1.json": golden(
            "open_banking77_v1", ["banking77"], "300 English banking requests, round-robin over the mapped intents.",
            banking_cases(files["banking77"][SOURCES["banking77"]["path"]])),
        "open_massive_th_en_v1.json": golden(
            "open_massive_th_en_v1", ["massive"],
            "150 Thai (th-TH) and the same 150 English (en-US) test utterances, a pair per id: assistant "
            "requests outside this help desk, so all other.",
            massive_cases(massive["1.1/data/en-US.jsonl"], massive["1.1/data/th-TH.jsonl"])),
        "open_bipia_injection_v1.json": golden(
            "open_bipia_injection_v1", ["bipia"],
            "BIPIA's 75 test text attacks (indirect prompt injection), each added to one clear case of "
            "case_triage_autosend_hard_v1, which keeps its label; the tag base:<case_id> names it.",
            bipia_cases(files["bipia"][SOURCES["bipia"]["path"]], bases)),
    }


def dump(document):
    return (json.dumps(document, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def mapping_sha256():
    tables = {"clinc_map": CLINC_MAP, "clinc_excluded": sorted(CLINC_EXCLUDED), "banking_map": BANKING_MAP,
              "sizes": [CLINC_OOS, CLINC_PER_MAPPED, CLINC_OTHER, BANKING_TOTAL, MASSIVE_PAIRS], "seed": SEED}
    return sha256(json.dumps(tables, sort_keys=True).encode("utf-8"))


def manifest(outputs, hard_set_sha256):
    sets = {}
    for name, document in outputs.items():
        counts = {}
        for case in document["cases"]:
            key = f"{case['language']}:{case['expected_category']}"
            counts[key] = counts.get(key, 0) + 1
        sets[name] = {"cases": len(document["cases"]), "sha256": sha256(dump(document)),
                      "by_language_and_category": dict(sorted(counts.items()))}
    return {"schema": "neuron-flow-open-bench-manifest-v1", "seed": SEED, "mapping_sha256": mapping_sha256(),
            "hard_set_sha256": hard_set_sha256,
            "sources": {key: {k: v for k, v in meta.items()} for key, meta in SOURCES.items()}, "sets": sets}


def _url(meta):
    if "url" in meta:
        return meta["url"]
    return (f"https://raw.githubusercontent.com/{meta['repo']}/{meta['commit']}/"
            + urllib.parse.quote(meta["path"]))


def fetch(cache=None):
    """Every source's bytes, checked against its pinned SHA-256; the archive's members read in memory."""
    files = {}
    for source_id, meta in SOURCES.items():
        cached = Path(cache) / meta["sha256"] if cache else None
        if cached is not None and cached.is_file():
            data = cached.read_bytes()
        else:
            try:
                with urllib.request.urlopen(_url(meta), timeout=300) as response:  # noqa: S310 (pinned https host)
                    data = response.read()
            except urllib.error.URLError as exc:
                raise SystemExit(f"{_url(meta)}: download failed ({exc})") from None
        if sha256(data) != meta["sha256"]:
            raise SystemExit(f"{source_id}: SHA-256 differs from the pinned value; nothing was built")
        if cached is not None and not cached.is_file():
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(data)
        if "members" in meta:
            found = {}
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
                for member in meta["members"]:
                    info = archive.getmember(member)
                    if not info.isfile():
                        raise SystemExit(f"{source_id}: {member} is not a regular file")
                    found[member] = archive.extractfile(info).read()
            files[source_id] = found
        else:
            files[source_id] = {meta["path"]: data}
    return files


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, help="folder for the four case files and manifest.json")
    parser.add_argument("--cache", help="folder that keeps the downloaded sources (named by SHA-256)")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 unless the manifest equals the committed tests/open_benchmarks/manifest_v1.json")
    parser.add_argument("--write-manifest", action="store_true", help="replace the committed manifest")
    args = parser.parse_args(argv)
    outputs = build(fetch(args.cache), hard_set_bases())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, document in outputs.items():
        (out / name).write_bytes(dump(document))
    result = manifest(outputs, sha256(HARD_SET.read_bytes()))
    (out / "manifest.json").write_bytes(dump(result))
    for name, item in result["sets"].items():
        print(f"{name}: {item['cases']} cases, sha256 {item['sha256'][:12]}")
    if args.write_manifest:
        MANIFEST.write_bytes(dump(result))
        print(f"wrote {MANIFEST}")
    if args.check:
        committed = json.loads(MANIFEST.read_bytes().decode("utf-8"))
        if committed != result:
            print("The built sets differ from tests/open_benchmarks/manifest_v1.json (sources, mapping, sample "
                  "or the hard set changed).")
            return 1
        print("OK: every source matches its pinned SHA-256 and every case file matches the committed manifest.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
