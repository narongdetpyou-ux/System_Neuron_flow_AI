"""One case, step by step, through the skill-handoff exchange (ADR-030, docs/skill_handoff.md).

From the repository root:  python -m examples.skill_handoff_demo [--summary FILE]

Everything runs offline in a temporary folder, through the same API, queue, Runner and Core as the web page, with
the offline mock AI. ``--summary`` appends a Thai/English Markdown report, for example to ``$GITHUB_STEP_SUMMARY``,
so the owner can read on the Actions run page what each part did:

1. a case is sent (``POST /v1/jobs``) and the Runner runs ``case_triage.v2``; it waits for a person;
2. a person approves it (``POST /v1/reviews/{id}/decisions``; the demo clicks for them);
3. the exchange finds the route, the out-translator turns the case into facts of the common language, only the
   facts the route needs are kept, and the in-translator turns them into the input of ``case_triage.v2.apply``;
4. the Runner runs the apply job, which records where the case goes, with a Core receipt;
5. the same click again changes nothing; a rejected case hands on nothing; nobody can start the apply skill from
   outside; and when a translation cannot be done, the handoff is refused with a reason instead of a guess.
"""

import argparse
import json
from pathlib import Path
import tempfile

from app.api.routes import ApiApp, Request
from app.exchange import TRANSLATORS, SourceView
from app.llm import LLMConfig
from app.persistence import QueueStore
from app.services.runner import Runner
from app.settings import Settings

KEY = "skill-handoff-demo-" + "k" * 16
CASE = {"case_id": "DEMO-HANDOFF-1", "summary": "เดือนนี้ถูกหักค่าบริการสองครั้ง ขอคืนเงินด้วยครับ"}
OTHER = {"case_id": "DEMO-HANDOFF-2", "summary": "I cannot upload an attachment to my ticket"}
ORIGIN_TH = {"input": "คนพิมพ์เข้ามา", "rules": "โค้ดหรือกฎ", "person": "คนตัดสิน", "ai": "AI เสนอ (เป็นแค่ข้อมูล)"}
CATEGORY_TH = {"access": "เข้าระบบ / บัญชี", "upload": "อัปโหลดไฟล์", "billing": "การเงิน", "other": "เรื่องอื่น ๆ"}


class Demo:
    def __init__(self, folder):
        self.settings = Settings(data_dir=Path(folder), storage="configured", access_key=KEY, runner_poll_s=0.05)
        self.store = QueueStore(self.settings.queue_db)
        self.store.migrate()
        self.app = ApiApp(self.settings, self.store)
        self.config = LLMConfig()  # the offline mock

    def call(self, method, path, body=None):
        headers = {"authorization": f"Bearer {KEY}", "content-type": "application/json"}
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else b""
        reply = self.app.handle(Request(method, path, {}, headers, data, "demo"))
        return reply.status, json.loads(reply.body)

    def run_jobs(self):
        Runner(self.settings, store=self.store, llm_config=self.config).drain()

    def decide(self, job_id, decision, key):
        review = "rev_" + job_id[len("job_"):]
        return self.call("POST", f"/v1/reviews/{review}/decisions",
                         {"decision": decision, "reason": "ตรวจแล้ว (การกดจำลองในตัวอย่าง)", "expected_version": 1,
                          "idempotency_key": key})


def cell(value):
    return " ".join(str(value).replace("|", "/").split())


