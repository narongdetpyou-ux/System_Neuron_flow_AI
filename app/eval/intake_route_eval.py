"""Scorecard for the plain-language router (roadmap 4.2, ADR-039): does it pick the right task of the frame, refuse
what is out of scope, ask one question when a message says too little, and keep its promises on every answer?

Flow:
1. load a labelled message set and check its shape: Thai and English, cases, paraphrases (Phase 4's gate pair
   among them), wishes to learn, metaphors, out-of-scope requests, messages that say too little and injection
   attempts, none of them an example of the frame;
2. run every message through the real ``intake.route.v1`` workflow on a fresh temporary Runtime;
3. read each answer and compare it with the label;
4. compute the scorecard (every rate keeps its numerator and denominator);
5. write a JSON report and a Thai/English markdown summary (shown on GitHub Actions).

Run: ``python -m app.eval.intake_route_eval --summary summary.md --out report.json`` (the development set), or
``--golden app/eval/golden/intake_route_heldout_v1.json`` for the held-out set.

What is measured:
* **task right**: messages that ask for a task, whose AI step answered, and whose task is the labelled one;
* **out of scope**: precision and recall, plus in-scope messages wrongly turned away;
* **one question when a message says too little**, and needless questions on messages that say enough;
* **the promises**, which must hold on every answer: every job ends, and the input of every proposal is the person's
  own message (the AI never writes a field). The run fails (exit 1) when either is broken. The router admits no job
  by construction (no admission code in its domain; ``tests/test_intake_route.py`` checks), so nothing here can
  create one.

Labels are synthetic and developer-written. With the mock provider (a keyword simulation, see
``app/domains/intake/mock_answers.py``) the numbers test the pipeline, not understanding.

Eval gate (roadmap 5.2): ``--compare-with <baseline or report>`` fails (exit 3) when any message's answer differs, or
when the message set, the AI, the prompt or the frame differs. CI compares every push with
``tests/baselines/intake_route_mock.json`` and ``intake_route_heldout_mock.json``; regenerate them on purpose with
``--write-baseline`` in the same pull request and say why.
"""

import argparse
import hashlib
import os
import platform
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from neuron_flow import Runtime
from neuron_flow.model import decode, fingerprint
from neuron_flow.telemetry import percentile

from app.domains.intake import build_route_workflow, check_message, route_registry
from app.domains.intake.contracts import KINDS, OUT_OF_SCOPE, UNDERSTAND_PROMPT_ID
from app.llm import LLMConfig, load_prompt
from app.services.workflows import router_frame

from . import common
from .common import fmt_ms, fmt_rate, rate

DEFAULT_GOLDEN = Path(__file__).with_name("golden") / "intake_route_v1.json"
GOLDEN_SCHEMA = "neuron-flow-route-golden-v1"
LANGUAGES = {"th": "ไทย (TH)", "en": "อังกฤษ (EN)"}
TAGS = {"case": "เคสปัญหาของลูกค้า", "paraphrase": "คำพูดต่างกัน เรื่องเดียวกัน", "study": "อยากเรียน",
        "metaphor": "คำเปรียบเปรย", "out_of_scope": "นอกกรอบ", "needs_more": "ข้อมูลไม่พอ", "injection": "คำสั่งแอบแฝง"}
KIND_TH = {"proposal": "เสนองาน", "confirm": "เล่ากลับให้ยืนยัน", "question": "ถามกลับ 1 คำถาม",
           "out_of_scope": "นอกกรอบ", "not_understood": "ยังอ่านไม่ได้"}
_CASE_KEYS = {"case_id", "language", "tags", "expected", "message"}
_CASE_ID = re.compile(r"^RT-(?:DEV|HLD)-\d{2}$")
_THAI = re.compile(r"[฀-๿]")
REPORT_SCHEMA = "neuron-flow-route-eval-v1"
BASELINE_SCHEMA = "neuron-flow-route-eval-baseline-v1"
# What a message "answered". Timings and token counts are left out: they change from run to run.
ANSWER_FIELDS = ("source_sha256", "expected", "job_status", "understand_status", "understand_reason", "task",
                 "confidence", "detected_language", "needs_more", "also_study", "understand_attempts", "check_reason",
                 "kind", "offered_study", "input_is_message")
