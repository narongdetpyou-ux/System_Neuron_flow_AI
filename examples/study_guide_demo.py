"""Four synthetic requests through the study guide (study_guide.v1), with the layered answer for each.

From the repository root:  python -m examples.study_guide_demo [--summary FILE]
Uses the offline mock AI (a keyword simulation, not an AI model) unless NEURON_FLOW_LLM_PROVIDER=anthropic
and ANTHROPIC_API_KEY are set (Claude), or NEURON_FLOW_LLM_PROVIDER=typhoon and TYPHOON_API_KEY (Typhoon). ``--summary`` appends a Thai/English Markdown report, for example to
``$GITHUB_STEP_SUMMARY``, so the answers can be read on the GitHub Actions run page.
"""

import argparse
import tempfile

from neuron_flow import Runtime
from app.domains.study_guide import build_study_workflow, study_registry
from app.llm import LLMConfig
from app.observability import init_sentry, run_job

REQUESTS = [
    ("demo_metaphor_th", "อยากมีรั้วกั้นไม่ให้ AI ออกนอกลู่นอกทาง"),
    ("demo_plain_en", "How do I write a good prompt?"),
    ("demo_owner_metaphor", "อยากให้ระบบเป็นเหมือนบรรณารักษ์ที่รู้ใจ"),
    ("demo_out_of_scope", "ขอสูตรต้มยำกุ้งน้ำข้นหน่อย"),
]
STATUS_TH = {"guide": "ได้แผนการเรียน", "out_of_scope": "อยู่นอกกรอบ", "not_understood": "ยังเข้าใจคำขอไม่ได้"}


def _cell(text):
    return " ".join(str(text).replace("|", "/").replace("`", "'").split())


def summary_markdown(config, results):
    simulated = config.provider == "mock"
    lines = ["## ผู้ช่วยแนะนำแหล่งเรียน: ตัวอย่างคำตอบ (study guide demo)", "",
             f"AI: `{config.provider}/{config.model}`"
             + (" — **AI จำลอง** จับคำสำคัญ ไม่ใช่ AI จริง คำตอบจึงบอกได้แค่ว่าระบบทำงานครบทุกขั้น ไม่ได้วัดความเข้าใจ"
                if simulated else ""), ""]
    for text, answer in results:
        lines += [f"### “{_cell(text)}”", ""]
        if answer is None:
            lines += ["งานไม่สำเร็จ ดู log ของขั้นตอนนี้", ""]
            continue
        lines += [f"- ผล: **{STATUS_TH[answer['status']]}** (`{answer['status']}`)",
                  f"- สรุป 1 บรรทัด: {_cell(answer['summary'])}"]
        if answer["restatement"]:
            lines.append(f"- ระบบเข้าใจว่า: {_cell(answer['restatement'])} — {answer['confirm_question']}")
        if answer["steps"]:
            lines += ["", "| ลำดับ | แหล่ง | ระดับ | ภาษา | ความสำคัญ | ลิงก์ (จากคลัง) |", "|---|---|---|---|---|---|"]
            for step in answer["steps"]:
                lines.append(f"| {step['order']} | {_cell(step['title'])} | {step['level_label']} | {step['language']} | "
                             f"{_cell(step['priority_label'])} | {step['url']} |")
        if answer["details"]["prerequisites_left_out"]:
            names = ", ".join(item["name"] for item in answer["details"]["prerequisites_left_out"])
            lines.append(f"\nหัวข้อพื้นฐานที่ไม่ได้ใส่ เพราะเกิน 5 แหล่ง: {names}")
        if answer["can_help_with"]:
            lines.append("\nหัวข้อที่ผู้ช่วยช่วยได้: " + ", ".join(item["name"] for item in answer["can_help_with"]))
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--summary", help="append a Markdown report here (e.g. $GITHUB_STEP_SUMMARY)")
    args = parser.parse_args(argv)
    init_sentry()  # no-op unless SENTRY_DSN is set and sentry-sdk is installed
    config = LLMConfig.from_env()
    print(f"AI provider: {config.provider}/{config.model}"
          + ("  (offline keyword simulation, not an AI model)" if config.provider == "mock" else ""))
    results, failed = [], 0
    with tempfile.TemporaryDirectory(prefix="neuron-study-demo-") as workspace:
        with Runtime(workspace, agents=study_registry(config)) as runtime:
            for job_id, text in REQUESTS:
                runtime.submit(build_study_workflow(job_id, {"message": text}, config))
                snapshot = run_job(runtime, job_id)
                answer = snapshot["steps"]["answer"].get("output")
                results.append((text, answer))
                print(f"\n\"{text}\" -> job {snapshot['status']}")
                if answer is None:
                    failed += 1
                    continue
                print(f"  status: {answer['status']} ({answer['language']}); summary: {answer['summary']}")
                for step in answer["steps"]:
                    print(f"  {step['order']}. [{step['priority']}] {step['title']} ({step['level']}, "
                          f"{step['language']}) {step['url']}")
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as stream:
            stream.write(summary_markdown(config, results))
    if failed:
        raise SystemExit("The study guide demo did not complete")


if __name__ == "__main__":
    main()
