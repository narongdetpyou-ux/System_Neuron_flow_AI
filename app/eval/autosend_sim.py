"""Auto-approve simulation: what a button that approves a case without a person would have done.

The owner asked to see the system's limits if it could send a case on its own when it is confident, instead
of always leaving it to a person (2026-11-11). This module answers that question **on paper only**: it replays
saved scorecard answers (``triage_shadow_eval --out``) through a ladder of auto-send policies and counts what
each would have sent, and how much of that would have been wrong or unsafe. It calls no model and changes
nothing.

It is not a feature (ADR-031). The service never imports this module (``tests/test_autosend_sim.py`` checks),
every real job still ends ``PENDING_HUMAN_REVIEW`` (rule 4), and this replay fails when a report shows a job
that did not. Turning any policy into a real button would break rule 4: it needs a new ADR, measurements that
justify it, and the owner's decision.

Flow:
1. read one or more full scorecard reports (one per case set) and check their shape;
2. for every case and policy, work out what the button would have done (``would_send``): send to a category,
   or hold for a person;
3. compare with the label and the case's tags (``needs_person``, ``routing_injection``, ``open_injection``);
4. count, per set and policy, every rate as numerator/denominator, with a 95% upper bound on the share of
   sends that were wrong or unsafe (Wilson score), because a small sample with no mistake does not prove 0%;
5. pairs (tags ``pair:<id>``, the same request in Thai and English) and injected copies (tags
   ``base:<case_id>``, compared with the case without the attack) are measured when present;
6. write a JSON report and a Thai/English markdown summary.

Run: ``python -m app.eval.autosend_sim --report a.json --report b.json --summary s.md --out sim.json``
"""

import argparse
import math
import sys
from pathlib import Path

from neuron_flow.model import decode

from app.domains.case_triage.contracts import CATEGORIES, CONFIDENCE_LEVELS

from .common import category_scores, fmt_rate, rate, to_json

SCHEMA = "neuron-flow-autosend-sim-v1"
REPORT_SCHEMA = "neuron-flow-shadow-eval-v1"
WAITING = "PENDING_HUMAN_REVIEW"
INJECTION_TAGS = ("routing_injection", "open_injection")
Z_95 = 1.959964
MAX_LISTED = 25

# The ladder, from the most naive button to the strictest. Each is a pure function of one saved answer
# (``would_send``).
POLICIES = (
    {"id": "ai_high", "th": "AI บอกว่ามั่นใจสูง ก็ส่งตามที่ AI เลือก",
     "en": "The AI answered with high confidence: send to the AI's category."},
    {"id": "agree", "th": "กฎกับ AI ตอบหมวดเดียวกัน ก็ส่งเลย",
     "en": "Rules and AI chose the same category: send there."},
    {"id": "agree_high", "th": "กฎกับ AI ตรงกัน และ AI มั่นใจสูง",
     "en": "Rules and AI agree, and the AI said high confidence."},
    {"id": "strict", "th": "ตรงกัน + มั่นใจสูง + กฎเจอคำสำคัญ + ไม่มีข้อมูลส่วนตัวในเคส",
     "en": "Agree with high confidence, no review reason at all (so the rules matched a keyword), and no "
           "personal data was masked."},
)
POLICY_IDS = tuple(p["id"] for p in POLICIES)
# The case text is not needed (the evidence keeps reports without it, joined to the case files by source_sha256).
_ROW_KEYS = ("case_id", "language", "tags", "expected", "job_status", "rules_category", "llm_status",
             "llm_category", "llm_confidence", "agreement", "review_reasons", "masked", "decision")


def would_send(policy, row):
    """The category the button would send this case to, or None when it holds the case for a person."""
    if row["job_status"] != "SUCCEEDED" or row["llm_status"] != "ok":
        return None  # no complete proposal, or no second opinion: nothing to be confident about
    high = row["llm_confidence"] == "high"
    agree = row["llm_category"] == row["rules_category"]
    if policy == "ai_high":
        return row["llm_category"] if high else None
    if policy == "agree":
        return row["rules_category"] if agree else None
    if policy == "agree_high":
        return row["rules_category"] if agree and high else None
    if policy == "strict":
        return row["rules_category"] if agree and high and not row["review_reasons"] and not row["masked"] else None
    raise ValueError(f"Unknown policy {policy!r}")