_HEAD = ("schema", "golden", "llm", "prompts", "frame")
_IDENTITY = (("golden", "message set"), ("llm", "AI"), ("prompts", "prompt"), ("frame", "frame"))


def _normal(text):
    return " ".join(text.casefold().split())


def load_golden(path=DEFAULT_GOLDEN, frame=None):
    """Read and check a message set. Raises ``ValueError`` with the first problem found."""
    frame = frame or router_frame()
    document = decode(Path(path).read_bytes())
    if (not isinstance(document, dict) or document.get("schema") != GOLDEN_SCHEMA
            or set(document) != {"schema", "name", "frame", "label_scope", "cases"}):
        raise ValueError(f"Message file must use schema {GOLDEN_SCHEMA} with name, frame, label_scope, cases")
    version = frame["frame_version"].split("@", 1)[0]
    if document["frame"] != version:
        raise ValueError(f"Message file is labelled for frame {document['frame']}, not {version}")
    tasks = {task["id"] for task in frame["tasks"]} | {OUT_OF_SCOPE}
    examples = {_normal(p) for task in frame["tasks"] for p in task["examples"]["th"] + task["examples"]["en"]}
    cases, seen = [], set()
    for index, case in enumerate(document["cases"] or []):
        where = f"message at position {index}"
        if not isinstance(case, dict) or set(case) != _CASE_KEYS:
            raise ValueError(f"{where}: needs exactly {sorted(_CASE_KEYS)}")
        if not isinstance(case["case_id"], str) or not _CASE_ID.fullmatch(case["case_id"]) or case["case_id"] in seen:
            raise ValueError(f"{where}: invalid or repeated case_id")
        expected, tags, message = case["expected"], case["tags"], case["message"]
        if (not isinstance(expected, dict) or set(expected) != {"task", "needs_more"}
                or expected["task"] not in tasks or expected["needs_more"] not in (True, False, None)):
            raise ValueError(f"{where}: expected needs a known task (or out_of_scope) and needs_more true, false or null")
        if expected["task"] == OUT_OF_SCOPE and expected["needs_more"] is not False:
            raise ValueError(f"{where}: an out-of-scope message never needs more")
        if not isinstance(tags, list) or not tags or not set(tags) <= set(TAGS) or len(set(tags)) != len(tags):
            raise ValueError(f"{where}: tags must be a non-empty list from {sorted(TAGS)}")
        if "out_of_scope" in tags and expected["task"] != OUT_OF_SCOPE:
            raise ValueError(f"{where}: the out_of_scope tag needs the out_of_scope label")
        if ("needs_more" in tags) != (expected["needs_more"] is True):
            raise ValueError(f"{where}: the needs_more tag must match the label")
        if case["language"] not in LANGUAGES:
            raise ValueError(f"{where}: unknown language")
        try:
            check_message({"message": message})
        except ValueError as exc:  # SpecError is a ValueError
            raise ValueError(f"{where}: {exc}") from None
        if (case["language"] == "th") != bool(_THAI.search(message)):
            raise ValueError(f"{where}: a th message must be written in Thai, an en message without Thai")
        if _normal(message) in examples:
            raise ValueError(f"{where}: the message is an example of the frame; the router must be tested on new phrases")
        seen.add(case["case_id"])
        cases.append({**case, "source_sha256": hashlib.sha256(message.strip().encode("utf-8")).hexdigest()})
    if not cases:
        raise ValueError("Message file has no messages")
    return {"name": document["name"], "label_scope": document["label_scope"], "sha256": fingerprint(document),
            "cases": cases}


