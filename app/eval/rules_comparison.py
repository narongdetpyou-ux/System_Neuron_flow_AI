"""Compare rules v1 and v2 using the same saved shadow-eval AI answers (E2).

No model is called here. Run the real shadow scorecard once per case set, then
pass its full ``--out`` reports with repeated ``--report`` arguments. The current
rules must still match the measured rules version and each recorded outcome.
The output keeps all case changes and regressions, including AI failures.
"""

import argparse
import hashlib
import inspect
from pathlib import Path

from neuron_flow.model import decode

from app.domains.case_triage.agents import _classification as classify_v1
from app.domains.case_triage.contracts import CATEGORIES
from app.domains.case_triage.rules import classify_case, rule_version

from .common import fmt_rate, rate, to_json

SCHEMA = "neuron-flow-rules-comparison-v1"


def _metrics(rows, column):
    wrong = [r for r in rows if r[column] != r["expected"]]
    answered = [r for r in rows if r["llm_status"] == "ok"]
    elevated = [r for r in answered if r["job_status"] == "SUCCEEDED" and r[column] != r["llm_category"]]
    return {
        "cases": len(rows),
        "jobs_completed": rate(sum(r["job_status"] == "SUCCEEDED" for r in rows), len(rows)),
        "rules_correct": rate(len(rows) - len(wrong), len(rows)),
        "elevated_review": rate(len(elevated), len(rows)),
        "rules_errors_flagged": rate(sum(r in elevated for r in wrong), len(wrong)),
        # An unavailable AI answer is recorded separately, never called an AI mistake.
        "both_wrong": [r["case_id"] for r in answered
                       if r[column] != r["expected"] and r["llm_category"] != r["expected"]],
        "rule_wrong_ai_unavailable": [r["case_id"] for r in wrong if r["llm_status"] != "ok"],
        "llm_answered": rate(len(answered), len(rows)),
        "llm_correct": rate(sum(r["llm_category"] == r["expected"] for r in answered), len(answered)),
        "by_language": {
            language: rate(sum(r[column] == r["expected"] for r in rows if r["language"] == language),
                           sum(r["language"] == language for r in rows))
            for language in ("en", "th") if any(r["language"] == language for r in rows)
        },
    }


def compare_report(report):
    """Replay deterministic rules only, refusing stale or malformed report evidence."""
    if not isinstance(report, dict) or report.get("schema") != "neuron-flow-shadow-eval-v1":
        raise ValueError("A full shadow-eval report is required")
    provenance, cases = report.get("provenance"), report.get("cases")
    if not isinstance(provenance, dict) or not isinstance(cases, list) or not cases:
        raise ValueError("The report has no provenance or cases")
    if provenance.get("rules") != {"version": rule_version()}:
        raise ValueError("The measured rules version differs from the current rules")
    for section, identifier in (("golden", "name"), ("llm", "provider"), ("llm", "model"), ("prompt", "id")):
        part = provenance.get(section)
        if not isinstance(part, dict) or not isinstance(part.get(identifier), str) or not part[identifier]:
            raise ValueError(f"The report is missing {section}.{identifier} provenance")
    if provenance["golden"].get("cases") != len(cases):
        raise ValueError("The report case count differs from its provenance")
    for section in ("golden", "prompt"):
        digest = provenance[section].get("sha256")
        if (not isinstance(digest, str) or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)):
            raise ValueError(f"The report is missing a valid {section} SHA-256")
    seen, rows = set(), []
    for case in cases:
        if (not isinstance(case, dict) or not isinstance(case.get("case_id"), str)
                or case["case_id"] in seen or not isinstance(case.get("summary"), str)
                or case.get("expected") not in CATEGORIES or case.get("language") not in ("en", "th")
                or case.get("job_status") not in ("SUCCEEDED", "FAILED")
                or case.get("llm_status") not in ("ok", "unavailable", "failed")
                or (case["llm_status"] == "ok" and case.get("llm_category") not in CATEGORIES)
                or (case["llm_status"] != "ok" and case.get("llm_category") is not None)):
            raise ValueError("The report has an invalid or duplicate case")
        seen.add(case["case_id"])
        if hashlib.sha256(case["summary"].encode("utf-8")).hexdigest() != case.get("source_sha256"):
            raise ValueError(f"{case['case_id']}: the source text hash differs")
        new = classify_case({"summary": case["summary"]})
        if (case.get("rules_category") != new["category"]
                or case.get("rule_version") != new["rule_version"]):
            raise ValueError(f"{case['case_id']}: the recorded rules output differs from replay")
        old = classify_v1({"summary": case["summary"]})
        rows.append({"case_id": case["case_id"], "language": case["language"],
                     "source_sha256": case["source_sha256"], "expected": case["expected"],
                     "rules_v1": old["category"], "rules_v2": new["category"],
                     "llm_status": case["llm_status"], "llm_category": case["llm_category"],
                     "job_status": case.get("job_status")})
    return {
        "provenance": provenance,
        "rules_v1": {"version": "keywords-v1",
                     "source_sha256": hashlib.sha256(inspect.getsource(classify_v1).encode("utf-8")).hexdigest(),
                     "metrics": _metrics(rows, "rules_v1")},
        "rules_v2": {"version": rule_version(), "metrics": _metrics(rows, "rules_v2")},
        "changed_cases": [r["case_id"] for r in rows if r["rules_v1"] != r["rules_v2"]],
        "regressions": [r["case_id"] for r in rows
                        if r["rules_v1"] == r["expected"] and r["rules_v2"] != r["expected"]],
        "improvements": [r["case_id"] for r in rows
                         if r["rules_v1"] != r["expected"] and r["rules_v2"] == r["expected"]],
        "cases": rows,
    }


