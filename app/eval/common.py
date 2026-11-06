"""What the scorecards share: rates with their numerator and denominator, and the eval gate's baseline file,
comparison and verdict (roadmap 5.2). Each scorecard says which fields make up a case's answer and which
parts of a run (case set, AI, prompts, library) must match."""

import json
import subprocess
from pathlib import Path

MAX_LISTED_CHANGES = 40


def rate(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "rate": round(numerator / denominator, 4) if denominator else None}


def fmt_rate(value):
    if not value["denominator"]:
        return "–"
    return f"{value['numerator']}/{value['denominator']} ({value['rate'] * 100:.0f}%)"


def fmt_ms(value):
    return "–" if value is None else f"{value:,.1f}" if value >= 10 else f"{value:.3f}"


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
              f"ถ้าเปลี่ยน prompt หรือรุ่น AI ให้แนบผลรัน Claude จริงด้วย (Actions → {live_run})", ""]
    return "\n".join(lines)