def evaluate(golden, config=None, *, frame=None, limit=None, max_workers=3, min_interval_s=0.0):
    config = config or LLMConfig.from_env()
    frame = frame or router_frame()
    pacer = common.Pacer(min_interval_s)
    cases = golden["cases"][:limit] if limit else golden["cases"]
    started = time.monotonic()
    rows = []
    with tempfile.TemporaryDirectory(prefix="neuron-route-eval-") as workspace:
        with Runtime(workspace, agents=route_registry(config, frame), max_workers=max_workers) as runtime:
            for case in cases:
                pacer.wait()
                job_id = "eval_" + case["case_id"].replace("-", "_")
                runtime.submit(build_route_workflow(job_id, {"message": case["message"]}, config, frame=frame))
                rows.append(case_row(case, runtime.run(job_id)))
    prompt = load_prompt(UNDERSTAND_PROMPT_ID)
    return {"schema": REPORT_SCHEMA,
            "provenance": {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           "git_sha": os.environ.get("GITHUB_SHA") or common.git_sha(),
                           "python": platform.python_version(), "llm": config.to_params(),
                           "prompts": {"understand": {"id": prompt.id, "sha256": prompt.sha256}},
                           "frame": frame["frame_version"],
                           "golden": {"name": golden["name"], "sha256": golden["sha256"], "cases": len(cases),
                                      "label_scope": golden["label_scope"]},
                           "duration_s": round(time.monotonic() - started, 2),
                           "min_interval_s": pacer.min_interval_s},
            "metrics": compute_metrics(rows), "cases": rows}


def case_row(case, snapshot):
    steps = snapshot["steps"]
    state = steps["understand"]
    if state.get("status") != "SUCCEEDED":
        status, reason, understood = "failed", (state.get("error") or {}).get("type"), None
    else:
        understood = state["output"]
        status, reason = understood["status"], understood.get("reason")
    ok = status == "ok"
    checked = steps["check"]["output"] if steps["check"]["status"] == "SUCCEEDED" else None
    reply = steps["respond"]["output"] if steps["respond"]["status"] == "SUCCEEDED" else None
    proposing = reply is not None and reply["kind"] in ("proposal", "confirm")
    usage = understood["usage"] if ok else {"input_tokens": 0, "output_tokens": 0, "estimated": False}
    return {"case_id": case["case_id"], "language": case["language"], "tags": case["tags"], "message": case["message"],
            "source_sha256": case["source_sha256"], "expected": case["expected"], "job_status": snapshot["status"],
            "understand_status": status, "understand_reason": reason,
            "task": understood["task"] if ok else None, "confidence": understood["confidence"] if ok else None,
            "detected_language": understood["language"] if ok else None,
            "needs_more": understood["needs_more"] if ok else None,
            "also_study": understood["also_study"] if ok else None,
            "understand_attempts": state.get("attempts", 0), "latency_ms": understood["latency_ms"] if ok else None,
            "restatement": understood["restatement"] if ok else None,
            "check_reason": checked["reason"] if checked else None, "kind": reply["kind"] if reply else None,
            "offered_study": bool(reply and reply["also"]),
            # The promise that the AI never writes a field: a proposal carries the person's own message, unchanged.
            "input_is_message": (list(reply["input"].values()) == [case["message"].strip()]) if proposing else None,
            "input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"],
            "usage_estimated": usage["estimated"]}


def _correct(row):
    return row["understand_status"] == "ok" and row["task"] == row["expected"]["task"]


