"""Skill-handoff check over the existing triage case sets (ADR-030; the owner asked on 2026-11-11 for the new
exchange to be tested "with the old sets too").

Every case of each set goes end to end through the real service parts, on a fresh temporary data folder, with the
offline mock AI:

1. admission (``POST /v1/jobs``'s own code) and the Runner, which runs ``case_triage.v2`` on Core;
2. a person's decision through the reviews service with the exchange, in a fixed pattern: every fifth case is
   rejected, every third of the rest is approved with another category than the rules suggested, the others are
   approved as proposed; then the same click again, which must change nothing;
3. the Runner again, which runs every ``case_triage.v2.apply`` job the approvals started.

Checks for each case (any failure makes the exit status 1):
* an approval started exactly one handoff and one apply job; it completed with a Core receipt, and its routing
  record holds exactly the approved category, its queue and the decision id;
* a rejection started nothing; a repeated click started nothing either;
* the case text is in no envelope, no apply job's input and no event.

The mock AI only shapes the proposals here; it does not change what the exchange must do, so this measures the
exchange and its route, not triage accuracy. Run it with ``python -m tests.handoff_check``; ``--summary FILE``
appends a Markdown report (Thai first) for the Actions run page, ``--json FILE`` writes the per-case rows.
"""

import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

from app.domains.case_triage.contracts import CATEGORIES, QUEUE_FOR
from app.exchange import Exchange
from app.llm import LLMConfig
from app.persistence import QueueStore, review_id_for
from app.services import reviews
from app.services.admission import AdmissionError, admit
from app.services.runner import Runner
from app.services.workflows import CATALOG
from app.settings import Settings

ROOT = Path(__file__).resolve().parent.parent
SETS = {
    "development": ROOT / "app" / "eval" / "golden" / "case_triage_synthetic_v1.json",
    "heldout": ROOT / "app" / "eval" / "golden" / "case_triage_heldout_v1.json",
    "edge": ROOT / "tests" / "robustness" / "triage_edge_golden_v1.json",
}
SET_TH = {"development": "ชุดพัฒนา", "heldout": "ชุดที่กันไว้", "edge": "ชุดเคสยาก (ด่านความทนทาน)"}
REASON = "ตรวจแล้วตามชุดทดสอบการส่งต่อ"  # a fixed synthetic reason; a person's own words on the page


def plan_for(index, suggested):
    """The decision for the ``index``-th case: reject, approve with another category, or approve as proposed."""
    if index % 5 == 4:
        return "REJECT", None
    if index % 3 == 2:
        others = [c for c in CATEGORIES if c != suggested]
        return "APPROVE", others[index % len(others)]
    return "APPROVE", suggested


def run(set_names, workdir):
    settings = Settings(data_dir=Path(workdir), storage="configured", access_key="handoff-eval-" + "k" * 16,
                        runner_poll_s=0.05)
    store = QueueStore(settings.queue_db)
    store.migrate()
    exchange = Exchange(CATALOG)
    cases = []
    for name in set_names:
        for case in json.loads(SETS[name].read_text(encoding="utf-8"))["cases"]:
            cases.append((name, case))
    rows = []
    for name, case in cases:
        row = {"set": name, "case_id": case["case_id"], "problems": []}
        body = {"workflow_type": "case_triage.v2", "idempotency_key": f"handoff-eval-{name}-{case['case_id']}",
                "input": {"case_id": case["case_id"], "summary": case["summary"]}}
        try:
            job, _ = admit(store, body, max_queued=100000)
            row["job_id"] = job["job_id"]
        except AdmissionError as exc:
            row["admission"] = exc.code  # refused at the door, as for any request; counted, not a failure
        rows.append(row)
    config = LLMConfig()  # the offline mock: the proposals do not change what the exchange must do
    Runner(settings, store=store, llm_config=config).drain()
    for index, row in enumerate(rows):
        if "job_id" not in row:
            continue
        job = store.get(row["job_id"])
        row["status_before"] = job["status"]
        if job["status"] != "REVIEW_REQUIRED":
            row["problems"].append(f"expected REVIEW_REQUIRED, got {job['status']}")
            continue
        suggested = job["result"]["review"]["suggested_category"]
        decision, category = plan_for(index, suggested)
        row.update(decision=decision, suggested=suggested, final_category=category)
        request = {"decision": decision, "reason": REASON, "expected_version": 1,
                   "idempotency_key": f"handoff-eval-decide-{index:05d}"}
        if category is not None:
            request["final_category"] = category
        _review, decided, created = reviews.decide(store, review_id_for(row["job_id"]), request, exchange=exchange)
        row["decision_id"] = decided["decision_id"]
        _review, again, created_again = reviews.decide(store, review_id_for(row["job_id"]), request, exchange=exchange)
        if not created or created_again or again["decision_id"] != decided["decision_id"]:
            row["problems"].append("a repeated click was not idempotent")
    Runner(settings, store=store, llm_config=config).drain()
    for row in rows:
        if "decision" in row:
            check(store, row, cases[rows.index(row)][1]["summary"])
    return rows, store


