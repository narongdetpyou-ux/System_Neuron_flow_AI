"""Check a synthetic training set and keep it apart from every exam set (own-model track T2, ADR-037).

A training set is one JSON file of hand-written synthetic cases, each with the answer the triage prompt
(``triage_classify_v2``) should give. The owner approves a set by merging the pull request that adds it; its
manifest pins the file's SHA-256, so the approved bytes are the trained bytes. This tool checks, with the standard
library and the app's own contracts only:

1. **every record**: exactly the fields ``case_id``, ``language``, ``summary``, ``category``, ``attention``,
   ``confidence`` and ``rationale``; a unique id; a summary the triage workflow would admit (``check_case``); the
   language matches the text (``th`` holds a Thai letter, ``en`` does not), in the rationale too; nothing in the
   summary or the rationale that the masking rules would still change (``mask``), so the text looks like what the
   model sees at run time; and an answer the gateway accepts unchanged (``parse_answer`` with the prompt's schema);
2. **the set**: no two summaries the same after normalization, and the manifest equal to the file (its SHA-256,
   size and counts);
3. **no overlap with an exam set**: no summary equal to, or nearly equal to, any text of any exam set
   (``EXAM_SETS``, plus the open-benchmark case files passed with ``--extra`` and ``--extra-sealed``).

The overlap rule ``overlap-v1``, fixed before the first set was checked: texts are normalized (NFKC, case folded,
invisible format characters removed, runs of spaces made one) and cut into overlapping 4-character pieces. Two
texts are an **exact** match when they are equal after normalization, and a **near** match when the share of
pieces they have in common is at least 0.6 of all their pieces (Jaccard), or when at least 0.9 of the shorter
text's pieces are in the longer one and the shorter has at least 20 pieces (one text inside the other). Every
result reports these thresholds. An exam text found in a training set fails the check; a failure is never fixed by
changing the rule, only by rewriting or removing the training case.

The sealed half of the open data (``--extra-sealed``) is reported as counts only: no text and no id is printed.

Run: ``python -m training.check_set`` (the committed set against the committed exam sets), with
``--extra open-sets/open_clinc150_v1.json …`` and ``--extra-sealed open-sets/open_attention_sealed_v1.json`` where
the open sets were built (the *Training set check* workflow), ``--summary`` for a Thai summary, and
``--write-manifest`` after changing a set on purpose.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata

from app.domains.case_triage.contracts import ATTENTION_VALUES, CATEGORIES, CONFIDENCE_LEVELS
from app.llm.gateway import parse_answer
from app.llm.prompts import load_prompt
from app.llm.redaction import mask
from app.services.workflows import check_case

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SET = ROOT / "training" / "data" / "triage_train_v1.json"
SCHEMA = "neuron-flow-triage-training-v1"
MANIFEST_SCHEMA = "neuron-flow-training-manifest-v1"
PROMPT_ID = "triage_classify_v2"
FIELDS = ("case_id", "language", "summary", "category", "attention", "confidence", "rationale")
LANGUAGES = ("th", "en")
RATIONALE_MAX_CHARS = 200
CASE_ID = re.compile(r"^TR-[A-Z0-9][A-Z0-9-]{2,40}$")
# The letters of the Thai script, as the reviewer-label scorecard counts them (review_labels.language_of).
THAI_LETTER = re.compile(r"[ก-ะาำเ-ๆ]")

OVERLAP_RULE = {"version": "overlap-v1", "piece_chars": 4, "jaccard_min": 0.6, "containment_min": 0.9,
                "containment_min_pieces": 20}


def _golden(field):
    return lambda data: [case[field] for case in data["cases"]]


def _strings(value):
    """Every string inside a JSON value (the robustness items' inputs)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    return []


def _robustness_items(data):
    return [text for item in data["items"] for text in _strings(item.get("input"))]


def _open_extract(data):
    return [row["text"] for row in data["labelled"]] + [text for text in data["corpora"]["blns"] if isinstance(text, str)]


# Every exam set committed to this repository: (name, path, how to read its texts). A new exam set must be added
# here; tests/test_training_set.py fails while a case file of app/eval/golden/ or tests/robustness/ is missing.
EXAM_SETS = (
    ("case_triage_synthetic_v1", "app/eval/golden/case_triage_synthetic_v1.json", _golden("summary")),
    ("case_triage_heldout_v1", "app/eval/golden/case_triage_heldout_v1.json", _golden("summary")),
    ("case_triage_autosend_hard_v1", "app/eval/golden/case_triage_autosend_hard_v1.json", _golden("summary")),
    ("case_triage_attention_heldout_v1", "app/eval/golden/case_triage_attention_heldout_v1.json", _golden("summary")),
    ("triage_edge_golden_v1", "tests/robustness/triage_edge_golden_v1.json", _golden("summary")),
    ("study_guide_synthetic_v1", "app/eval/golden/study_guide_synthetic_v1.json", _golden("message")),
    ("intake_route_v1", "app/eval/golden/intake_route_v1.json", _golden("message")),
    ("intake_route_heldout_v1", "app/eval/golden/intake_route_heldout_v1.json", _golden("message")),
    ("robustness_synthetic_v1", "tests/robustness/synthetic_v1.json", _robustness_items),
    ("robustness_open_extract_v1", "tests/robustness/open_extract_v1.json", _open_extract),
)


class SetError(Exception):
    """The training set or its manifest cannot be read at all."""


# -- text pieces -------------------------------------------------------------------------------------------

def normalize(text):
    """NFKC, case folded, without invisible format characters (Cf), with runs of white space made one space."""
    text = unicodedata.normalize("NFKC", text).casefold()
    text = "".join(character for character in text if unicodedata.category(character) != "Cf")
    return " ".join(text.split())


def pieces(text, size=OVERLAP_RULE["piece_chars"]):
    """The set of overlapping ``size``-character pieces of a normalized text (the whole text when shorter)."""
    if len(text) <= size:
        return {text} if text else set()
    return {text[i:i + size] for i in range(len(text) - size + 1)}


def similarity(a, b):
    """``(jaccard, containment)`` of two piece sets; containment is ``None`` when the shorter is too short."""
    if not a or not b:
        return 0.0, None
    common = len(a & b)
    jaccard = common / (len(a) + len(b) - common)
    shorter = min(len(a), len(b))
    containment = common / shorter if shorter >= OVERLAP_RULE["containment_min_pieces"] else None
    return jaccard, containment


def is_near(jaccard, containment):
    return jaccard >= OVERLAP_RULE["jaccard_min"] or (
        containment is not None and containment >= OVERLAP_RULE["containment_min"])


# -- the set and its manifest ------------------------------------------------------------------------------

def load_set(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SetError(f"cannot read the training set {path}: {exc}") from None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("cases"), list):
        raise SetError(f"{path} is not a training set of schema {SCHEMA}")
    return data


def manifest_path(path):
    path = Path(path)
    return path.with_name(path.stem + ".manifest.json")


def counts(cases, field, values):
    return {value: sum(case.get(field) == value for case in cases) for value in values}


def build_manifest(path):
    path = Path(path)
    raw = path.read_bytes()
    cases = load_set(path)["cases"]
    return {"schema": MANIFEST_SCHEMA, "set": path.name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            "cases": len(cases), "prompt_id": PROMPT_ID,
            "by_language": counts(cases, "language", LANGUAGES),
            "by_category": counts(cases, "category", CATEGORIES),
            "by_attention": counts(cases, "attention", ATTENTION_VALUES),
            "by_confidence": counts(cases, "confidence", CONFIDENCE_LEVELS),
            "overlap_rule": dict(OVERLAP_RULE)}


def check_manifest(path):
    """Problems with the manifest beside ``path`` (it must equal what the file gives now)."""
    target = manifest_path(path)
    try:
        stored = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [f"{target.name} is missing or unreadable: write it with --write-manifest"]
    current = build_manifest(path)
    return [f"manifest field {key} is {stored.get(key)!r}, the file gives {value!r}"
            for key, value in current.items() if stored.get(key) != value]


def _language_problem(text, language):
    has_thai = bool(THAI_LETTER.search(text))
    return (language == "th") != has_thai


def check_records(cases):
    """Problems with the records themselves, as ``(case_id, problem)`` pairs."""
    schema = load_prompt(PROMPT_ID).output_schema
    problems, seen_ids, seen_texts = [], set(), {}
    for index, case in enumerate(cases):
        case_id = case.get("case_id") if isinstance(case, dict) else None
        label = case_id if isinstance(case_id, str) else f"#{index}"
        if not isinstance(case, dict) or tuple(sorted(case)) != tuple(sorted(FIELDS)):
            problems.append((label, f"the fields must be exactly {', '.join(FIELDS)}"))
            continue
        if not isinstance(case_id, str) or not CASE_ID.fullmatch(case_id):
            problems.append((label, "case_id must look like TR-EN-ACC-001"))
        elif case_id in seen_ids:
            problems.append((label, "case_id is used twice"))
        seen_ids.add(case_id)
        summary, rationale = case["summary"], case["rationale"]
        if not isinstance(summary, str) or not isinstance(rationale, str):
            problems.append((label, "summary and rationale must be text"))
            continue
        if case["language"] not in LANGUAGES:
            problems.append((label, f"language must be one of {', '.join(LANGUAGES)}"))
        elif _language_problem(summary, case["language"]) or _language_problem(rationale, case["language"]):
            problems.append((label, "the summary and the rationale must be in the case's language "
                                    "(th: with a Thai letter; en: without one)"))
        try:
            check_case({"case_id": case_id if isinstance(case_id, str) else "TR-X", "summary": summary})
        except Exception as exc:  # the workflow's own admission check
            problems.append((label, f"the triage workflow would refuse the summary: {exc}"))
        for name, text in (("summary", summary), ("rationale", rationale)):
            masked = mask(text).text
            if masked != text:
                problems.append((label, f"the {name} holds text the masking rules would change: write the "
                                        "placeholder (such as [PHONE]) instead"))
        if not rationale.strip() or len(rationale) > RATIONALE_MAX_CHARS or "\n" in rationale:
            problems.append((label, f"rationale must be one line of 1-{RATIONALE_MAX_CHARS} characters"))
        target = {"attention": case["attention"], "category": case["category"], "confidence": case["confidence"],
                  "rationale": rationale}
        try:
            parsed = parse_answer(json.dumps(target, ensure_ascii=False), schema)
        except Exception as exc:  # the gateway's own answer check
            problems.append((label, f"the gateway would refuse this answer: {exc}"))
        else:
            if parsed != target:
                problems.append((label, "the gateway would change this answer (spaces or invisible characters)"))
        key = normalize(summary)
        if key in seen_texts:
            problems.append((label, f"the same summary as {seen_texts[key]}"))
        seen_texts.setdefault(key, label)
    return problems


# -- the overlap check -------------------------------------------------------------------------------------

def exam_texts(extra=(), extra_sealed=()):
    """``[(name, sealed, [texts])]``: the committed exam sets, then the case files given on the command line."""
    sets = []
    for name, relative, read in EXAM_SETS:
        sets.append((name, False, read(json.loads((ROOT / relative).read_text(encoding="utf-8")))))
    for sealed, files in ((False, extra), (True, extra_sealed)):
        for path in files:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            sets.append((Path(path).stem, sealed, [case["summary"] for case in data["cases"]]))
    return sets


def overlap(cases, sets):
    """One result per exam set: how many of its texts were compared, the matches and the highest similarity."""
    training = [(case["case_id"], normalize(case["summary"])) for case in cases]
    training = [(case_id, text, pieces(text)) for case_id, text in training]
    results = []
    for name, sealed, texts in sets:
        exact, near, highest = [], [], 0.0
        exam = [normalize(text) for text in texts if isinstance(text, str) and text.strip()]
        exam = [(text, pieces(text)) for text in exam]
        for case_id, text, mine in training:
            for position, (other, theirs) in enumerate(exam):
                if text == other:
                    exact.append((case_id, position))
                    highest = 1.0
                    continue
                jaccard, containment = similarity(mine, theirs)
                highest = max(highest, jaccard)
                if is_near(jaccard, containment):
                    near.append((case_id, position, round(jaccard, 3),
                                 None if containment is None else round(containment, 3)))
        results.append({"name": name, "sealed": sealed, "compared": len(exam), "exact": exact, "near": near,
                        "highest_jaccard": round(highest, 3)})
    return results


def report_lines(problems, manifest_problems, results, cases):
    """Plain lines for the console; sealed results never name a case or show a text."""
    lines = [f"training set: {len(cases)} cases; overlap rule {OVERLAP_RULE['version']} "
             f"({OVERLAP_RULE['piece_chars']}-character pieces, Jaccard >= {OVERLAP_RULE['jaccard_min']}, "
             f"containment >= {OVERLAP_RULE['containment_min']} when the shorter has >= "
             f"{OVERLAP_RULE['containment_min_pieces']} pieces)"]
    lines += [f"record problem: {label}: {problem}" for label, problem in problems]
    lines += [f"manifest problem: {problem}" for problem in manifest_problems]
    for result in results:
        lines.append(f"{result['name']}{' (sealed: counts only)' if result['sealed'] else ''}: "
                     f"{result['compared']} texts, {len(result['exact'])} exact, {len(result['near'])} near, "
                     f"highest Jaccard {result['highest_jaccard']}")
        if not result["sealed"]:
            lines += [f"  exact: {case_id} = text #{position}" for case_id, position in result["exact"]]
            lines += [f"  near: {case_id} ~ text #{position} (Jaccard {jaccard}, containment {containment})"
                      for case_id, position, jaccard, containment in result["near"]]
    return lines


def summary_lines(problems, manifest_problems, results, cases, passed):
    """Thai lines for the run page (``--summary``)."""
    languages = _language_counts(cases)
    lines = ["### ชุดฝึก AI ของเราเอง (ขั้น T2): ตรวจความถูกต้อง และตรวจว่าไม่ซ้ำกับข้อสอบ", "",
             f"- ผล: **{'ผ่าน' if passed else 'ไม่ผ่าน'}** · {len(cases)} เคส"
             + f" · ไทย {languages['th']} · อังกฤษ {languages['en']}",
             f"- เกณฑ์ซ้ำ ({OVERLAP_RULE['version']}): เหมือนกันหลังปรับรูปข้อความ หรือมีชิ้นข้อความ 4 ตัวอักษรร่วมกัน"
             f" ≥ {OVERLAP_RULE['jaccard_min']:.0%} หรือข้อความหนึ่งอยู่ในอีกข้อความ ≥ {OVERLAP_RULE['containment_min']:.0%}",
             f"- ปัญหาของเคส: {len(problems)} · ปัญหาของใบกำกับชุดฝึก (manifest): {len(manifest_problems)}", "",
             "| ข้อสอบ | จำนวนข้อความ | ซ้ำตรง | ซ้ำใกล้เคียง | ความคล้ายสูงสุด |", "|---|---|---|---|---|"]
    for result in results:
        name = result["name"] + (" (ครึ่งที่ปิดไว้ นับอย่างเดียว)" if result["sealed"] else "")
        lines.append(f"| {name} | {result['compared']} | {len(result['exact'])} | {len(result['near'])} | "
                     f"{result['highest_jaccard']} |")
    return lines + [""]


def _language_counts(cases):
    return {language: sum(isinstance(case, dict) and case.get("language") == language for case in cases)
            for language in LANGUAGES}


def run(path=DEFAULT_SET, extra=(), extra_sealed=()):
    """``(passed, problems, manifest_problems, results, cases)`` for one training set."""
    cases = load_set(path)["cases"]
    problems = check_records(cases)
    manifest_problems = check_manifest(path)
    valid = [case for case in cases if isinstance(case, dict) and isinstance(case.get("summary"), str)
             and isinstance(case.get("case_id"), str)]
    results = overlap(valid, exam_texts(extra, extra_sealed))
    passed = not problems and not manifest_problems and not any(r["exact"] or r["near"] for r in results)
    return passed, problems, manifest_problems, results, cases


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--set", default=str(DEFAULT_SET), help="the training set (JSON)")
    parser.add_argument("--extra", nargs="*", default=[], help="more exam case files (cases[].summary)")
    parser.add_argument("--extra-sealed", nargs="*", default=[],
                        help="exam case files reported as counts only (the sealed half)")
    parser.add_argument("--summary", help="append Thai lines here (e.g. $GITHUB_STEP_SUMMARY)")
    parser.add_argument("--write-manifest", action="store_true",
                        help="write the manifest beside the set from the file as it is now, then check")
    args = parser.parse_args(argv)
    if args.write_manifest:
        manifest = build_manifest(args.set)
        manifest_path(args.set).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    passed, problems, manifest_problems, results, cases = run(args.set, args.extra, args.extra_sealed)
    print("\n".join(report_lines(problems, manifest_problems, results, cases)))
    print("PASSED" if passed else "FAILED")
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as handle:
            handle.write("\n".join(summary_lines(problems, manifest_problems, results, cases, passed)) + "\n")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
