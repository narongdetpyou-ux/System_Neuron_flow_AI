"""Attention replay: what the attention signals change on answers that were saved before they existed.

The signals (``app/domains/case_triage/signals.py``, ADR-032) are plain code over the case text, and they
never change a category. So their effect on an old scorecard report can be worked out exactly, without
asking the model again: join each saved row to its case text, find the signals, and add the reasons and the
raised priority that ``compare`` would have produced. The model's answers stay byte for byte the saved ones,
which makes "before" and "after" a comparison of the flag alone.

Flow:
1. read pairs of a saved report (``triage_shadow_eval --out``) and its case file; refuse a row whose case
   text hash is not the one in the case file;
2. per row: ``before`` is the saved priority; ``after`` adds the signal reasons, and is ``elevated`` when
   the row was already elevated or a signal was found;
3. count, per set and in total: cases a person should see first (tag ``needs_person``) that were raised,
   cases carrying an injected instruction (tags ``routing_injection``, ``open_injection``) that were raised,
   and other cases raised by a signal (the cost: more cases marked "look first");
4. optionally write each report again with the new reasons (``--out-dir``), so the auto-approve simulation
   can replay its ``screened`` policy on them.

It calls no model and changes nothing in the service.

Run: ``python -m app.eval.attention_replay --pair saved.json cases.json [--pair ...] --summary s.md``
"""

import argparse
import sys
from pathlib import Path

from neuron_flow.model import decode

from app.domains.case_triage.contracts import REVIEW_REASONS, SIGNAL_REASONS
from app.domains.case_triage.signals import REASON_FOR, find_signals, signal_version

from .common import fmt_rate, rate, to_json
from .triage_shadow_eval import REPORT_SCHEMA, attention_metrics, load_golden

SCHEMA = "neuron-flow-attention-replay-v1"
INJECTION_TAGS = ("routing_injection", "open_injection")
MAX_LISTED = 25


def replay_rows(report, golden):
    """The report's rows with the signal reasons added; raises when a row does not belong to the case file."""
    if not isinstance(report, dict) or report.get("schema") != REPORT_SCHEMA or not report.get("cases"):
        raise ValueError("A full shadow-eval report (--out) is required")
    cases = {case["case_id"]: case for case in golden["cases"]}
    rows = []
    for row in report["cases"]:
        case = cases.get(row["case_id"])
        if case is None or case["source_sha256"] != row["source_sha256"]:
            raise ValueError(f"Case {row['case_id']!r} is not in the case file, or its text differs")
        if any(reason in SIGNAL_REASONS for reason in row["review_reasons"]):
            raise ValueError("This report already has attention signals; replay only older reports")
        if row["job_status"] != "SUCCEEDED":
            rows.append(dict(row))  # no proposal was built, so there is nothing to raise
            continue
        reasons = [REASON_FOR[kind] for kind in find_signals(case["summary"])["signals"]]
        rows.append({**row,
                     "review_reasons": sorted([*reasons, *row["review_reasons"]], key=REVIEW_REASONS.index),
                     "review_priority": "elevated" if reasons else row["review_priority"]})
    return rows


def _injected(row):
    return any(tag in row["tags"] for tag in INJECTION_TAGS)


def _counts(rows):
    must = [r for r in rows if "needs_person" in r["tags"]]
    attacks = [r for r in rows if _injected(r)]
    rest = [r for r in rows if "needs_person" not in r["tags"] and not _injected(r)]

    def raised(subset):
        return rate(sum(r["review_priority"] == "elevated" for r in subset), len(subset))

    return {"raised": raised(rows), "needs_person_raised": raised(must), "injection_raised": raised(attacks),
            "others_raised": raised(rest),
            # Is a raise worth the reviewer's look? It is when the rules were wrong, the case is one a person
            # should see first, or it carries an injected instruction.
            "raises_needed": rate(sum(r["rules_category"] != r["expected"] or "needs_person" in r["tags"]
                                      or _injected(r) for r in rows if r["review_priority"] == "elevated"),
                                  sum(r["review_priority"] == "elevated" for r in rows))}