def compute_metrics(rows):
    answered = [r for r in rows if r["understand_status"] == "ok"]
    in_scope = [r for r in answered if r["expected"]["task"] != OUT_OF_SCOPE]
    out_of_scope = [r for r in answered if r["expected"]["task"] == OUT_OF_SCOPE]
    called_out = [r for r in answered if r["task"] == OUT_OF_SCOPE]
    needs_more = [r for r in rows if r["expected"]["needs_more"] is True]
    says_enough = [r for r in rows if r["expected"]["needs_more"] is False and r["expected"]["task"] != OUT_OF_SCOPE]
    proposals = [r for r in rows if r["input_is_message"] is not None]
    injection = [r for r in rows if "injection" in r["tags"]]
    latencies = [r["latency_ms"] for r in answered]

    def scores(subset):
        sub_answered = [r for r in subset if r["understand_status"] == "ok"]
        sub_in = [r for r in sub_answered if r["expected"]["task"] != OUT_OF_SCOPE]
        return {"cases": len(subset), "correct": rate(sum(map(_correct, sub_answered)), len(sub_answered)),
                "task_correct": rate(sum(map(_correct, sub_in)), len(sub_in))}

    complete = all(r["job_status"] == "SUCCEEDED" for r in rows)
    own_words = all(r["input_is_message"] for r in proposals)
    return {
        "cases": len(rows),
        "jobs_completed": rate(sum(r["job_status"] == "SUCCEEDED" for r in rows), len(rows)),
        "understood": rate(len(answered), len(rows)),
        "task_correct": rate(sum(map(_correct, in_scope)), len(in_scope)),
        "correct": rate(sum(map(_correct, answered)), len(answered)),
        "out_of_scope_precision": rate(sum(r["expected"]["task"] == OUT_OF_SCOPE for r in called_out), len(called_out)),
        "out_of_scope_recall": rate(sum(r["task"] == OUT_OF_SCOPE for r in out_of_scope), len(out_of_scope)),
        "in_scope_turned_away": rate(sum(r["task"] == OUT_OF_SCOPE for r in in_scope), len(in_scope)),
        "question_when_needed": rate(sum(r["kind"] == "question" for r in needs_more), len(needs_more)),
        "needless_questions": rate(sum(r["kind"] == "question" for r in says_enough), len(says_enough)),
        "kinds": {kind: sum(r["kind"] == kind for r in rows) for kind in KINDS},
        "study_offered": sum(r["offered_study"] for r in rows),
        "proposals_in_own_words": rate(sum(bool(r["input_is_message"]) for r in proposals), len(proposals)),
        "injection": {"cases": len(injection), "correct": rate(sum(map(_correct, injection)), len(injection)),
                      "jobs_created": 0},
        "understand_unavailable": rate(sum(r["understand_status"] == "unavailable" for r in rows), len(rows)),
        "understand_failed": rate(sum(r["understand_status"] == "failed" for r in rows), len(rows)),
        "by_language": {lang: scores([r for r in rows if r["language"] == lang]) for lang in LANGUAGES
                        if any(r["language"] == lang for r in rows)},
        "by_tag": {tag: scores([r for r in rows if tag in r["tags"]]) for tag in TAGS
                   if any(tag in r["tags"] for r in rows)},
        "tokens": {"input": sum(r["input_tokens"] for r in rows), "output": sum(r["output_tokens"] for r in rows),
                   "estimated": any(r["usage_estimated"] for r in rows)},
        "understand_latency_ms": {"p50": percentile(latencies, .5), "p95": percentile(latencies, .95)},
        "mistakes": [{"case_id": r["case_id"], "expected": r["expected"]["task"],
                      "got": r["task"] if r["understand_status"] == "ok" else f"understand_{r['understand_status']}",
                      "kind": r["kind"]}
                     for r in rows if not _correct(r)],
        "promises_kept": complete and own_words,
    }


# -- eval gate (roadmap 5.2) ------------------------------------------------------------------------

def baseline_view(report):
    """A run's per-message answers and what produced them: the part the gate compares."""
    p = report["provenance"]
    return {"schema": BASELINE_SCHEMA,
            "golden": {key: p["golden"][key] for key in ("name", "sha256", "cases")},
            "llm": {"provider": p["llm"]["provider"], "model": p["llm"]["model"]},
            "prompts": {"understand_id": p["prompts"]["understand"]["id"],
                        "understand_sha256": p["prompts"]["understand"]["sha256"]},
            "frame": {"tag": p["frame"]},
            "cases": [{"case_id": r["case_id"], **{field: r[field] for field in ANSWER_FIELDS}}
                      for r in report["cases"]]}


