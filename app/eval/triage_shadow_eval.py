"""Scorecard for shadow mode: how often rules and AI are right, agree, get flagged, and cost.

Flow:
1. load the labelled case set and check its shape;
2. run every case through the real v2 workflow on a fresh temporary Runtime;
3. read each proposal and compare it with the label;
4. compute the scorecard (every rate keeps its numerator and denominator);
5. write a JSON report and a Thai/English markdown summary (shown on GitHub Actions).

Run: ``python -m app.eval.triage_shadow_eval --summary summary.md --out report.json``
Labels are synthetic unless a different case file is given; the mock provider is
a keyword simulation, so its numbers test the pipeline, not AI accuracy.

Eval gate (roadmap 5.2): ``--compare-with <baseline or report>`` fails (exit 3) when any case's answer
differs: the rules' category, the AI's status, category, reason, confidence and attempts, the agreement,
the review priority and reasons, the job status, or the case text; and when the case set, the prompt or
the AI model differs. CI compares every push with the committed mock baseline
(``tests/baselines/shadow_eval_mock.json``). To change the answers on purpose, regenerate it in the same
pull request with ``--write-baseline`` and say why; a prompt or model change also needs a live run by hand
(*Actions → Shadow eval with Claude*).
"""

import argparse
import hashlib
import os
import platform
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from neuron_flow import Runtime
from neuron_flow.evaluation import candidate_gate
from neuron_flow.model import decode, fingerprint
from neuron_flow.telemetry import percentile

from app.domains.case_triage import build_shadow_workflow, shadow_registry
from app.domains.case_triage.contracts import CATEGORIES
from app.domains.case_triage.shadow_workflow import PROMPT_ID
from app.llm import LLMConfig, load_prompt

from . import common
from .common import fmt_ms as _ms, fmt_rate as _fmt, git_sha as _git_sha, rate as _rate, to_json as _json

DEFAULT_GOLDEN = Path(__file__).with_name("golden") / "case_triage_synthetic_v1.json"
LANGUAGES = {"en": "อังกฤษ (EN)", "th": "ไทย (TH)"}
_CASE_KEYS = {"case_id", "language", "expected_category", "tags", "summary"}


def load_golden(path=DEFAULT_GOLDEN):
    document = decode(Path(path).read_bytes())
    if not isinstance(document, dict) or document.get("schema") != "neuron-flow-golden-v1":
        raise ValueError("Case file must use schema neuron-flow-golden-v1")
    cases, seen = [], set()
    for index, case in enumerate(document.get("cases") or []):
        if (not isinstance(case, dict) or set(case) != _CASE_KEYS or case["case_id"] in seen
                or case["expected_category"] not in CATEGORIES or case["language"] not in LANGUAGES
                or not isinstance(case["tags"], list) or not all(isinstance(t, str) for t in case["tags"])
                or not isinstance(case["summary"], str)):
            raise ValueError(f"Invalid or duplicate case at position {index}")
        seen.add(case["case_id"])
        cases.append({**case, "cluster_id": case["case_id"],
                      # Fixed split by position: even = validation, odd = holdout.
                      "split": "validation" if index % 2 == 0 else "holdout",
                      "source_sha256": hashlib.sha256(case["summary"].encode("utf-8")).hexdigest()})
    if not cases:
        raise ValueError("Case file has no cases")
    return {"name": document.get("name", Path(path).stem), "label_scope": document.get("label_scope", ""),
            "sha256": fingerprint(document), "cases": cases}


def evaluate(golden, config=None, *, limit=None, max_workers=3, min_interval_s=0.0):
    config = config or LLMConfig.from_env()
    pacer = common.Pacer(min_interval_s)
    cases = golden["cases"][:limit] if limit else golden["cases"]
    prompt = load_prompt(PROMPT_ID)
    started = time.monotonic()
    rows = []
    with tempfile.TemporaryDirectory(prefix="neuron-shadow-eval-") as workspace:
        with Runtime(workspace, agents=shadow_registry(config), max_workers=max_workers) as runtime:
            for case in cases:
                pacer.wait()
                job_id = "eval_" + case["case_id"]
                runtime.submit(build_shadow_workflow(
                    job_id, {"case_id": case["case_id"], "summary": case["summary"]}, config))
                rows.append(case_row(case, runtime.run(job_id)))
    return {"schema": "neuron-flow-shadow-eval-v1",
            "provenance": {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           "git_sha": os.environ.get("GITHUB_SHA") or _git_sha(),
                           "python": platform.python_version(), "llm": config.to_params(),
                           "prompt": {"id": prompt.id, "sha256": prompt.sha256},
                           "golden": {"name": golden["name"], "sha256": golden["sha256"], "cases": len(cases),
                                      "label_scope": golden["label_scope"]},
                           "duration_s": round(time.monotonic() - started, 2),
                           "min_interval_s": pacer.min_interval_s},
            "metrics": compute_metrics(rows), "cases": rows}


