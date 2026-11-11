"""What the scorecards share: rates with their numerator and denominator, and the eval gate's baseline file,
comparison and verdict (roadmap 5.2). Each scorecard says which fields make up a case's answer and which
parts of a run (case set, AI, prompts, library) must match."""

import json
import subprocess
import time
from pathlib import Path

MAX_LISTED_CHANGES = 40


class Pacer:
    """Keeps the starts of two cases at least ``min_interval_s`` seconds apart.

    Free tiers count requests per minute (Typhoon allows about 200, and 5 a second). Without pacing, a fast run
    would turn the limit into "unavailable" answers and measure the limit instead of the model. 0 = no wait.
    """

    def __init__(self, min_interval_s=0.0, *, clock=time.monotonic, sleep=time.sleep):
        if isinstance(min_interval_s, bool) or not isinstance(min_interval_s, (int, float)) \
                or not 0 <= min_interval_s <= 120:
            raise ValueError("min_interval_s must be between 0 and 120 seconds")
        self.min_interval_s = float(min_interval_s)
        self._clock, self._sleep, self._last = clock, sleep, None

    def wait(self):
        if self.min_interval_s <= 0:
            return
        now = self._clock()
        if self._last is not None and now < self._last + self.min_interval_s:
            self._sleep(self._last + self.min_interval_s - now)
            now = self._clock()
        self._last = now


def rate(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "rate": round(numerator / denominator, 4) if denominator else None}


def fmt_rate(value):
    if not value["denominator"]:
        return "–"
    return f"{value['numerator']}/{value['denominator']} ({value['rate'] * 100:.0f}%)"


def fmt_ms(value):
    return "–" if value is None else f"{value:,.1f}" if value >= 10 else f"{value:.3f}"


def provider_note(llm):
    """A note for runs on a free real model other than Claude (Thai first): whose numbers these are."""
    if llm["provider"] == "local":
        return ["> **หมายเหตุ:** รอบนี้ใช้โมเดลเปิด (open-weight) ที่รันเองบนเครื่องทดสอบของ GitHub รุ่น `" + llm["model"] + "` "
                "(ตัวเลขหลังเครื่องหมาย : คือลายนิ้วมือของไฟล์โมเดล) ข้อความของเคสไม่ได้ส่งไปบริษัท AI ใด "
                "ผลนี้เป็นของไฟล์โมเดลนี้กับการตั้งค่าในไฟล์ workflow เท่านั้น ไม่ใช่ของ Typhoon รุ่น 30B ที่เรียกผ่าน API และไม่ใช่ของ Claude "
                "เครื่องทดสอบคิดด้วย CPU อย่างเดียว เวลาตอบจึงช้ากว่าบริการออนไลน์มาก "
                "ถ้าช่อง \"AI ใช้งานไม่ได้\" สูงผิดปกติ ให้ดูหัวข้อ \"ตรวจการเชื่อมต่อ AI\" ด้านบน  ",
                "> *Local open-weight model on the GitHub runner (ADR-026): these numbers belong to this model file and "
                "the server settings in the workflow, not to Typhoon's hosted 30B model and not to Claude. Nothing was "
                "sent to an AI company. CPU only, so latency is far higher than a hosted service.*", ""]
    if llm["provider"] != "typhoon":
        return []
    return ["> **หมายเหตุ:** รอบนี้ใช้ AI จริง Typhoon ของ SCB 10X (ใช้ฟรี ช่วงทดลอง) รุ่น `" + llm["model"] + "` "
            "ผลนี้เป็นของรุ่นนี้ ไม่ใช่ของ Claude บริการนี้เก็บข้อมูลการใช้งานไปปรับปรุงโมเดล ซึ่งรับได้เพราะทุกเคสเป็นข้อมูลสมมุติ "
            "ถ้าช่อง \"AI ใช้งานไม่ได้\" สูงผิดปกติ ให้ดูหัวข้อ \"ตรวจการเชื่อมต่อ AI\" ด้านบน  ",
            "> *Typhoon (free research API): these numbers belong to this model, not to Claude. The service collects "
            "usage data to improve its models; acceptable only because every case is synthetic.*", ""]


def reason_line(rows, status_key, reason_key):
    """Why the AI did not answer, counted by reason (Thai first); empty when every call answered."""
    counts = {}
    for row in rows:
        if row[status_key] in ("unavailable", "failed"):
            key = f"{row[status_key]}: {row[reason_key] or 'unknown'}"
            counts[key] = counts.get(key, 0) + 1
    if not counts:
        return []
    listed = ", ".join(f"`{key}` {count}" for key, count in sorted(counts.items()))
    return [f"เหตุที่ AI ไม่ได้ตอบ (why the AI gave no answer): {listed}", ""]