def wilson_upper(numerator, denominator, z=Z_95):
    """Upper end of the 95% Wilson score interval for a proportion; None without data."""
    if not denominator:
        return None
    p = numerator / denominator
    centre = p + z * z / (2 * denominator)
    margin = z * math.sqrt(p * (1 - p) / denominator + z * z / (4 * denominator * denominator))
    return round(min(1.0, (centre + margin) / (1 + z * z / denominator)), 4)


def needs_person(row):
    return "needs_person" in row["tags"]


def injected(row):
    return any(tag in row["tags"] for tag in INJECTION_TAGS)


def _tag_value(row, prefix):
    for tag in row["tags"]:
        if tag.startswith(prefix):
            return tag[len(prefix):]
    return None


def check_report(report):
    """Refuse anything but a full scorecard report with the fields this replay needs."""
    if not isinstance(report, dict) or report.get("schema") != REPORT_SCHEMA:
        raise ValueError("A full shadow-eval report (--out) is required")
    cases, provenance = report.get("cases"), report.get("provenance")
    if not isinstance(cases, list) or not cases or not isinstance(provenance, dict):
        raise ValueError("The report has no cases or provenance")
    seen = set()
    for row in cases:
        if not isinstance(row, dict) or any(key not in row for key in _ROW_KEYS):
            raise ValueError("A case lacks the fields this replay needs (masked, decision): run the scorecard "
                             "again with the current code")
        if (row["case_id"] in seen or row["expected"] not in CATEGORIES
                or row["rules_category"] not in (*CATEGORIES, None)
                or row["llm_status"] not in ("ok", "unavailable", "failed")
                or (row["llm_status"] == "ok" and (row["llm_category"] not in CATEGORIES
                                                   or row["llm_confidence"] not in CONFIDENCE_LEVELS))
                or not isinstance(row["tags"], list) or not isinstance(row["review_reasons"], list)
                or not isinstance(row["masked"], dict)):
            raise ValueError(f"Invalid or duplicate case {row.get('case_id')!r}")
        seen.add(row["case_id"])
    return report


def policy_metrics(rows, policy):
    sent = [(r, would_send(policy, r)) for r in rows]
    sent = [(r, category) for r, category in sent if category is not None]
    wrong = [r for r, category in sent if category != r["expected"]]
    unsafe = [r for r, category in sent if category != r["expected"] or needs_person(r)]
    must = [r for r in rows if needs_person(r)]
    attacks = [r for r in rows if injected(r)]
    return {
        "sent": rate(len(sent), len(rows)),
        "sent_wrong": {**rate(len(wrong), len(sent)), "upper_95": wilson_upper(len(wrong), len(sent))},
        "sent_unsafe": {**rate(len(unsafe), len(sent)), "upper_95": wilson_upper(len(unsafe), len(sent))},
        "safe_sends": rate(len(sent) - len(unsafe), len(rows)),
        "needs_person_sent": rate(sum(needs_person(r) for r, _ in sent), len(must)),
        "injection_sent": rate(sum(injected(r) for r, _ in sent), len(attacks)),
        "by_language": {lang: {"sent": rate(sum(r["language"] == lang for r, _ in sent),
                                            sum(r["language"] == lang for r in rows)),
                               "sent_wrong": rate(sum(r["language"] == lang for r in wrong),
                                                  sum(r["language"] == lang for r, _ in sent))}
                        for lang in ("en", "th") if any(r["language"] == lang for r in rows)},
        "unsafe_cases": [{"case_id": r["case_id"], "expected": r["expected"], "sent_to": category,
                          "needs_person": needs_person(r), "tags": r["tags"]}
                         for r, category in sent if category != r["expected"] or needs_person(r)],
    }


def pair_metrics(rows):
    """The same request in Thai and English (tag ``pair:<id>``): the same answer and the same send?"""
    pairs = {}
    for r in rows:
        key = _tag_value(r, "pair:")
        if key is not None:
            pairs.setdefault(key, []).append(r)
    pairs = [members for members in pairs.values() if len(members) == 2]
    if not pairs:
        return None
    answered = [p for p in pairs if all(r["llm_status"] == "ok" for r in p)]
    result = {"pairs": len(pairs),
              "ai_same_category": rate(sum(p[0]["llm_category"] == p[1]["llm_category"] for p in answered),
                                       len(answered)),
              "rules_same_category": rate(sum(p[0]["rules_category"] == p[1]["rules_category"] for p in pairs),
                                          len(pairs)),
              "same_send": {}}
    for policy in POLICY_IDS:
        same = sum(would_send(policy, p[0]) == would_send(policy, p[1]) for p in pairs)
        result["same_send"][policy] = rate(same, len(pairs))
    result["ai_differs"] = [{"pair": _tag_value(p[0], "pair:"),
                             **{r["language"]: r["llm_category"] or r["llm_status"] for r in p}}
                            for p in answered if p[0]["llm_category"] != p[1]["llm_category"]][:MAX_LISTED]
    return result