def case_row(case, snapshot):
    steps = snapshot["steps"]

    def output(step_id):
        return steps[step_id]["output"] if steps[step_id]["status"] == "SUCCEEDED" else None

    rules, llm, final = output("classify_rules"), output("classify_llm"), output("prepare")
    llm_state = steps["classify_llm"]
    ok = llm is not None and llm["status"] == "ok"
    if ok:
        status, reason = "ok", None
    elif llm is not None:
        status, reason = "unavailable", llm["reason"]
    else:
        status, reason = "failed", (llm_state.get("error") or {}).get("type")
    usage = llm["usage"] if ok else {"input_tokens": 0, "output_tokens": 0, "estimated": False}
    return {"case_id": case["case_id"], "language": case["language"], "tags": case["tags"],
            "split": case["split"], "cluster_id": case["cluster_id"], "source_sha256": case["source_sha256"],
            "summary": case["summary"], "expected": case["expected_category"], "job_status": snapshot["status"],
            "rules_category": rules["category"] if rules else None,
            "llm_status": status, "llm_reason": reason,
            "llm_category": llm["category"] if ok else None,
            "llm_confidence": llm["confidence"] if ok else None,
            "llm_attempts": llm_state["attempts"], "llm_latency_ms": llm["latency_ms"] if ok else None,
            "input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"],
            "usage_estimated": usage["estimated"],
            "agreement": final["agreement"] if final else None,
            "review_priority": final["review_priority"] if final else None,
            "review_reasons": final["review_reasons"] if final else []}


def compute_metrics(rows):
    answered = [r for r in rows if r["llm_status"] == "ok"]
    rules_wrong = [r for r in rows if r["rules_category"] != r["expected"]]
    elevated = [r for r in rows if r["review_priority"] == "elevated"]
    disagreements = [r for r in answered if r["llm_category"] != r["rules_category"]]
    latencies = [r["llm_latency_ms"] for r in answered]

    def scores(subset):
        sub_answered = [r for r in subset if r["llm_status"] == "ok"]
        return {"cases": len(subset),
                "rules_correct": _rate(sum(r["rules_category"] == r["expected"] for r in subset), len(subset)),
                "llm_correct": _rate(sum(r["llm_category"] == r["expected"] for r in sub_answered), len(sub_answered))}

    tags = sorted({tag for r in rows for tag in r["tags"]})
    return {
        "cases": len(rows),
        "jobs_completed": _rate(sum(r["job_status"] == "SUCCEEDED" for r in rows), len(rows)),
        "rules_correct": _rate(len(rows) - len(rules_wrong), len(rows)),
        "llm_answered": _rate(len(answered), len(rows)),
        "llm_correct": _rate(sum(r["llm_category"] == r["expected"] for r in answered), len(answered)),
        "agreement": _rate(len(answered) - len(disagreements), len(answered)),
        "elevated_review": _rate(len(elevated), len(rows)),
        # Is the AI flag useful? Share of rule mistakes it raised, and share of raises that were needed.
        "rules_errors_flagged": _rate(sum(r["review_priority"] == "elevated" for r in rules_wrong), len(rules_wrong)),
        "flags_needed": _rate(sum(r["rules_category"] != r["expected"] for r in elevated), len(elevated)),
        "llm_unavailable": _rate(sum(r["llm_status"] == "unavailable" for r in rows), len(rows)),
        "llm_failed": _rate(sum(r["llm_status"] == "failed" for r in rows), len(rows)),
        "when_disagreeing": {
            "total": len(disagreements),
            "llm_right": sum(r["llm_category"] == r["expected"] for r in disagreements),
            "rules_right": sum(r["rules_category"] == r["expected"] for r in disagreements),
            "neither": sum(r["expected"] not in (r["llm_category"], r["rules_category"]) for r in disagreements)},
        "by_language": {lang: scores([r for r in rows if r["language"] == lang]) for lang in LANGUAGES
                        if any(r["language"] == lang for r in rows)},
        "by_tag": {tag: scores([r for r in rows if tag in r["tags"]]) for tag in tags},
        "tokens": {"input": sum(r["input_tokens"] for r in rows), "output": sum(r["output_tokens"] for r in rows),
                   "estimated": any(r["usage_estimated"] for r in rows)},
        "llm_latency_ms": {"p50": percentile(latencies, .5), "p95": percentile(latencies, .95)},
        "both_wrong": [r["case_id"] for r in rows if r["rules_category"] != r["expected"]
                       and r["llm_category"] != r["expected"]],
    }