def run(folder):
    demo = Demo(folder)
    out = ["## การส่งต่อระหว่างทักษะ: ตัวอย่างทีละขั้น (skill handoff demo)", "",
           "ทำงานจริงผ่าน API คิว ตัวรันงาน และ Core ชุดเดียวกับหน้าเว็บ ใช้ AI จำลอง (mock) ข้อมูลสมมุติทั้งหมด", ""]

    # 1. A case is sent and waits for a person.
    status, job = demo.call("POST", "/v1/jobs", {"workflow_type": "case_triage.v2",
                                                 "idempotency_key": "demo-handoff-case-1", "input": CASE})
    demo.run_jobs()
    source = demo.call("GET", f"/v1/jobs/{job['job_id']}")[1]
    review = source["result"]["review"]
    out += ["### ขั้น 1: ส่งเคส แล้วระบบทำงานจนรอคนตัดสิน", "",
            f"- ข้อความเคส: “{CASE['summary']}” (`POST /v1/jobs` → {status})",
            f"- ผล: **{source['status']}** · กฎเสนอ {CATEGORY_TH[review['suggested_category']]} → `{review['suggested_queue']}`",
            "- ตอนนี้ยังไม่มีอะไรถูกส่งต่อ เพราะยังไม่มีคนตัดสิน", ""]

    # 2. A person approves it.
    status, decided = demo.decide(job["job_id"], "APPROVE", "demo-handoff-decide-1")
    [handoff] = decided["handoffs"]
    route = next(r for r in demo.call("GET", "/v1/status")[1]["handoff"]["routes"] if r["id"] == handoff["route_id"])
    out += ["### ขั้น 2: คนกด \"อนุมัติ\" (ตัวอย่างนี้กดแทน)", "",
            f"- `POST /v1/reviews/…/decisions` → {status} · การตัดสิน `{decided['decision']['decision_id']}`",
            f"- ตัวกลางหาเส้นทางเจอ: `{route['id']}` — {route['why']['th']}", ""]

    # 3. What the translators did, in the common language.
    stored = demo.store.get(job["job_id"])
    decision_row = demo.store.review_of_job(job["job_id"])["decision"]
    given = TRANSLATORS[handoff["translator_out"]].function(
        SourceView(stored["workflow_type"], stored["status"], stored["input"], stored["result"], decision_row))
    meanings = demo.call("GET", "/v1/status")[1]["handoff"]["facts"]
    kept = {item["name"] for item in handoff["facts"]}
    out += ["### ขั้น 3: ล่ามขาออกแปลเป็นภาษากลาง แล้วตัวกลางเก็บไว้เฉพาะที่เส้นทางต้องใช้", "",
            f"ล่ามขาออก `{handoff['translator_out']}` · สมุดคำศัพท์กลาง `{handoff['vocabulary_version'][:40]}…`", "",
            "| ข้อมูล (fact) | ความหมาย | ค่า | มาจาก | ส่งต่อไหม |", "|---|---|---|---|---|"]
    for name in sorted(given):
        item = given[name]
        value = f"ข้อความ {len(item['value'])} ตัวอักษร" if meanings[name]["type"] == "text" else item["value"]
        out.append(f"| `{name}` | {cell(meanings[name]['meaning']['th'])} | {cell(value)} | {ORIGIN_TH[item['origin']]} | "
                   f"{'ส่งต่อ' if name in kept else 'ไม่ส่ง (เส้นทางนี้ไม่ใช้)'} |")
    target = demo.store.get(handoff["target_job_id"])
    out += ["", f"ล่ามขาเข้า `{handoff['translator_in']}` แปลเป็นภาษาของงานปลายทาง แล้วผ่านด่านตรวจของงานนั้นเอง:", "",
            "```json", json.dumps(target["input"], ensure_ascii=False, indent=1), "```",
            f"งานใหม่ `{target['job_id']}` ถูกสร้างพร้อมกับการตัดสินในครั้งเดียว (สถานะ {target['status']})", ""]

    # 4. The apply job runs.
    demo.run_jobs()
    applied = demo.call("GET", f"/v1/jobs/{target['job_id']}")[1]
    record = applied["result"]["output"]
    out += ["### ขั้น 4: งานบันทึกผลหลังอนุมัติทำงาน", "",
            f"- ผล: **{applied['status']}** · บันทึกว่าไป `{record['final_queue']}` · อนุมัติโดย `{record['approved_by']}` · "
            f"ส่งออกนอกระบบ: {'ไม่' if not record['sends_outside'] else 'ใช่'}",
            f"- ใบรับจาก Core (SHA-256): `{applied['result']['receipt']['sha256'][:16]}…`", ""]

    # 5. The guarantees.
    again_status, again = demo.decide(job["job_id"], "APPROVE", "demo-handoff-decide-1")
    _, rejected_job = demo.call("POST", "/v1/jobs", {"workflow_type": "case_triage.v2",
                                                     "idempotency_key": "demo-handoff-case-2", "input": OTHER})
    demo.run_jobs()
    _, rejected = demo.decide(rejected_job["job_id"], "REJECT", "demo-handoff-decide-2")
    forged_status, forged = demo.call("POST", "/v1/jobs", {"workflow_type": "case_triage.v2.apply",
                                                           "idempotency_key": "demo-forged-apply", "input": target["input"]})
    refused = demo.app.exchange.prepare(dict(stored, result={"review": None}), decision=decision_row)
    applies = [j for j in demo.store.list_jobs(limit=100)[0] if j["workflow_type"] == "case_triage.v2.apply"]
    out += ["### ขั้น 5: สิ่งที่ระบบรับประกัน", "",
            f"- กด \"อนุมัติ\" ซ้ำด้วยรหัสเดิม → {again_status} การตัดสินเดิม ส่งต่อเดิม ({len(again['handoffs'])} ครั้ง) "
            f"งานบันทึกผลทั้งหมด {len(applies)} งาน",
            f"- เคสที่ \"ไม่อนุมัติ\" → ส่งต่อ {len(rejected['handoffs'])} ครั้ง",
            f"- คนข้างนอกเรียกงานบันทึกผลตรง ๆ → {forged_status} `{forged['error']}`",
            f"- ถ้าข้อมูลต้นทางไม่ครบ → ตัวกลางไม่เดา: `{refused['state']}` เหตุผล `{refused['reason']}` งานต้นทางยังเป็นผลเดิม",
            "- ข้อความเคสไม่ถูกส่งต่อ: " + ("ผ่าน" if CASE["summary"] not in json.dumps(
                [target["input"], demo.store.handoffs_from(job["job_id"])], ensure_ascii=False) else "ไม่ผ่าน"),
            "", "In English: a case was approved, the exchange translated it through the common language into the input "
            "of the apply skill, and the apply job recorded the decision with a Core receipt; a repeated click, a "
            "rejection, a forged request and an incomplete source each started nothing.", ""]
    ok = (applied["status"] == "COMPLETED" and again_status == 200 and len(applies) == 1 and not rejected["handoffs"]
          and forged_status == 400 and refused["state"] == "REFUSED")
    return "\n".join(out) + "\n", ok


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--summary", help="append a Markdown report to this file (for $GITHUB_STEP_SUMMARY)")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as folder:
        report, ok = run(folder)
    print(report)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as handle:
            handle.write(report)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