def category_scores(rows, column, categories, *, expected="expected"):
    """Precision, recall and F1 per category, and their macro average, for one predictor (roadmap 5.6).

    ``column`` names the prediction in each row; a missing prediction (``None``, an AI that did not answer)
    counts as a miss for the expected category and as no prediction for any other. Every value keeps its
    counts. A category that never occurs and is never predicted is left out of the macro average.
    """
    per_category, f1s = {}, []
    for category in categories:
        true_positive = sum(r[column] == category and r[expected] == category for r in rows)
        predicted = sum(r[column] == category for r in rows)
        support = sum(r[expected] == category for r in rows)
        precision = true_positive / predicted if predicted else None
        recall = true_positive / support if support else None
        if precision is None and recall is None:
            f1 = None
        elif not precision or not recall:
            f1 = 0.0
        else:
            f1 = 2 * precision * recall / (precision + recall)
        per_category[category] = {"support": support, "predicted": predicted, "correct": true_positive,
                                  "precision": None if precision is None else round(precision, 4),
                                  "recall": None if recall is None else round(recall, 4),
                                  "f1": None if f1 is None else round(f1, 4)}
        if f1 is not None:
            f1s.append(f1)
    return {"per_category": per_category,
            "macro_f1": round(sum(f1s) / len(f1s), 4) if f1s else None,
            "categories_in_macro": len(f1s)}


def git_sha():
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5,
                                cwd=Path(__file__).resolve().parent)
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def to_json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def brief(value):
    if isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value):
        value = value[:12] + "…"  # a SHA-256: the first 12 characters tell two versions apart
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= 80 else text[:77] + "..."


def baseline_text(baseline, head_keys, answer_fields):
    """Stable text, one case per line, so a pull request's diff shows exactly which cases changed."""
    lines = ["{"]
    for key in head_keys:
        lines.append(f"  {json.dumps(key)}: {json.dumps(baseline[key], ensure_ascii=False, sort_keys=True)},")
    lines.append('  "cases": [')
    # case_id first, then the answer fields in a fixed order (not sorted), so each line reads left to right.
    rows = [json.dumps({"case_id": case["case_id"], **{field: case[field] for field in answer_fields}},
                       ensure_ascii=False) for case in baseline["cases"]]
    lines += [f"    {row}," for row in rows[:-1]] + [f"    {row}" for row in rows[-1:]]
    lines += ["  ]", "}"]
    return "\n".join(lines) + "\n"


def check_baseline(document, schema, head_keys, answer_fields):
    """A baseline file's shape; raises ``ValueError`` when it is malformed or repeats a case."""
    if not isinstance(document, dict) or document.get("schema") != schema:
        raise ValueError("Compare with a scorecard report or a baseline file")
    cases = document.get("cases")
    if (set(document) != {*head_keys, "cases"} or not isinstance(cases, list)
            or any(not isinstance(c, dict) or set(c) != {"case_id", *answer_fields} for c in cases)
            or len({c["case_id"] for c in cases}) != len(cases)):
        raise ValueError("The baseline file is malformed or repeats a case")
    return document


def answer_changes(reference, candidate, identity, answer_fields):
    """Every difference between two baselines, one short English line each; empty when nothing changed.
    ``identity`` lists ``(key, label)`` pairs for what produced the answers."""
    changes = []
    for key, label in identity:  # one line per differing part
        old, new = reference[key], candidate[key]
        changes += [f"{label} {part}: {brief(old.get(part))} -> {brief(new.get(part))}"
                    for part in sorted(set(old) | set(new)) if old.get(part) != new.get(part)]
    before = {case["case_id"]: case for case in reference["cases"]}
    after = {case["case_id"]: case for case in candidate["cases"]}
    changes += [f"{case_id}: in the baseline but not in this run" for case_id in before if case_id not in after]
    changes += [f"{case_id}: new in this run, not in the baseline" for case_id in after if case_id not in before]
    for case_id, old in before.items():
        new = after.get(case_id)
        if new is not None:
            changes += [f"{case_id}: {field} {brief(old[field])} -> {brief(new[field])}"
                        for field in answer_fields if old[field] != new[field]]
    return changes


def gate_markdown(changes, compared_with, cases, *, module, live_run):
    """The gate's verdict for the run page (Thai first), with how to proceed when it fails."""
    if not changes:
        return (f"### ด่านตรวจผลรายเคส (eval gate): ผ่าน\n\nทั้ง {cases} เคสตอบเหมือนใน `{compared_with}` ทุกช่อง "
                f"(Every case answered exactly as in the baseline.)\n")
    lines = [f"### ด่านตรวจผลรายเคส (eval gate): ไม่ผ่าน ({len(changes)} จุดต่างจากเดิม)", "",
             f"เทียบกับ `{compared_with}` (Per-case answers differ from the baseline.)", ""]
    lines += [f"- `{line}`" for line in changes[:MAX_LISTED_CHANGES]]
    if len(changes) > MAX_LISTED_CHANGES:
        lines.append(f"- … และอีก {len(changes) - MAX_LISTED_CHANGES} จุด")
    lines += ["", "- **ถ้าไม่ได้ตั้งใจ:** แก้โค้ดจนผลกลับมาเหมือนเดิม",
              f"- **ถ้าตั้งใจเปลี่ยน:** อัปเดต baseline ใน PR เดียวกัน "
              f"(`python -m {module} --write-baseline {compared_with}`) และเขียนเหตุผลไว้ในคำอธิบาย PR "
              f"ถ้าเปลี่ยน prompt หรือรุ่น AI ให้แนบผลรันกับ AI จริงด้วย (Actions → {live_run})", ""]
    return "\n".join(lines)