def gate_rows(report):
    """Rows for neuron_flow.evaluation.candidate_gate (detects any change in AI outcomes)."""
    return [{"case_id": r["case_id"], "cluster_id": r["cluster_id"], "split": r["split"],
             "source_sha256": r["source_sha256"], "group": r["expected"],
             "outcome": r["llm_category"] or f"llm_{r['llm_status']}", "latency_ms": r["llm_latency_ms"] or 0,
             "attempts": max(1, r["llm_attempts"]),
             "first_method_success": r["llm_status"] == "ok" and r["llm_attempts"] == 1}
            for r in report["cases"]]


def compare_reports(reference, candidate, **limits):
    """Before switching prompt or model: did any case's AI outcome change?"""
    return candidate_gate(gate_rows(reference), gate_rows(candidate), **limits)


# -- eval gate (roadmap 5.2): every per-case answer against a committed baseline ------------------

BASELINE_SCHEMA = "neuron-flow-shadow-eval-baseline-v1"
REPORT_SCHEMA = "neuron-flow-shadow-eval-v1"
# What a case "answered". Timings and token counts are left out: they change from run to run.
ANSWER_FIELDS = ("source_sha256", "expected", "job_status", "rules_category", "llm_status", "llm_category",
                 "llm_reason", "llm_confidence", "llm_attempts", "agreement", "review_priority", "review_reasons")
_IDENTITY = (("golden", "case set"), ("llm", "AI"), ("prompt", "prompt"))
_HEAD = ("schema", "golden", "llm", "prompt")


def baseline_view(report):
    """A run's per-case answers and what produced them (case set, AI, prompt): the part the gate compares."""
    p = report["provenance"]
    return {"schema": BASELINE_SCHEMA,
            "golden": {key: p["golden"][key] for key in ("name", "sha256", "cases")},
            "llm": {"provider": p["llm"]["provider"], "model": p["llm"]["model"]},
            "prompt": {"id": p["prompt"]["id"], "sha256": p["prompt"]["sha256"]},
            "cases": [{"case_id": r["case_id"], **{field: r[field] for field in ANSWER_FIELDS}}
                      for r in report["cases"]]}


def as_baseline(document):
    """Accept a baseline file or a full report (``--out``); refuse anything else."""
    if isinstance(document, dict) and document.get("schema") == REPORT_SCHEMA:
        return baseline_view(document)
    return common.check_baseline(document, BASELINE_SCHEMA, _HEAD, ANSWER_FIELDS)


def baseline_json(baseline):
    """Stable text, one case per line, so a pull request's diff shows exactly which cases changed."""
    return common.baseline_text(baseline, _HEAD, ANSWER_FIELDS)


def answer_changes(reference, candidate):
    """Every difference between two baselines, one short English line each; empty when nothing changed."""
    return common.answer_changes(reference, candidate, _IDENTITY, ANSWER_FIELDS)


def gate_markdown(changes, compared_with, cases):
    """The gate's verdict for the run page (Thai first), with how to proceed when it fails."""
    return common.gate_markdown(changes, compared_with, cases, module="app.eval.triage_shadow_eval",
                                live_run="Shadow eval with Claude หรือ with GitHub Models")