def summary_markdown(comparison):
    lines = ["## เปรียบเทียบกฎรุ่น 1 กับรุ่น 2 (E2)", "",
             "ใช้ผลการรัน AI ชุดเดียวกันทั้งสองรุ่น ไม่เรียก AI เพิ่มเพื่อเทียบกฎ "
             "ตัวเลขเป็นผลบนข้อมูลสมมุติที่ผู้พัฒนาให้เฉลย ไม่ใช่ความแม่นยำในการใช้งานจริง", "",
             "| ชุดเคส | กฎ | งานจบ | จัดหมวดถูก | ต้องดูก่อน | ความผิดของกฎที่ถูกยก | ผิดทั้งคู่ | AI ไม่ตอบ |",
             "|---|---|---|---|---|---|---|---|"]
    for result in comparison["sets"]:
        p = result["provenance"]
        for version in ("rules_v1", "rules_v2"):
            m = result[version]["metrics"]
            lines.append(f"| {p['golden']['name']} | {version} | {fmt_rate(m['jobs_completed'])} | "
                         f"{fmt_rate(m['rules_correct'])} | "
                         f"{fmt_rate(m['elevated_review'])} | {fmt_rate(m['rules_errors_flagged'])} | "
                         f"{len(m['both_wrong'])}/{m['llm_answered']['numerator']} | "
                         f"{m['cases'] - m['llm_answered']['numerator']}/{m['cases']} |")
    for result in comparison["sets"]:
        p = result["provenance"]
        lines += ["", f"### {p['golden']['name']}", "",
                  f"AI `{p['llm']['provider']}/{p['llm']['model']}` · "
                  f"กฎ `{result['rules_v2']['version']}` · "
                  f"ชุดเคส `{p['golden']['sha256']}` · commit `{p.get('git_sha') or 'unknown'}`", "",
                  "| ภาษา | กฎรุ่น 1 ถูก | กฎรุ่น 2 ถูก |", "|---|---|---|"]
        for language, value in result["rules_v1"]["metrics"]["by_language"].items():
            lines.append(f"| {language} | {fmt_rate(value)} | "
                         f"{fmt_rate(result['rules_v2']['metrics']['by_language'][language])} |")
        lines += ["", "เคสที่กฎเดิมถูกแต่กฎใหม่ผิด: "
                  + (", ".join(f"`{case_id}`" for case_id in result["regressions"]) or "ไม่มี"), ""]
        lines += [f"- `{r['case_id']}`: {r['rules_v1']} → {r['rules_v2']}; เฉลย {r['expected']}"
                  for r in result["cases"] if r["rules_v1"] != r["rules_v2"]]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", action="append", required=True, help="full saved shadow-eval report; repeatable")
    parser.add_argument("--out", help="comparison JSON output")
    parser.add_argument("--summary", help="append markdown to this file")
    args = parser.parse_args(argv)
    comparison = {"schema": SCHEMA,
                  "sets": [compare_report(decode(Path(path).read_bytes())) for path in args.report]}
    text = summary_markdown(comparison)
    print(text)
    if args.out:
        Path(args.out).write_text(to_json(comparison), encoding="utf-8")
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as stream:
            stream.write(text)
    # Regressions are evidence to review, not an invented acceptance threshold.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