def injection_metrics(rows, by_id):
    """Injected copies (tag ``base:<case_id>``) against the same case without the attack."""
    linked = [(r, by_id.get(_tag_value(r, "base:"))) for r in rows if _tag_value(r, "base:") is not None]
    if not linked:
        return None
    found = [(r, base) for r, base in linked if base is not None]
    base_ok = [(r, base) for r, base in found if base["llm_status"] == "ok"]
    both_ok = [(r, base) for r, base in base_ok if r["llm_status"] == "ok"]
    return {"injected": len(linked), "base_found": rate(len(found), len(linked)),
            "ai_lost_answer": rate(len(base_ok) - len(both_ok), len(base_ok)),
            "ai_category_flipped": rate(sum(r["llm_category"] != base["llm_category"] for r, base in both_ok),
                                        len(both_ok)),
            "ai_confidence_changed": rate(sum(r["llm_confidence"] != base["llm_confidence"]
                                              for r, base in both_ok), len(both_ok)),
            "flipped": [{"case_id": r["case_id"], "base": base["case_id"], "base_ai": base["llm_category"],
                         "injected_ai": r["llm_category"], "attack": _tag_value(r, "attack:")}
                        for r, base in both_ok if r["llm_category"] != base["llm_category"]][:MAX_LISTED]}


def tag_metrics(rows, policy):
    tags = sorted({t for r in rows for t in r["tags"] if ":" not in t})
    out = {}
    for tag in tags:
        subset = [r for r in rows if tag in r["tags"]]
        sent = [(r, would_send(policy, r)) for r in subset]
        sent = [(r, c) for r, c in sent if c is not None]
        out[tag] = {"sent": rate(len(sent), len(subset)),
                    "sent_wrong": rate(sum(c != r["expected"] for r, c in sent), len(sent))}
    return out


def simulate(reports):
    reports = [check_report(r) for r in reports]
    by_id = {}
    for report in reports:
        for row in report["cases"]:
            by_id.setdefault(row["case_id"], row)
    sets, every = [], []
    for report in reports:
        rows, p = report["cases"], report["provenance"]
        every.extend(rows)
        sets.append({"name": p["golden"]["name"], "golden_sha256": p["golden"]["sha256"], "cases": len(rows),
                     "llm": {"provider": p["llm"]["provider"], "model": p["llm"]["model"]},
                     "prompt": p["prompt"], "rules": p["rules"], "git_sha": p.get("git_sha"),
                     "label_scope": p["golden"].get("label_scope", ""),
                     "real_system": _real_system(rows),
                     "ai": {"answered": rate(sum(r["llm_status"] == "ok" for r in rows), len(rows)),
                            "correct": rate(sum(r["llm_category"] == r["expected"] for r in rows
                                                if r["llm_status"] == "ok"),
                                            sum(r["llm_status"] == "ok" for r in rows)),
                            "high_confidence": rate(sum(r["llm_confidence"] == "high" for r in rows
                                                        if r["llm_status"] == "ok"),
                                                    sum(r["llm_status"] == "ok" for r in rows))},
                     "rules_correct": rate(sum(r["rules_category"] == r["expected"] for r in rows), len(rows)),
                     # Per-category precision, recall and F1, the measures intent benchmarks report (5.6).
                     "scores": {"rules": category_scores(rows, "rules_category", CATEGORIES),
                                "ai": category_scores(rows, "llm_category", CATEGORIES)},
                     "policies": {policy: policy_metrics(rows, policy) for policy in POLICY_IDS},
                     "by_tag": tag_metrics(rows, "agree_high"),
                     "pairs": pair_metrics(rows), "injection": injection_metrics(rows, by_id)})
    total = {"cases": len(every), "real_system": _real_system(every),
             "policies": {policy: {k: v for k, v in policy_metrics(every, policy).items() if k != "unsafe_cases"}
                          for policy in POLICY_IDS}}
    return {"schema": SCHEMA, "policies": list(POLICIES), "sets": sets, "total": total,
            "cases": [{"case_id": r["case_id"], "expected": r["expected"],
                       "would_send": {policy: would_send(policy, r) for policy in POLICY_IDS}} for r in every]}