def replay(pairs):
    """``pairs``: ``(report, golden)`` tuples. Returns the result and the upgraded reports."""
    sets, upgraded, every_before, every_after = [], [], [], []
    for report, golden in pairs:
        after = replay_rows(report, golden)
        before = report["cases"]
        every_before += before
        every_after += after
        p = report["provenance"]
        sets.append({"name": p["golden"]["name"], "golden_sha256": p["golden"]["sha256"], "cases": len(after),
                     "llm": {"provider": p["llm"]["provider"], "model": p["llm"]["model"]},
                     "answers_from_git_sha": p.get("git_sha"),
                     "before": _counts(before), "after": _counts(after),
                     "by_reason": {reason: sum(reason in r["review_reasons"] for r in after)
                                   for reason in SIGNAL_REASONS},
                     "needs_person_still_missed": [r["case_id"] for r in after if "needs_person" in r["tags"]
                                                   and r["review_priority"] != "elevated"],
                     "injection_still_missed": [r["case_id"] for r in after if _injected(r)
                                                and r["review_priority"] != "elevated"]})
        upgraded.append({**report, "cases": after,
                         "provenance": {**p, "signals": {"version": signal_version()},
                                        "replayed": "attention signals added by app.eval.attention_replay; "
                                                    "the model's answers are the saved ones"},
                         "metrics": {**report["metrics"], "attention": attention_metrics(after)}})
    return ({"schema": SCHEMA, "signals": {"version": signal_version()}, "sets": sets,
             "total": {"cases": len(every_after), "before": _counts(every_before), "after": _counts(every_after)}},
            upgraded)


def summary_markdown(result):
    lines = ["## สัญญาณ \"ต้องให้คนดูก่อน\": ก่อนและหลัง บนคำตอบชุดเดียวกัน (attention replay)", "",
             "> คำตอบของ AI คือชุดที่บันทึกไว้เดิมทุกตัวอักษร ไม่ได้ถาม AI ใหม่ สิ่งที่ต่างคือป้าย \"ยกให้ดูก่อน\" เท่านั้น "
             "(ก่อน = ยกเมื่อกฎกับ AI เห็นไม่ตรงกัน · หลัง = ยกเมื่อไม่ตรงกัน หรือโค้ดเจอสัญญาณในข้อความ) ทุกเคสยังรอคนตัดสินเหมือนเดิม  ",
             "> *The model's answers are the saved ones; only the \"look at this first\" flag differs. "
             f"Signals `{result['signals']['version'][:23]}…`.*", "",
             "| ชุดเคส | เคส | เคสต้องให้คนดูก่อน ที่ถูกยก: ก่อน → หลัง | เคสมีคำสั่งแอบแฝง ที่ถูกยก: ก่อน → หลัง | "
             "เคสอื่นที่ถูกยก: ก่อน → หลัง | การยกที่จำเป็นจริง: ก่อน → หลัง |", "|---|---|---|---|---|---|"]

    def row(name, cases, before, after):
        return (f"| {name} | {cases} | " + " | ".join(
            f"{fmt_rate(before[key])} → {fmt_rate(after[key])}"
            for key in ("needs_person_raised", "injection_raised", "others_raised", "raises_needed")) + " |")

    for s in result["sets"]:
        lines.append(row(f"`{s['name']}`", s["cases"], s["before"], s["after"]))
    total = result["total"]
    lines += [row("**รวม**", total["cases"], total["before"], total["after"]), "",
              "\"การยกที่จำเป็นจริง\" = เคสที่ถูกยก แล้วกฎผิดจริง หรือเป็นเคสที่ต้องให้คนดูก่อน หรือมีคำสั่งแอบแฝง", ""]
    for s in result["sets"]:
        for title, case_ids in (("ต้องให้คนดูก่อน แต่ยังไม่ถูกยก", s["needs_person_still_missed"]),
                                ("มีคำสั่งแอบแฝง แต่ยังไม่ถูกยก", s["injection_still_missed"])):
            if case_ids:
                lines.append(f"- `{s['name']}` {title} ({len(case_ids)}): "
                             + ", ".join(f"`{c}`" for c in case_ids[:MAX_LISTED])
                             + (" …" if len(case_ids) > MAX_LISTED else ""))
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pair", action="append", nargs=2, required=True, metavar=("REPORT", "CASES"),
                        help="a saved scorecard report and its case file; repeat for each case set")
    parser.add_argument("--out", help="write the JSON result here")
    parser.add_argument("--out-dir", help="write each report again, with the signal reasons, into this folder")
    parser.add_argument("--summary", help="append the markdown summary here (e.g. $GITHUB_STEP_SUMMARY)")
    args = parser.parse_args(argv)
    pairs = [(decode(Path(report).read_bytes()), load_golden(cases)) for report, cases in args.pair]
    result, upgraded = replay(pairs)
    text = summary_markdown(result)
    print(text)
    if args.out:
        Path(args.out).write_text(to_json(result), encoding="utf-8")
    if args.out_dir:
        folder = Path(args.out_dir)
        folder.mkdir(parents=True, exist_ok=True)
        for (report_path, _), report in zip(args.pair, upgraded):
            (folder / Path(report_path).name).write_text(to_json(report), encoding="utf-8")
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as stream:
            stream.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
