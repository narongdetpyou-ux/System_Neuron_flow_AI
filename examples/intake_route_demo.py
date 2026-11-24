"""Five synthetic messages through the plain-language router (intake.route.v1, roadmap 4.2), with its answer for each.

From the repository root:  python -m examples.intake_route_demo [--summary FILE]
Uses the offline mock AI (a keyword simulation, not an AI model) unless NEURON_FLOW_LLM_PROVIDER is set to a real
provider with its key. ``--summary`` appends a Thai/English Markdown report, for example to ``$GITHUB_STEP_SUMMARY``,
so the owner can read on the GitHub Actions run page what the router answers. The router never runs a task: every
answer here stops before a job is created.
"""

import argparse
import tempfile

from neuron_flow import Runtime

from app.domains.intake import build_route_workflow, route_registry
from app.llm import LLMConfig
from app.services.workflows import router_frame

MESSAGES = [
    ("demo_case_th", "ลูกค้าบอกว่าอัปโหลดไฟล์แนบไม่ได้ ค้างที่ 99%"),
    ("demo_case_en", "The customer was charged twice for one order"),
    ("demo_study_th", "อยากเรียนวิธีเขียน prompt ให้ AI เข้าใจงาน"),
    ("demo_out_of_scope", "ขอสูตรต้มยำกุ้งน้ำข้นหน่อย"),
    ("demo_too_little", "ลืมรหัสผ่าน"),
]
KIND_TH = {"proposal": "เสนองาน (รอคนกด \"ใช่ ทำเลย\" ก่อน)", "confirm": "เล่ากลับให้ยืนยัน (AI ไม่มั่นใจ)",
           "question": "ถามกลับ 1 คำถาม", "out_of_scope": "บอกตรง ๆ ว่าอยู่นอกกรอบ",
           "not_understood": "ยังอ่านข้อความไม่ได้ (ให้เลือกงานเอง)"}


def _cell(text):
    return " ".join(str(text).replace("|", "/").replace("`", "'").split())


def run(config=None):
    config = config or LLMConfig.from_env()
    frame = router_frame()
    names = {task["id"]: task["name"]["th"] for task in frame["tasks"]}
    results = []
    with tempfile.TemporaryDirectory(prefix="neuron-route-demo-") as workspace:
        with Runtime(workspace, agents=route_registry(config, frame), max_workers=2) as runtime:
            for job_id, text in MESSAGES:
                runtime.submit(build_route_workflow(job_id, {"message": text}, config, frame=frame))
                snapshot = runtime.run(job_id)
                state = snapshot["steps"]["respond"]
                results.append((text, state["output"] if state["status"] == "SUCCEEDED" else None))
    return config, names, results


def summary_markdown(config, names, results):
    simulated = config.provider == "mock"
    lines = ["## ตัวอ่านข้อความ: ตัวอย่างคำตอบ (router demo, ขั้น 4.2)", "",
             f"AI: `{config.provider}/{config.model}`"
             + (" — **AI จำลอง** จับคำสำคัญ ไม่ใช่ AI จริง คำตอบจึงบอกได้แค่ว่าระบบทำงานครบทุกขั้น ไม่ได้วัดความเข้าใจ"
                if simulated else ""),
             "", "ตัวอ่านข้อความไม่สร้างงานเอง ทุกคำตอบข้างล่างหยุดก่อนสร้างงาน (ปุ่ม \"ใช่ ทำเลย\" มาในขั้น 4.2 ส่วนที่สอง)", "",
             "| ข้อความ | ระบบตอบแบบไหน | งานที่เข้าใจ | สิ่งที่ระบบพูด |", "|---|---|---|---|"]
    for text, answer in results:
        if answer is None:
            lines.append(f"| {_cell(text)} | งานไม่สำเร็จ (ดู log) | – | – |")
            continue
        said = answer["question"] or answer["intro"] or answer["restatement"] or ""
        if answer["kind"] in ("proposal", "confirm"):
            said = f"{answer['restatement']} · {answer['confirm_question']}"
        task = names.get(answer["task"], "–") if answer["task"] else "–"
        lines.append(f"| {_cell(text)} | {KIND_TH[answer['kind']]} | {_cell(task)} | {_cell(said)} |")
    lines += ["", "*The router answers in one of five kinds and never creates a job; a person confirms a proposal first.*", ""]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--summary", help="append the Markdown report here (e.g. $GITHUB_STEP_SUMMARY)")
    args = parser.parse_args(argv)
    text = summary_markdown(*run())
    print(text)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as stream:
            stream.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
