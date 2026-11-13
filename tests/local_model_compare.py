"""Compare models on the same triage case sets from their saved scorecard reports (ADR-034): the owner's fine-tune
against the publisher's Typhoon 2.5 4B it was trained from, and any reference such as Typhoon 30B's saved run.

    python -m tests.local_model_compare \
        --model "fine-tune=lane/shadow-nf-typhoon4b-v01-q4_k_m-*.json" \
        --model "4B base=lane/shadow-typhoon2.5-qwen3-4b-q4_k_m-*.json" \
        --model "Typhoon 30B (API, 2026-11-11)=docs/evidence/2026-11-11-attention-raw/typhoon-v2-*.json" \
        --summary "$GITHUB_STEP_SUMMARY" --json comparison.json

The first ``--model`` is the candidate and the second its baseline; more are references. Reports are grouped by
the case set their provenance names; only the candidate's sets are shown. A set is compared only when every report of
it used the same case file and number of cases, prompt, rules and attention signals (the identity the eval gate uses);
otherwise it is listed as not comparable.

For each set and model: jobs completed; AI answered (the answer passed the schema); AI category right, of the answered
cases and of all cases (a case without an answer counts as not right); the rules' mistakes raised for a person;
``needs_person`` cases raised, and raised by the AI's own flag; ordinary cases the AI flagged without need; tokens;
latency. Then case by case, candidate against baseline: the cases only the candidate gets right, only the baseline
gets right, both get wrong, and ``needs_person`` cases only one of them flags.

``--training-cases FILE`` (a JSON list of case ids, from ``tests/training_overlap.py``) marks cases whose text was
found in the training data, and the figures are repeated without them. Nothing here is accuracy: the labels are the
developer's and each report is one run.
"""

import argparse
import glob
import json
from pathlib import Path
import sys

from app.eval import common

IDENTITY = ("golden", "cases", "prompt", "rules", "signals")
SET_NAMES = {"case_triage_synthetic_v1": "ชุดพัฒนา (development, 61)",
             "triage_edge_robustness_v1": "เคสขอบ (robustness edge, 116)",
             "case_triage_heldout_v1": "ชุดที่กันไว้ (held-out, 40)",
             "case_triage_autosend_hard_v1": "ชุดเคสยาก (hard, 128)",
             "case_triage_attention_heldout_v1": "ชุด attention ที่กันไว้ (held-out, 64)"}


def load_reports(spec):
    label, _, pattern = spec.partition("=")
    if not label or not pattern:
        raise SystemExit(f"--model needs LABEL=GLOB, got {spec!r}")
    reports = {}
    for path in sorted(glob.glob(pattern)):
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        if document.get("schema") != "neuron-flow-shadow-eval-v1":
            continue
        reports[document["provenance"]["golden"]["name"]] = {"path": path, **document}
    return label.strip(), reports


def identity(report):
    p = report["provenance"]
    return {"golden": p["golden"]["sha256"], "cases": p["golden"]["cases"], "prompt": p["prompt"]["sha256"],
            "rules": p["rules"]["version"], "signals": p["signals"]["version"]}


def right(row):
    return row["llm_status"] == "ok" and row["llm_category"] == row["expected"]


def ai_flag(row):
    return row["llm_status"] == "ok" and row["llm_attention"] not in (None, "none")


def figures(rows):
    answered = [r for r in rows if r["llm_status"] == "ok"]
    must = [r for r in rows if "needs_person" in r["tags"]]
    ordinary = [r for r in rows if "needs_person" not in r["tags"]]
    rules_wrong = [r for r in rows if r["rules_category"] != r["expected"]]
    latencies = [r["llm_latency_ms"] for r in answered if r["llm_latency_ms"] is not None]
    return {
        "cases": len(rows),
        "jobs_completed": common.rate(sum(r["job_status"] == "SUCCEEDED" for r in rows), len(rows)),
        "ai_answered": common.rate(len(answered), len(rows)),
        "ai_right_of_answered": common.rate(sum(map(right, answered)), len(answered)),
        "ai_right_of_all": common.rate(sum(map(right, rows)), len(rows)),
        "rule_mistakes_raised": common.rate(sum(r["review_priority"] == "elevated" for r in rules_wrong), len(rules_wrong)),
        "needs_person_raised": common.rate(sum(r["review_priority"] == "elevated" for r in must), len(must)),
        "needs_person_ai_flag": common.rate(sum(map(ai_flag, must)), len(must)),
        "ordinary_ai_flag": common.rate(sum(map(ai_flag, ordinary)), len(ordinary)),
        "raised": common.rate(sum(r["review_priority"] == "elevated" for r in rows), len(rows)),
        "tokens_in": sum(r["input_tokens"] for r in rows), "tokens_out": sum(r["output_tokens"] for r in rows),
        "latency_ms_p50": _percentile(latencies, 0.5), "latency_ms_p95": _percentile(latencies, 0.95),
    }