def check(store, row, summary):
    handoffs = store.handoffs_from(row["job_id"])
    row["handoffs"] = [h["state"] for h in handoffs]
    events = json.dumps(store.events(row["job_id"], limit=100)[0], ensure_ascii=False)
    if summary in events or summary in json.dumps(handoffs, ensure_ascii=False):
        row["problems"].append("the case text reached an event or an envelope")
    if row["decision"] == "REJECT":
        if handoffs:
            row["problems"].append("a rejection started a handoff")
        return
    if row["handoffs"] != ["STARTED"]:
        row["problems"].append(f"expected one started handoff, got {row['handoffs']}")
        return
    target = store.get(handoffs[0]["target_job_id"])
    row["apply_status"] = target["status"]
    output = (target["result"] or {}).get("output") or {}
    expected = {"kind": "routing_record", "case_id": row["case_id"], "final_category": row["final_category"],
                "final_queue": QUEUE_FOR[row["final_category"]], "decision_id": row["decision_id"],
                "approved_by": "owner", "sends_outside": False}
    if target["status"] != "COMPLETED" or {k: output.get(k) for k in expected} != expected:
        row["problems"].append("the apply job did not record exactly the approved decision")
    if not (target["result"] or {}).get("receipt"):
        row["problems"].append("the apply job has no Core receipt")
    if summary in json.dumps(target["input"], ensure_ascii=False) or summary in json.dumps(
            store.events(target["job_id"], limit=100)[0], ensure_ascii=False):
        row["problems"].append("the case text reached the apply job")


def totals(rows, name=None):
    chosen = [r for r in rows if name is None or r["set"] == name]
    decided = [r for r in chosen if "decision" in r]
    approved = [r for r in decided if r["decision"] == "APPROVE"]
    return {
        "cases": len(chosen),
        "refused_at_admission": sum("admission" in r for r in chosen),
        "approved_as_proposed": sum(r["final_category"] == r["suggested"] for r in approved),
        "approved_changed": sum(r["final_category"] != r["suggested"] for r in approved),
        "rejected": len(decided) - len(approved),
        "handoffs_started": sum(r.get("handoffs") == ["STARTED"] for r in approved),
        "apply_completed": sum(r.get("apply_status") == "COMPLETED" for r in approved),
        "rejections_without_handoff": sum(not r.get("handoffs") for r in decided if r["decision"] == "REJECT"),
        "problems": sum(len(r["problems"]) for r in chosen),
    }


def markdown(rows, set_names, seconds):
    every = totals(rows)
    ok = every["problems"] == 0
    lines = ["## การส่งต่อระหว่างทักษะ: ทดสอบกับชุดเคสเดิม (skill handoff check)", "",
             f"**{'ผ่านทุกข้อ' if ok else 'ไม่ผ่าน'}** · {every['cases']} เคส · ใช้เวลา {seconds:.0f} วินาที · AI จำลอง (mock)", "",
             "ทุกเคสผ่านระบบจริงทั้งสาย: รับเข้าคิว → ตัวรันงาน → คนตัดสิน (จำลองการกด) → ตัวกลางกับล่าม → งานบันทึกผล", "",
             "| ชุด | เคส | อนุมัติตามข้อเสนอ | อนุมัติแต่เปลี่ยนหมวด | ไม่อนุมัติ | ส่งต่อสำเร็จ | งานบันทึกผลเสร็จ | ไม่อนุมัติแล้วไม่ส่งต่อ | ปัญหา |",
             "|---|---|---|---|---|---|---|---|---|"]
    for name in set_names:
        t = totals(rows, name)
        lines.append(f"| {SET_TH[name]} | {t['cases']} | {t['approved_as_proposed']} | {t['approved_changed']} | "
                     f"{t['rejected']} | {t['handoffs_started']} | {t['apply_completed']} | "
                     f"{t['rejections_without_handoff']} | {t['problems']} |")
    lines += ["", "สิ่งที่ตรวจทุกเคส: อนุมัติแล้วเกิดงานบันทึกผลพอดี 1 งานที่บันทึกหมวด คิว และรหัสการตัดสินตรงกับที่คนตัดสิน "
              "พร้อมใบรับจาก Core; ไม่อนุมัติแล้วไม่เกิดอะไร; กดซ้ำไม่เกิดงานซ้ำ; ข้อความเคสไม่ถูกส่งต่อและไม่อยู่ในบันทึกเหตุการณ์",
              "", "Every case ran end to end through admission, the Runner on Core, a decision through the reviews service "
              "with the exchange, and the apply job. The mock AI only shapes the proposals, so this measures the "
              "exchange and its route, not triage accuracy."]
    problems = [r for r in rows if r["problems"]]
    if problems:
        lines += ["", "### ปัญหาที่พบ (problems)", ""] + [f"- {r['set']} {r['case_id']}: {'; '.join(r['problems'])}"
                                                    for r in problems[:50]]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sets", default=",".join(SETS), help="comma-separated: " + ", ".join(SETS))
    parser.add_argument("--summary", help="append a Markdown report to this file (for $GITHUB_STEP_SUMMARY)")
    parser.add_argument("--json", help="write the per-case rows to this file")
    args = parser.parse_args(argv)
    names = [name.strip() for name in args.sets.split(",") if name.strip()]
    unknown = set(names) - set(SETS)
    if unknown:
        parser.error(f"unknown sets: {sorted(unknown)}")
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as workdir:
        rows, _store = run(names, workdir)
    seconds = time.monotonic() - started
    report = markdown(rows, names, seconds)
    print(report)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as handle:
            handle.write(report)
    if args.json:
        Path(args.json).write_text(json.dumps({"sets": names, "totals": totals(rows), "rows": rows},
                                              ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0 if totals(rows)["problems"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