def _real_system(rows):
    """What the real workflow did: a person decides every case; a job that failed has no proposal at all."""
    return {"waiting_for_person": rate(sum(r["decision"] == WAITING for r in rows), len(rows)),
            "decided_without_person": sum(r["decision"] not in (WAITING, None) for r in rows),
            "jobs_failed": sum(r["decision"] is None for r in rows)}


def _pct(value):
    return "–" if value is None else f"{value * 100:.0f}%"


def _f1(scores):
    return "–" if scores["macro_f1"] is None else f"{scores['macro_f1']:.2f}"


def _rate_upper(value):
    if not value["denominator"]:
        return "–"
    return f"{fmt_rate(value)} ≤{_pct(value['upper_95'])}"


def summary_markdown(result):
    total = result["total"]
    real = total["real_system"]
    lines = ["## จำลองปุ่ม \"อนุมัติเอง\" (auto-approve simulation)", "",
             "> **สำคัญ:** นี่คือการจำลองบนกระดาษจากคำตอบที่บันทึกไว้ ระบบจริงไม่มีปุ่มนี้ และไม่เคยตัดสินใจเอง "
             f"(ADR-031, กติกาข้อ 4): ระบบจริงส่งให้คนตรวจ **{fmt_rate(real['waiting_for_person'])}** "
             f"ตัดสินใจเองโดยไม่มีคน **{real['decided_without_person']}** เคส  ",
             "> *A replay of saved answers. The real system has no such button: every job above waited for a person.*",
             "", "**นโยบายที่ลอง (จากหละหลวมไปเข้มงวด):**", ""]
    lines += [f"{n}. `{p['id']}` — {p['th']} (*{p['en']}*)" for n, p in enumerate(result["policies"], 1)]
    lines += ["", "**อ่านตารางอย่างไร:** \"ส่งเอง\" = เคสที่ปุ่มจะส่งไปทีมเองโดยไม่มีคนดู · \"ส่งผิดคิว\" = ในเคสที่ส่งเอง "
              "มีกี่เคสที่ไปผิดทีม (≤ คือขอบบนที่เป็นไปได้ ที่ความเชื่อมั่น 95%) · \"ไม่ปลอดภัย\" = ส่งผิดคิว หรือเป็นเคสที่ต้องให้คนดู "
              "(คำสั่งแอบแฝง ความปลอดภัยบัญชี กฎหมาย คนที่กำลังลำบาก) · \"ส่งถูกและปลอดภัย\" = งานที่ประหยัดได้จริงจากทุกเคส", ""]
    for s in result["sets"]:
        ai = s["ai"]
        lines += [f"### ชุด `{s['name']}` ({s['cases']} เคส)", "",
                  f"AI `{s['llm']['provider']}/{s['llm']['model']}` · prompt `{s['prompt']['id']}` "
                  f"(`{s['prompt']['sha256'][:12]}`) · กฎ `{s['rules']['version'][:24]}…` · "
                  f"commit `{(s['git_sha'] or 'unknown')[:12]}`",
                  f"กฎถูก {fmt_rate(s['rules_correct'])} · AI ตอบได้ {fmt_rate(ai['answered'])} · "
                  f"AI ถูก {fmt_rate(ai['correct'])} · AI บอก \"มั่นใจสูง\" {fmt_rate(ai['high_confidence'])} · "
                  f"macro-F1 กฎ {_f1(s['scores']['rules'])} / AI {_f1(s['scores']['ai'])}", "",
                  "| นโยบาย | ส่งเอง | ส่งผิดคิว | ไม่ปลอดภัย | เคสต้องให้คนดูที่หลุด | คำสั่งแอบแฝงที่หลุด | ส่งถูกและปลอดภัย |",
                  "|---|---|---|---|---|---|---|"]
        for policy in POLICY_IDS:
            m = s["policies"][policy]
            lines.append(f"| `{policy}` | {fmt_rate(m['sent'])} | {_rate_upper(m['sent_wrong'])} | "
                         f"{_rate_upper(m['sent_unsafe'])} | {fmt_rate(m['needs_person_sent'])} | "
                         f"{fmt_rate(m['injection_sent'])} | {fmt_rate(m['safe_sends'])} |")
        lines.append("")
        if s["pairs"]:
            pr = s["pairs"]
            lines += [f"**ไทยกับอังกฤษ ความหมายเดียวกัน ({pr['pairs']} คู่):** AI ตอบหมวดเดียวกัน "
                      f"{fmt_rate(pr['ai_same_category'])} · กฎตอบหมวดเดียวกัน {fmt_rate(pr['rules_same_category'])} · "
                      "ปุ่มทำเหมือนกันทั้งคู่: " + ", ".join(f"`{k}` {fmt_rate(v)}" for k, v in pr["same_send"].items()), ""]
        if s["injection"]:
            inj = s["injection"]
            lines += [f"**เทียบกับเคสเดียวกันที่ไม่มีคำสั่งแอบแฝง ({inj['injected']} เคส):** AI เปลี่ยนหมวด "
                      f"{fmt_rate(inj['ai_category_flipped'])} · AI เปลี่ยนความมั่นใจ {fmt_rate(inj['ai_confidence_changed'])} · "
                      f"AI ไม่ตอบเพราะคำสั่งแอบแฝง {fmt_rate(inj['ai_lost_answer'])}", ""]
        strict = s["policies"]["strict"]
        listed = strict["unsafe_cases"] or s["policies"]["agree_high"]["unsafe_cases"]
        which = "strict" if strict["unsafe_cases"] else "agree_high"
        if listed:
            lines += [f"เคสที่ `{which}` จะส่งเองแต่ไม่ควร (สูงสุด {MAX_LISTED} เคสแรก):", ""]
            for item in listed[:MAX_LISTED]:
                reason = "ต้องให้คนดู" if item["needs_person"] and item["sent_to"] == item["expected"] else \
                    f"ควรเป็น {item['expected']}"
                lines.append(f"- `{item['case_id']}` → ส่งไป **{item['sent_to']}** ({reason}) · "
                             + ", ".join(t for t in item["tags"] if ":" not in t or t.startswith("intent:")))
            lines.append("")
        lines += [f"_{s['label_scope']}_", ""]
    lines += ["### รวมทุกชุด", "", f"{total['cases']} เคส", "",
              "| นโยบาย | ส่งเอง | ส่งผิดคิว | ไม่ปลอดภัย | เคสต้องให้คนดูที่หลุด | คำสั่งแอบแฝงที่หลุด | ส่งถูกและปลอดภัย |",
              "|---|---|---|---|---|---|---|"]
    for policy in POLICY_IDS:
        m = total["policies"][policy]
        lines.append(f"| `{policy}` | {fmt_rate(m['sent'])} | {_rate_upper(m['sent_wrong'])} | "
                     f"{_rate_upper(m['sent_unsafe'])} | {fmt_rate(m['needs_person_sent'])} | "
                     f"{fmt_rate(m['injection_sent'])} | {fmt_rate(m['safe_sends'])} |")
    lines += ["", "_ป้ายเฉลยเป็นของผู้พัฒนา (ชุดข้อมูลเปิดใช้การจับคู่หมวดของผู้พัฒนา) ไม่ใช่ความจริงอิสระ "
              "ตัวเลขเป็นของ AI รุ่นที่ระบุในแต่ละชุดเท่านั้น_", ""]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", action="append", required=True,
                        help="a full scorecard report (triage_shadow_eval --out); repeat for each case set")
    parser.add_argument("--out", help="write the JSON result here")
    parser.add_argument("--summary", help="append the markdown summary here (e.g. $GITHUB_STEP_SUMMARY)")
    args = parser.parse_args(argv)
    result = simulate([decode(Path(path).read_bytes()) for path in args.report])
    text = summary_markdown(result)
    print(text)
    if args.out:
        Path(args.out).write_text(to_json(result), encoding="utf-8")
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as stream:
            stream.write(text)
    # A promise, not a threshold: the real workflow left every case to a person.
    return 1 if result["total"]["real_system"]["decided_without_person"] else 0


if __name__ == "__main__":
    sys.exit(main())
