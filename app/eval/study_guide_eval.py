"""Scorecard for the study guide (roadmap 3.3): does it find the right topic, refuse what is out of scope,
and keep its two promises (only library links, at most 5 resources) on every answer?

Flow:
1. load the labelled request set and check its shape: Thai and English, plain requests, paraphrases,
   metaphors, out-of-scope requests and injection attempts, none of them a catalog example;
2. run every request through the real ``study_guide.v1`` workflow on a fresh temporary Runtime;
3. read each answer and compare it with the label;
4. compute the scorecard (every rate keeps its numerator and denominator);
5. write a JSON report and a Thai/English markdown summary (shown on GitHub Actions).

Run: ``python -m app.eval.study_guide_eval --summary summary.md --out report.json``

What is measured:
* **topic accuracy**: requests that belong to a topic, whose topic detection answered, and whose detected
  topic is one of the labelled ones (a request may accept two topics, such as the owner's librarian);
* **out of scope**: precision (requests answered "out of scope" that really are) and recall (out-of-scope
  requests that were caught), plus in-scope requests wrongly turned away;
* **the promises**, which must hold on every answer: links outside the library (must be 0) and answers
  with more than 5 resources (must be 0). The run fails (exit 1) when either is broken, or when a job did
  not finish.

Labels are synthetic and developer-written. With the mock provider (a keyword simulation built from the
catalog examples, before this set was written) the numbers test the pipeline, not understanding.

Eval gate (roadmap 5.2): ``--compare-with <baseline or report>`` fails (exit 3) when any request's answer
differs (detection, explanation, the answer's status and the chosen resources in order), or when the
request set, the AI, a prompt or the library differs. CI compares every push with
``tests/baselines/study_guide_eval_mock.json``; regenerate it on purpose with ``--write-baseline`` in the
same pull request and say why.
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

from app.domains.study_guide import build_study_workflow, check_message, load_library, study_registry
from app.domains.study_guide.contracts import (DETECT_PROMPT_ID, EXPLAIN_PROMPT_ID, LIBRARY_VERSION,
                                               MAX_RESOURCES)
from app.domains.study_guide.library import OUT_OF_SCOPE
from app.llm import LLMConfig, load_prompt

from . import common
from .common import fmt_ms, fmt_rate, rate

DEFAULT_GOLDEN = Path(__file__).with_name("golden") / "study_guide_synthetic_v1.json"
GOLDEN_SCHEMA = "neuron-flow-study-golden-v1"
LANGUAGES = {"th": "ไทย (TH)", "en": "อังกฤษ (EN)"}
TAGS = {"plain": "ถามตรง ๆ", "paraphrase": "พูดอ้อม / คำพูดต่างกัน", "metaphor": "คำเปรียบเปรย",
        "out_of_scope": "นอกกรอบ", "injection": "คำสั่งแอบแฝง", "owner_example": "ตัวอย่างของเจ้าของโปรเจกต์"}
_CASE_KEYS = {"case_id", "language", "expected", "tags", "message"}
_CASE_ID = re.compile(r"^[A-Z]{2}-[A-Z]{3}-\d{2}$")
_THAI = re.compile(r"[฀-๿]")
REPORT_SCHEMA = "neuron-flow-study-eval-v1"
BASELINE_SCHEMA = "neuron-flow-study-eval-baseline-v1"
# What a request "answered". Timings and token counts are left out: they change from run to run.
ANSWER_FIELDS = ("source_sha256", "expected", "job_status", "detect_status", "detect_reason", "detected_topic",
                 "confidence", "detected_language", "detect_attempts", "explain_status", "answer_status",
                 "explanation_source", "resource_ids", "links_outside_library")
_HEAD = ("schema", "golden", "llm", "prompts", "library")
_IDENTITY = (("golden", "request set"), ("llm", "AI"), ("prompts", "prompt"), ("library", "library"))


def _normal(text):
    return " ".join(text.casefold().split())


def load_golden(path=DEFAULT_GOLDEN, library=None):
    """Read and check the request set. Raises ``ValueError`` with the first problem found."""
    library = library or load_library(LIBRARY_VERSION)
    document = decode(Path(path).read_bytes())
    if (not isinstance(document, dict) or document.get("schema") != GOLDEN_SCHEMA
            or set(document) != {"schema", "name", "library", "label_scope", "cases"}):
        raise ValueError(f"Request file must use schema {GOLDEN_SCHEMA} with name, library, label_scope, cases")
    if document["library"] != library.version:
        raise ValueError(f"Request file is labelled for library {document['library']}, not {library.version}")
    topics = {topic.id for topic in library.topics} | {OUT_OF_SCOPE}
    examples = {_normal(p) for topic in library.topics for p in topic.examples_th + topic.examples_en}
    cases, seen = [], set()
    for index, case in enumerate(document["cases"] or []):
        where = f"request at position {index}"
        if not isinstance(case, dict) or set(case) != _CASE_KEYS:
            raise ValueError(f"{where}: needs exactly {sorted(_CASE_KEYS)}")
        if not isinstance(case["case_id"], str) or not _CASE_ID.fullmatch(case["case_id"]) or case["case_id"] in seen:
            raise ValueError(f"{where}: invalid or repeated case_id")
        expected, tags, message = case["expected"], case["tags"], case["message"]
        if (not isinstance(expected, list) or not expected or len(set(expected)) != len(expected)
                or not set(expected) <= topics or (OUT_OF_SCOPE in expected and len(expected) > 1)):
            raise ValueError(f"{where}: expected must list known topics, or out_of_scope alone")
        if not isinstance(tags, list) or not tags or not set(tags) <= set(TAGS) or len(set(tags)) != len(tags):
            raise ValueError(f"{where}: tags must be a non-empty list from {sorted(TAGS)}")
        if ("out_of_scope" in tags) != (expected == [OUT_OF_SCOPE]):
            raise ValueError(f"{where}: the out_of_scope tag must match the label")
        if case["language"] not in LANGUAGES:
            raise ValueError(f"{where}: unknown language")
        try:
            check_message({"message": message})
        except ValueError as exc:  # SpecError is a ValueError
            raise ValueError(f"{where}: {exc}") from None
        if (case["language"] == "th") != bool(_THAI.search(message)):
            raise ValueError(f"{where}: a th request must be written in Thai, an en request without Thai")
        if _normal(message) in examples:
            raise ValueError(f"{where}: the message is a catalog example; detection must be tested on new phrases")
        seen.add(case["case_id"])
        cases.append({**case, "source_sha256": hashlib.sha256(message.strip().encode("utf-8")).hexdigest()})
    if not cases:
        raise ValueError("Request file has no requests")
    return {"name": document["name"], "label_scope": document["label_scope"], "sha256": fingerprint(document),
            "cases": cases}


def evaluate(golden, config=None, *, limit=None, max_workers=3, min_interval_s=0.0):
    config = config or LLMConfig.from_env()
    pacer = common.Pacer(min_interval_s)
    library = load_library(LIBRARY_VERSION)
    urls = {resource.id: resource.url for resource in library.resources}
    cases = golden["cases"][:limit] if limit else golden["cases"]
    started = time.monotonic()
    rows = []
    with tempfile.TemporaryDirectory(prefix="neuron-study-eval-") as workspace:
        with Runtime(workspace, agents=study_registry(config), max_workers=max_workers) as runtime:
            for case in cases:
                pacer.wait()
                job_id = "eval_" + case["case_id"].replace("-", "_")
                runtime.submit(build_study_workflow(job_id, {"message": case["message"]}, config))
                rows.append(case_row(case, runtime.run(job_id), urls))
    prompts = {key: {"id": prompt.id, "sha256": prompt.sha256}
               for key, prompt in (("detect", load_prompt(DETECT_PROMPT_ID)), ("explain", load_prompt(EXPLAIN_PROMPT_ID)))}
    return {"schema": REPORT_SCHEMA,
            "provenance": {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           "git_sha": os.environ.get("GITHUB_SHA") or common.git_sha(),
                           "python": platform.python_version(), "llm": config.to_params(), "prompts": prompts,
                           "library": library.tag,
                           "golden": {"name": golden["name"], "sha256": golden["sha256"], "cases": len(cases),
                                      "label_scope": golden["label_scope"]},
                           "duration_s": round(time.monotonic() - started, 2),
                           "min_interval_s": pacer.min_interval_s},
            "metrics": compute_metrics(rows), "cases": rows}


def _ai_record(state):
    """``(status, reason, output)`` of an AI step: ok / unavailable / skipped, or failed when the step failed."""
    if state.get("status") != "SUCCEEDED":
        return "failed", (state.get("error") or {}).get("type"), None
    output = state["output"]
    return output["status"], output.get("reason"), output


def case_row(case, snapshot, urls):
    steps = snapshot["steps"]
    detect_status, detect_reason, detected = _ai_record(steps["detect_topic"])
    explain_status, explain_reason, explained = _ai_record(steps["explain"])
    answer = steps["answer"]["output"] if steps["answer"]["status"] == "SUCCEEDED" else None
    ok = detect_status == "ok"
    usage = [record["usage"] for record in (detected, explained) if record and record.get("status") == "ok"]
    resources = [step["resource_id"] for step in answer["steps"]] if answer else []
    outside = sum(step.get("url") != urls.get(step.get("resource_id")) for step in answer["steps"]) if answer else 0
    return {"case_id": case["case_id"], "language": case["language"], "tags": case["tags"],
            "message": case["message"], "source_sha256": case["source_sha256"], "expected": case["expected"],
            "job_status": snapshot["status"],
            "detect_status": detect_status, "detect_reason": detect_reason,
            "detected_topic": detected["topic"] if ok else None,
            "confidence": detected["confidence"] if ok else None,
            "detected_language": detected["language"] if ok else None,
            "detect_attempts": steps["detect_topic"].get("attempts", 0),
            "detect_latency_ms": detected["latency_ms"] if ok else None,
            "explain_status": explain_status, "explain_reason": explain_reason,
            "answer_status": answer["status"] if answer else None,
            "explanation_source": answer["details"]["explanation_source"] if answer else None,
            "resource_ids": resources, "links_outside_library": outside,
            "confirm_asked": bool(answer and answer["confirm_question"]),
            "input_tokens": sum(u["input_tokens"] for u in usage), "output_tokens": sum(u["output_tokens"] for u in usage),
            "usage_estimated": any(u["estimated"] for u in usage)}


def _correct(row):
    return row["detect_status"] == "ok" and row["detected_topic"] in row["expected"]


def compute_metrics(rows):
    answered = [r for r in rows if r["detect_status"] == "ok"]
    in_scope = [r for r in answered if r["expected"] != [OUT_OF_SCOPE]]
    out_of_scope = [r for r in answered if r["expected"] == [OUT_OF_SCOPE]]
    called_out = [r for r in answered if r["detected_topic"] == OUT_OF_SCOPE]
    answers = [r for r in rows if r["answer_status"] is not None]
    guides = [r for r in answers if r["answer_status"] == "guide"]
    links = sum(len(r["resource_ids"]) for r in answers)
    outside = sum(r["links_outside_library"] for r in answers)
    over_five = [r["case_id"] for r in answers if len(r["resource_ids"]) > MAX_RESOURCES]
    latencies = [r["detect_latency_ms"] for r in answered]
    injection = [r for r in rows if "injection" in r["tags"]]

    def scores(subset):
        sub_answered = [r for r in subset if r["detect_status"] == "ok"]
        sub_in = [r for r in sub_answered if r["expected"] != [OUT_OF_SCOPE]]
        return {"cases": len(subset), "correct": rate(sum(map(_correct, sub_answered)), len(sub_answered)),
                "topic_correct": rate(sum(map(_correct, sub_in)), len(sub_in))}

    complete = all(r["job_status"] == "SUCCEEDED" for r in rows)
    return {
        "cases": len(rows),
        "jobs_completed": rate(sum(r["job_status"] == "SUCCEEDED" for r in rows), len(rows)),
        "detection_answered": rate(len(answered), len(rows)),
        "topic_correct": rate(sum(map(_correct, in_scope)), len(in_scope)),
        "correct": rate(sum(map(_correct, answered)), len(answered)),
        "out_of_scope_precision": rate(sum(r["expected"] == [OUT_OF_SCOPE] for r in called_out), len(called_out)),
        "out_of_scope_recall": rate(sum(r["detected_topic"] == OUT_OF_SCOPE for r in out_of_scope), len(out_of_scope)),
        "in_scope_turned_away": rate(sum(r["detected_topic"] == OUT_OF_SCOPE for r in in_scope), len(in_scope)),
        "links_outside_library": {"count": outside, "links_shown": links},
        "answers_over_five": {"count": len(over_five), "answers": len(answers), "cases": over_five},
        "asked_to_confirm": rate(sum(r["confirm_asked"] for r in answered), len(answered)),
        "explained_by_ai": rate(sum(r["explanation_source"] == "ai" for r in guides), len(guides)),
        "injection": {"cases": len(injection), "correct": rate(sum(map(_correct, injection)), len(injection)),
                      "links_outside_library": sum(r["links_outside_library"] for r in injection)},
        "detection_unavailable": rate(sum(r["detect_status"] == "unavailable" for r in rows), len(rows)),
        "detection_failed": rate(sum(r["detect_status"] == "failed" for r in rows), len(rows)),
        "by_language": {lang: scores([r for r in rows if r["language"] == lang]) for lang in LANGUAGES
                        if any(r["language"] == lang for r in rows)},
        "by_tag": {tag: scores([r for r in rows if tag in r["tags"]]) for tag in TAGS
                   if any(tag in r["tags"] for r in rows)},
        "tokens": {"input": sum(r["input_tokens"] for r in rows), "output": sum(r["output_tokens"] for r in rows),
                   "estimated": any(r["usage_estimated"] for r in rows)},
        "detect_latency_ms": {"p50": percentile(latencies, .5), "p95": percentile(latencies, .95)},
        "mistakes": [{"case_id": r["case_id"], "expected": r["expected"],
                      "got": r["detected_topic"] if r["detect_status"] == "ok" else f"detection_{r['detect_status']}"}
                     for r in rows if not _correct(r)],
        "promises_kept": complete and outside == 0 and not over_five,
    }


# -- eval gate (roadmap 5.2) ------------------------------------------------------------------------

def baseline_view(report):
    """A run's per-request answers and what produced them: the part the gate compares."""
    p = report["provenance"]
    return {"schema": BASELINE_SCHEMA,
            "golden": {key: p["golden"][key] for key in ("name", "sha256", "cases")},
            "llm": {"provider": p["llm"]["provider"], "model": p["llm"]["model"]},
            "prompts": {f"{key}_{part}": p["prompts"][key][part] for key in ("detect", "explain") for part in ("id", "sha256")},
            "library": {"tag": p["library"]},
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
    return common.gate_markdown(changes, compared_with, cases, module="app.eval.study_guide_eval",
                                live_run="Study guide eval with Claude หรือ with Typhoon")


# -- the report ---------------------------------------------------------------------------------------

def summary_markdown(report):
    m, p = report["metrics"], report["provenance"]
    llm = p["llm"]
    lines = ["## ผลวัดผู้ช่วยแนะนำแหล่งเรียน (study guide scorecard)", ""]
    if llm["provider"] == "mock":
        lines += ["> **หมายเหตุ:** รอบนี้ใช้ \"AI จำลอง\" (mock) ซึ่งแค่จับคำสำคัญที่มาจากตัวอย่างในสมุดหัวข้อ ไม่ใช่ AI จริง "
                  "ชุดข้อสอบนี้เขียนทีหลัง ไม่ใช้ประโยคตัวอย่าง และไม่ได้แก้คำสำคัญให้ตรงข้อสอบ AI จำลองจึงพลาดคำเปรียบเปรยเกือบทั้งหมด "
                  "ผลนี้บอกว่าทุกขั้นและการวัดผลทำงานครบ และคำมั่นสองข้อ (ลิงก์จากคลังเท่านั้น ไม่เกิน 5 แหล่ง) เป็นจริง "
                  "แต่ไม่ได้บอกว่าผู้ช่วยเข้าใจคนได้ดีแค่ไหน  ",
                  "> *Mock provider: a keyword simulation built from the catalog examples before this set was written, "
                  "and not tuned to it. It proves the pipeline, the measurement and the two promises, not understanding.*",
                  ""]
    lines += common.provider_note(llm)
    links = m["links_outside_library"]
    over = m["answers_over_five"]
    lines += [f"ชุดข้อสอบ `{p['golden']['name']}` ({p['golden']['cases']} คำขอ) · AI `{llm['provider']}/{llm['model']}` · "
              f"คลัง `{p['library'][:22]}…` · commit `{(p['git_sha'] or 'unknown')[:12]}`", "",
              "| สิ่งที่วัด | ผล |", "|---|---|",
              f"| งานที่ทำจบครบทุกขั้น | {fmt_rate(m['jobs_completed'])} |",
              f"| AI ถอดความได้ (ตอบ) | {fmt_rate(m['detection_answered'])} |",
              f"| **หัวข้อถูก** (คำขอที่อยู่ในกรอบ) | {fmt_rate(m['topic_correct'])} |",
              f"| ตอบถูกทุกแบบ (รวมนอกกรอบ) | {fmt_rate(m['correct'])} |",
              f"| นอกกรอบ: ที่ตอบว่านอกกรอบ ถูกจริง (precision) | {fmt_rate(m['out_of_scope_precision'])} |",
              f"| นอกกรอบ: จับได้ครบแค่ไหน (recall) | {fmt_rate(m['out_of_scope_recall'])} |",
              f"| คำขอในกรอบที่ถูกตอบว่านอกกรอบ | {fmt_rate(m['in_scope_turned_away'])} |",
              f"| **ลิงก์นอกคลัง** (ต้องเป็น 0) | {links['count']} จาก {links['links_shown']} ลิงก์ |",
              f"| **คำตอบที่เกิน 5 แหล่ง** (ต้องเป็น 0) | {over['count']} จาก {over['answers']} คำตอบ |",
              f"| ถาม \"เข้าใจถูกไหม\" (เมื่อถอดความได้) | {fmt_rate(m['asked_to_confirm'])} |",
              f"| คำอธิบายเขียนโดย AI (คำตอบที่ได้แผน) | {fmt_rate(m['explained_by_ai'])} |",
              f"| คำสั่งแอบแฝง: ตอบหัวข้อถูก / ลิงก์นอกคลัง | {fmt_rate(m['injection']['correct'])} / "
              f"{m['injection']['links_outside_library']} |",
              f"| AI ใช้งานไม่ได้ / ล้มเหลว | {m['detection_unavailable']['numerator']} / {m['detection_failed']['numerator']} |",
              f"| token ที่ใช้ เข้า / ออก (2 ขั้น AI) | {m['tokens']['input']:,} / {m['tokens']['output']:,}"
              f"{' (ประมาณการ)' if m['tokens']['estimated'] else ''} |",
              f"| เวลาตอบของขั้นถอดความ p50 / p95 | {fmt_ms(m['detect_latency_ms']['p50'])} / {fmt_ms(m['detect_latency_ms']['p95'])} ms |",
              "", f"**คำมั่น (ลิงก์จากคลังเท่านั้น · ไม่เกิน 5 แหล่ง · งานจบครบ): "
              f"{'เป็นจริงทุกคำตอบ' if m['promises_kept'] else 'ไม่เป็นจริง — ต้องแก้ก่อน merge'}**", "",
              *common.reason_line(report["cases"], "detect_status", "detect_reason"),
              "### แยกตามภาษา", "", "| ภาษา | คำขอ | หัวข้อถูก (ในกรอบ) | ตอบถูกทุกแบบ |", "|---|---|---|---|"]
    for lang, score in m["by_language"].items():
        lines.append(f"| {LANGUAGES[lang]} | {score['cases']} | {fmt_rate(score['topic_correct'])} | {fmt_rate(score['correct'])} |")
    lines += ["", "### แยกตามแบบของคำขอ", "", "| แบบ | คำขอ | ตอบถูก |", "|---|---|---|"]
    for tag, score in m["by_tag"].items():
        lines.append(f"| {TAGS[tag]} (`{tag}`) | {score['cases']} | {fmt_rate(score['correct'])} |")
    if m["mistakes"]:
        rows = {r["case_id"]: r for r in report["cases"]}
        lines += ["", f"### คำขอที่ตอบไม่ตรงกับที่ควร ({len(m['mistakes'])} ข้อ)", ""]
        for item in m["mistakes"][:40]:
            text = " ".join(rows[item["case_id"]]["message"].replace("|", "/").replace("`", "'").split())[:80]
            lines.append(f"- `{item['case_id']}` ควรเป็น **{' หรือ '.join(item['expected'])}** · ได้ `{item['got']}` · \"{text}\"")
        if len(m["mistakes"]) > 40:
            lines.append(f"- … และอีก {len(m['mistakes']) - 40} ข้อ")
    lines += ["", f"_{p['golden']['label_scope']}_"]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--golden", default=str(DEFAULT_GOLDEN), help="labelled request file")
    parser.add_argument("--limit", type=int, default=None, help="only the first N requests")
    parser.add_argument("--min-interval-s", type=float, default=0.0,
                        help="wait at least this long between two requests (rate-limited free tiers)")
    parser.add_argument("--out", help="write the full JSON report here")
    parser.add_argument("--summary", help="append the markdown summary here (e.g. $GITHUB_STEP_SUMMARY)")
    parser.add_argument("--compare-with",
                        help="baseline file or earlier JSON report; exit 3 if any per-request answer differs")
    parser.add_argument("--write-baseline", help="write this run's per-request answers as a baseline file")
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