def _percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return round(ordered[index], 1)


def case_diff(candidate, baseline):
    base = {r["case_id"]: r for r in baseline}
    rows = [(r, base[r["case_id"]]) for r in candidate if r["case_id"] in base]
    return {
        "only_candidate_right": [c["case_id"] for c, b in rows if right(c) and not right(b)],
        "only_baseline_right": [c["case_id"] for c, b in rows if right(b) and not right(c)],
        "both_wrong": [c["case_id"] for c, b in rows if not right(c) and not right(b)],
        "needs_person_flag_only_candidate": [c["case_id"] for c, b in rows
                                             if "needs_person" in c["tags"] and ai_flag(c) and not ai_flag(b)],
        "needs_person_flag_only_baseline": [c["case_id"] for c, b in rows
                                            if "needs_person" in c["tags"] and ai_flag(b) and not ai_flag(c)],
        "ordinary_flag_only_candidate": [c["case_id"] for c, b in rows
                                         if "needs_person" not in c["tags"] and ai_flag(c) and not ai_flag(b)],
        "category_changed": sum(c["llm_category"] != b["llm_category"] for c, b in rows),
        "compared": len(rows),
    }


def compare(models, seen_in_training=frozenset()):
    """``models``: [(label, {set name: report})]. Returns the comparison document."""
    sets = sorted(models[0][1], key=lambda name: list(SET_NAMES).index(name) if name in SET_NAMES else 99)
    result = {"schema": "neuron-flow-local-compare-v1", "models": [label for label, _ in models], "sets": []}
    for name in sets:
        present = [(label, reports[name]) for label, reports in models if name in reports]
        entry = {"set": name, "models": {}, "comparable": True, "problems": []}
        identities = {label: identity(report) for label, report in present}
        first = next(iter(identities.values()))
        for label, ident in identities.items():
            for key in IDENTITY:
                if ident[key] != first[key]:
                    entry["comparable"] = False
                    entry["problems"].append(f"{label}: {key} differs")
        for label, report in present:
            rows = report["cases"]
            entry["models"][label] = {"report": report["path"], "model": report["provenance"]["llm"]["model"],
                                      "provider": report["provenance"]["llm"]["provider"],
                                      "duration_s": report["provenance"].get("duration_s"), **figures(rows)}
            if seen_in_training:
                clean = [r for r in rows if r["case_id"] not in seen_in_training]
                entry["models"][label]["without_training_cases"] = figures(clean)
                entry["models"][label]["training_cases_here"] = len(rows) - len(clean)
        labels = [label for label, _ in models]
        if entry["comparable"] and len(labels) >= 2 and labels[0] in entry["models"] and labels[1] in entry["models"]:
            entry["diff"] = case_diff(models[0][1][name]["cases"], models[1][1][name]["cases"])
        result["sets"].append(entry)
    return result


def fmt(value):
    return common.fmt_rate(value)