def summary_markdown(report):
    m, p = report["metrics"], report["provenance"]
    llm = p["llm"]
    lines = ["## ผลวัดการคัดแยกเคสแบบคู่ขนาน (shadow mode)", ""]
    if llm["provider"] == "mock":
        lines += ["> **หมายเหตุ:** รอบนี้ใช้ \"AI จำลอง\" (mock) ซึ่งแค่จับคำสำคัญ ไม่ใช่ AI จริง "
                  "และรายการคำสำคัญถูกเขียนพร้อมกับชุดเคสนี้ คะแนนของ AI จึงสูงเกินจริงโดยตั้งใจ "
                  "ผลนี้ยืนยันว่าทุกขั้นของระบบและการวัดผลทำงานครบ แต่ไม่ได้บอกความแม่นยำของ AI จริง  ",
                  "> *Mock provider: a keyword simulation written alongside this case set, so its score is "
                  "inflated by design. This run proves the pipeline and the measurement work, not AI accuracy.*", ""]
    lines += common.github_models_note(llm)
    lines += [f"ชุดเคส `{p['golden']['name']}` ({p['golden']['cases']} เคส) · AI `{llm['provider']}/{llm['model']}` · "
              f"prompt `{p['prompt']['id']}` (`{p['prompt']['sha256'][:12]}`) · commit `{(p['git_sha'] or 'unknown')[:12]}`",
              "", "| สิ่งที่วัด | ผล |", "|---|---|",
              f"| งานที่ทำจบครบทุกขั้น | {_fmt(m['jobs_completed'])} |",
              f"| กฎเดิมจัดหมวดถูก | {_fmt(m['rules_correct'])} |",
              f"| AI ตอบได้ | {_fmt(m['llm_answered'])} |",
              f"| AI จัดหมวดถูก (เฉพาะที่ตอบได้) | {_fmt(m['llm_correct'])} |",
              f"| กฎกับ AI เห็นตรงกัน | {_fmt(m['agreement'])} |",
              f"| เคสที่ถูกยกเป็น \"ต้องดูก่อน\" | {_fmt(m['elevated_review'])} |",
              f"| ความผิดของกฎที่ถูกยกขึ้นมาให้คนดู | {_fmt(m['rules_errors_flagged'])} |",
              f"| การยกขึ้นที่จำเป็นจริง (กฎผิดจริง) | {_fmt(m['flags_needed'])} |",
              f"| AI ใช้งานไม่ได้ / ล้มเหลว | {m['llm_unavailable']['numerator']} / {m['llm_failed']['numerator']} |",
              f"| token ที่ใช้ เข้า / ออก | {m['tokens']['input']:,} / {m['tokens']['output']:,}"
              f"{' (ประมาณการ)' if m['tokens']['estimated'] else ''} |",
              f"| เวลาตอบของ AI p50 / p95 | {_ms(m['llm_latency_ms']['p50'])} / {_ms(m['llm_latency_ms']['p95'])} ms |",
              "", "### แยกตามภาษา", "", "| ภาษา | เคส | กฎถูก | AI ถูก |", "|---|---|---|---|"]
    for lang, score in m["by_language"].items():
        lines.append(f"| {LANGUAGES[lang]} | {score['cases']} | {_fmt(score['rules_correct'])} | {_fmt(score['llm_correct'])} |")
    d = m["when_disagreeing"]
    lines += ["", f"### เมื่อกฎกับ AI เห็นไม่ตรงกัน ({d['total']} เคส) ใครถูก", "",
              "| AI ถูก | กฎถูก | ผิดทั้งคู่ |", "|---|---|---|",
              f"| {d['llm_right']} | {d['rules_right']} | {d['neither']} |", ""]
    rows = {r["case_id"]: r for r in report["cases"]}
    if m["both_wrong"]:
        lines += ["### เคสที่ผิดทั้งกฎและ AI (ควรดูต่อ)", ""]
        for case_id in m["both_wrong"]:
            r = rows[case_id]
            lines.append(f"- `{case_id}` ควรเป็น **{r['expected']}** · กฎ: {r['rules_category']} · "
                         f"AI: {r['llm_category'] or r['llm_status']} · \"{r['summary'][:80]}\"")
        lines.append("")
    lines.append(f"_{p['golden']['label_scope']}_")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--golden", default=str(DEFAULT_GOLDEN), help="labelled case file")
    parser.add_argument("--limit", type=int, default=None, help="only the first N cases")
    parser.add_argument("--min-interval-s", type=float, default=0.0,
                        help="wait at least this long between two cases (rate-limited free tiers)")
    parser.add_argument("--out", help="write the full JSON report here")
    parser.add_argument("--summary", help="append the markdown summary here (e.g. $GITHUB_STEP_SUMMARY)")
    parser.add_argument("--compare-with",
                        help="baseline file or earlier JSON report; exit 3 if any per-case answer differs")
    parser.add_argument("--write-baseline", help="write this run's per-case answers as a baseline file")
    args = parser.parse_args(argv)
    # Read the reference first, so a missing or broken file fails before the run, not after it.
    reference = as_baseline(decode(Path(args.compare_with).read_bytes())) if args.compare_with else None
    report = evaluate(load_golden(args.golden), limit=args.limit, min_interval_s=args.min_interval_s)
    text = summary_markdown(report)
    print(text)
    if args.out:
        Path(args.out).write_text(_json(report), encoding="utf-8")
    if args.write_baseline:
        Path(args.write_baseline).write_text(baseline_json(baseline_view(report)), encoding="utf-8")
    code = 0 if report["metrics"]["jobs_completed"]["rate"] == 1 else 1
    if reference is not None:
        changes = answer_changes(reference, baseline_view(report))
        verdict = gate_markdown(changes, args.compare_with, len(report["cases"]))
        print(verdict)
        text += "\n" + verdict
        code = code or (3 if changes else 0)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as stream:
            stream.write(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