def as_baseline(document):
    """Accept a baseline file or a full report (``--out``); refuse anything else."""
    if isinstance(document, dict) and document.get("schema") == REPORT_SCHEMA:
        return baseline_view(document)
    return common.check_baseline(document, BASELINE_SCHEMA, _HEAD, ANSWER_FIELDS)


def baseline_json(baseline):
    return common.baseline_text(baseline, _HEAD, ANSWER_FIELDS)


def answer_changes(reference, candidate):
    return common.answer_changes(reference, candidate, _IDENTITY, ANSWER_FIELDS)


def gate_markdown(changes, compared_with, cases):
    return common.gate_markdown(changes, compared_with, cases, module="app.eval.intake_route_eval",
                                live_run="a Typhoon run of this scorecard from a session (docs/intake_router.md)")


# -- the report ---------------------------------------------------------------------------------------

def summary_markdown(report):
    m, p = report["metrics"], report["provenance"]
    llm = p["llm"]
    lines = ["## ผลวัดตัวอ่านข้อความ (router scorecard, ขั้น 4.2)", ""]
    if llm["provider"] == "mock":
        lines += ["> **หมายเหตุ:** รอบนี้ใช้ \"AI จำลอง\" (mock) ซึ่งแค่จับคำสำคัญ ไม่ใช่ AI จริง และไม่ได้เลือกคำจากชุดข้อสอบนี้ "
                  "ผลนี้บอกว่าทุกขั้นและการวัดผลทำงานครบ และคำมั่น (งานจบครบ · งานที่เสนอใช้คำของคนเองเสมอ) เป็นจริง "
                  "แต่ไม่ได้บอกว่าตัวอ่านข้อความเข้าใจคนได้ดีแค่ไหน  ",
                  "> *Mock provider: a keyword simulation. It proves the pipeline, the measurement and the promises, not "
                  "understanding.*", ""]
    lines += common.provider_note(llm)
    kinds = " · ".join(f"{KIND_TH[kind]} {count}" for kind, count in m["kinds"].items())
    lines += [f"ชุดข้อสอบ `{p['golden']['name']}` ({p['golden']['cases']} ข้อความ) · AI `{llm['provider']}/{llm['model']}` · "
              f"สมุดงาน `{p['frame'][:22]}…` · commit `{(p['git_sha'] or 'unknown')[:12]}`", "",
              "| สิ่งที่วัด | ผล |", "|---|---|",
              f"| งานที่ทำจบครบทุกขั้น | {fmt_rate(m['jobs_completed'])} |",
              f"| AI ถอดความได้ (ตอบ) | {fmt_rate(m['understood'])} |",
              f"| **เลือกงานถูก** (ข้อความที่อยู่ในกรอบ) | {fmt_rate(m['task_correct'])} |",
              f"| ตอบถูกทุกแบบ (รวมนอกกรอบ) | {fmt_rate(m['correct'])} |",
              f"| นอกกรอบ: ที่ตอบว่านอกกรอบ ถูกจริง (precision) | {fmt_rate(m['out_of_scope_precision'])} |",
              f"| นอกกรอบ: จับได้ครบแค่ไหน (recall) | {fmt_rate(m['out_of_scope_recall'])} |",
              f"| ข้อความในกรอบที่ถูกตอบว่านอกกรอบ | {fmt_rate(m['in_scope_turned_away'])} |",
              f"| ข้อมูลไม่พอ แล้วถามกลับ 1 คำถาม | {fmt_rate(m['question_when_needed'])} |",
              f"| ข้อมูลพอแล้ว แต่ยังถามกลับ (ยิ่งน้อยยิ่งดี) | {fmt_rate(m['needless_questions'])} |",
              f"| **งานที่เสนอใช้คำของคนเอง** (ต้องครบทุกข้อ) | {fmt_rate(m['proposals_in_own_words'])} |",
              f"| คำสั่งแอบแฝง: เลือกงานถูก / งานที่ถูกสร้าง | {fmt_rate(m['injection']['correct'])} / "
              f"{m['injection']['jobs_created']} |",
              f"| แบบของคำตอบ | {kinds} |",
              f"| เสนอแหล่งเรียนเพิ่ม (กฎการตอบสนองแรก) | {m['study_offered']} ข้อความ |",
              f"| AI ใช้งานไม่ได้ / ล้มเหลว | {m['understand_unavailable']['numerator']} / {m['understand_failed']['numerator']} |",
              f"| token ที่ใช้ เข้า / ออก | {m['tokens']['input']:,} / {m['tokens']['output']:,}"
              f"{' (ประมาณการ)' if m['tokens']['estimated'] else ''} |",
              f"| เวลาตอบของขั้นถอดความ p50 / p95 | {fmt_ms(m['understand_latency_ms']['p50'])} / "
              f"{fmt_ms(m['understand_latency_ms']['p95'])} ms |",
              "", f"**คำมั่น (งานจบครบ · งานที่เสนอใช้คำของคนเองเสมอ · ตัวอ่านข้อความไม่สร้างงานเอง): "
              f"{'เป็นจริงทุกคำตอบ' if m['promises_kept'] else 'ไม่เป็นจริง — ต้องแก้ก่อน merge'}**", "",
              *common.reason_line(report["cases"], "understand_status", "understand_reason"),
              "### แยกตามภาษา", "", "| ภาษา | ข้อความ | เลือกงานถูก (ในกรอบ) | ตอบถูกทุกแบบ |", "|---|---|---|---|"]
    for lang, score in m["by_language"].items():
        lines.append(f"| {LANGUAGES[lang]} | {score['cases']} | {fmt_rate(score['task_correct'])} | {fmt_rate(score['correct'])} |")
    lines += ["", "### แยกตามแบบของข้อความ", "", "| แบบ | ข้อความ | ตอบถูก |", "|---|---|---|"]
    for tag, score in m["by_tag"].items():
        lines.append(f"| {TAGS[tag]} (`{tag}`) | {score['cases']} | {fmt_rate(score['correct'])} |")
    if m["mistakes"]:
        rows = {r["case_id"]: r for r in report["cases"]}
        lines += ["", f"### ข้อความที่เลือกงานไม่ตรงกับที่ควร ({len(m['mistakes'])} ข้อ)", ""]
        for item in m["mistakes"][:40]:
            text = " ".join(rows[item["case_id"]]["message"].replace("|", "/").replace("`", "'").split())[:80]
            lines.append(f"- `{item['case_id']}` ควรเป็น **{item['expected']}** · ได้ `{item['got']}` · \"{text}\"")
        if len(m["mistakes"]) > 40:
            lines.append(f"- … และอีก {len(m['mistakes']) - 40} ข้อ")
    lines += ["", f"_{p['golden']['label_scope']}_"]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--golden", default=str(DEFAULT_GOLDEN), help="labelled message file")
    parser.add_argument("--limit", type=int, default=None, help="only the first N messages")
    parser.add_argument("--min-interval-s", type=float, default=0.0,
                        help="wait at least this long between two messages (rate-limited free tiers)")
    parser.add_argument("--out", help="write the full JSON report here")
    parser.add_argument("--summary", help="append the markdown summary here (e.g. $GITHUB_STEP_SUMMARY)")
    parser.add_argument("--compare-with",
                        help="baseline file or earlier JSON report; exit 3 if any per-message answer differs")
    parser.add_argument("--write-baseline", help="write this run's per-message answers as a baseline file")
    args = parser.parse_args(argv)
    # Read the reference first, so a missing or broken file fails before the run, not after it.
    reference = as_baseline(decode(Path(args.compare_with).read_bytes())) if args.compare_with else None
    report = evaluate(load_golden(args.golden), limit=args.limit, min_interval_s=args.min_interval_s)
    text = summary_markdown(report)
    print(text)
    if args.out:
        Path(args.out).write_text(common.to_json(report), encoding="utf-8")
    if args.write_baseline:
        Path(args.write_baseline).write_text(baseline_json(baseline_view(report)), encoding="utf-8")
    code = 0 if report["metrics"]["promises_kept"] else 1
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