def markdown(document):
    labels = document["models"]
    lines = ["## เทียบโมเดลบนชุดเคสเดียวกัน (model comparison)", "",
             f"ตัวที่ทดสอบ: **{labels[0]}** · เทียบกับ: **{labels[1] if len(labels) > 1 else '–'}**"
             + (f" · อ้างอิง: {', '.join(labels[2:])}" if len(labels) > 2 else ""), "",
             "> ทุกชุดเป็นข้อมูลสมมุติ เฉลยเขียนโดยผู้พัฒนา และแต่ละโมเดลรันครั้งเดียว ตัวเลขนี้จึงเป็นการวัดครั้งแรกของไฟล์โมเดลเหล่านี้ "
             "ไม่ใช่ความแม่นยำ เวลาตอบเทียบกันได้เฉพาะโมเดลที่รันบนเครื่องเดียวกันในรอบเดียวกัน  ",
             "> *Synthetic sets, developer labels, one run per model: a first measurement, not accuracy. Latency compares "
             "only models run on the same machine in the same job.*", ""]
    rows = (("AI ตอบได้ (ผ่าน schema)", "ai_answered"), ("AI จัดหมวดถูก (ของที่ตอบได้)", "ai_right_of_answered"),
            ("AI จัดหมวดถูก (ของทุกเคส)", "ai_right_of_all"), ("ความผิดของกฎที่ถูกยกให้คนดู", "rule_mistakes_raised"),
            ("เคสที่ต้องให้คนดูก่อน ถูกยกขึ้น", "needs_person_raised"),
            ("… ในนั้น AI ชี้เอง", "needs_person_ai_flag"), ("เคสธรรมดาที่ AI ชี้โดยไม่จำเป็น", "ordinary_ai_flag"),
            ("เคสที่ถูกยกทั้งหมด", "raised"))
    for entry in document["sets"]:
        lines += [f"### {SET_NAMES.get(entry['set'], entry['set'])}", ""]
        if not entry["comparable"]:
            lines += ["เทียบกันไม่ได้: " + "; ".join(entry["problems"]), ""]
        present = [label for label in labels if label in entry["models"]]
        lines += ["| สิ่งที่วัด | " + " | ".join(present) + " |", "|---|" + "---|" * len(present)]
        for title, key in rows:
            values = [entry["models"][label][key] for label in present]
            if all(not value["denominator"] for value in values):
                continue
            lines.append(f"| {title} | " + " | ".join(fmt(value) for value in values) + " |")
        lines.append("| เวลาตอบ p50 / p95 (ms) | " + " | ".join(
            f"{entry['models'][l]['latency_ms_p50']} / {entry['models'][l]['latency_ms_p95']}" for l in present) + " |")
        lines.append("| token เข้า / ออก | " + " | ".join(
            f"{entry['models'][l]['tokens_in']:,} / {entry['models'][l]['tokens_out']:,}" for l in present) + " |")
        if any("training_cases_here" in entry["models"][l] for l in present):
            lines.append("| เคสที่พบในข้อมูลฝึก | " + " | ".join(
                str(entry["models"][l].get("training_cases_here", "–")) for l in present) + " |")
            lines.append("| AI ถูก (ของทุกเคส) ไม่นับเคสที่พบในข้อมูลฝึก | " + " | ".join(
                fmt(entry["models"][l]["without_training_cases"]["ai_right_of_all"]) for l in present) + " |")
        diff = entry.get("diff")
        if diff:
            lines += ["", f"รายเคส {labels[0]} เทียบ {labels[1]} ({diff['compared']} เคส, หมวดต่างกัน {diff['category_changed']} เคส):", ""]
            for title, key in (("ถูกเฉพาะตัวที่ทดสอบ", "only_candidate_right"), ("ถูกเฉพาะตัวเดิม", "only_baseline_right"),
                               ("ผิดทั้งคู่", "both_wrong"),
                               ("เคสต้องให้คนดู ที่เฉพาะตัวที่ทดสอบชี้", "needs_person_flag_only_candidate"),
                               ("เคสต้องให้คนดู ที่เฉพาะตัวเดิมชี้", "needs_person_flag_only_baseline"),
                               ("เคสธรรมดา ที่เฉพาะตัวที่ทดสอบชี้โดยไม่จำเป็น", "ordinary_flag_only_candidate")):
                ids = diff[key]
                if ids:
                    shown = ", ".join(f"`{c}`" for c in ids[:25]) + (" …" if len(ids) > 25 else "")
                    lines.append(f"- {title} ({len(ids)}): {shown}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", action="append", required=True, help="LABEL=GLOB; the first is the candidate")
    parser.add_argument("--training-cases", help="a JSON list of case ids found in the training data")
    parser.add_argument("--summary")
    parser.add_argument("--json")
    args = parser.parse_args(argv)
    models = [load_reports(spec) for spec in args.model]
    if len(models) < 2:
        parser.error("give at least two --model entries")
    seen = frozenset(json.loads(Path(args.training_cases).read_text(encoding="utf-8"))) if args.training_cases else frozenset()
    document = compare(models, seen)
    text = markdown(document)
    print(text)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as stream:
            stream.write(text)
    if args.json:
        Path(args.json).write_text(json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0 if any(entry["comparable"] for entry in document["sets"]) else 1


if __name__ == "__main__":
    sys.exit(main())
