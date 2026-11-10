# Skill handoff: first runs of the exchange (ADR-030)

**Date:** 2026-11-11. **Where:** a Claude Code cloud session (Python 3.10, 3.12 and 3.13), before the pull request's
CI runs. **What:** roadmap H1–H3 and H5's page part ([skill_handoff.md](../skill_handoff.md)): an approval of a
`case_triage.v2` case hands on to `case_triage.v2.apply` through the exchange. **Data:** the three existing
synthetic triage sets and a few synthetic cases; the offline mock AI. **Not in this note:** Render (not merged or
deployed), a live model (the exchange and its translators use no AI), and the trace link (not built).

## สรุปสำหรับเจ้าของโปรเจกต์

- **ทดสอบกับชุดเคสเดิมทั้ง 3 ชุด 217 เคส:** ทุกเคสวิ่งครบสายจริง (รับเข้าคิว → ตัวรันงาน → คนตัดสินแบบจำลองการกด →
  ตัวกลางกับล่าม → งานบันทึกผล) ผ่านทุกข้อ 0 ปัญหา ใช้เวลา 16 วินาที
  - อนุมัติ 174 เคส (ตามข้อเสนอ 116 เปลี่ยนหมวด 58): ส่งต่อสำเร็จ 174 งานบันทึกผลเสร็จ 174 ทุกงานบันทึกหมวด คิว และรหัสการตัดสินตรง
  - ไม่อนุมัติ 43 เคส: ไม่ส่งต่อเลย
  - กดซ้ำทุกเคส: ไม่เกิดงานซ้ำ
  - ข้อความเคสไม่อยู่ในข้อมูลที่ส่งต่อและไม่อยู่ในบันทึกเหตุการณ์
- **ชุดทดสอบเดิมทั้งหมดได้ผลเหมือนเดิม:** ข้อสอบคัดแยกเคส ข้อสอบผู้ช่วยแนะนำแหล่งเรียน และด่านความทนทาน (239 จาก 270 ข้อ 0 bug เท่าเดิม)
- **ชุดทดสอบอัตโนมัติ 448 ข้อผ่านทั้งหมด** บน Python 3.10 และ 3.12 (ใหม่ 37 ข้อ)
- **ระบบจริงที่รันด้วยคำสั่งเดียวกับบน Render (นอก Docker):** อนุมัติแล้วส่งต่อ งานบันทึกผลเสร็จพร้อมใบรับ คนข้างนอกเรียกตรง ๆ ไม่ได้ และหลังรีสตาร์ทยังอยู่ครบ
- **ยังไม่ได้ทำ:** ลองบนหน้าเว็บจริงบน Render (ต้องรวมโค้ดก่อน)

## 1. The existing case sets, end to end

`python -m tests.handoff_check` (all three sets, Python 3.13; again on 3.10 with the same result):

| Set | Cases | Approved as proposed | Approved, another category | Rejected | Handoffs started | Apply jobs completed | Rejections without handoff | Problems |
|---|---|---|---|---|---|---|---|---|
| Development | 61 | 33 | 16 | 12 | 49 | 49 | 12 | 0 |
| Held-out | 40 | 21 | 11 | 8 | 32 | 32 | 8 | 0 |
| Edge (robustness) | 116 | 62 | 31 | 23 | 93 | 93 | 23 | 0 |
| **All** | **217** | **116** | **58** | **43** | **174** | **174** | **43** | **0** |

The decision pattern is fixed (every fifth case rejected, every third of the rest approved with another category),
so the run repeats exactly. Every case was admitted (none refused at the door). The mock AI only shapes the
proposals; whether a case was approved is the check's choice, so this measures the exchange and its route, not
triage accuracy.

## 2. Earlier gates, unchanged

| Gate | Command | Result |
|---|---|---|
| All tests | `python3.10 -m unittest discover -s tests`, the same with `python3.12` | 448 pass on both |
| Triage eval gate | `python -m app.eval.triage_shadow_eval --compare-with tests/baselines/shadow_eval_mock.json` | every case answers as in the baseline |
| Study guide eval gate | `python -m app.eval.study_guide_eval --compare-with tests/baselines/study_guide_eval_mock.json` | every request answers as in the baseline |
| Robustness gate | `python -m tests.robustness.bench --compare-with tests/baselines/robustness_v1.json` | every outcome as in the baseline: 239/270 own items pass, 0 bugs, 20 gaps; 0 of 4,680 sweep checks broken |
| Demos | the three earlier demos and `examples.skill_handoff_demo` | all exit 0 |

No baseline was regenerated: no earlier outcome changed.

Two earlier tests were adapted, both because of the new behaviour, not to hide it:
- `tests/test_service_reviews.py`'s helper `waiting_job` claims its own job by id, because an approval now queues a
  follow-up job that `claim_next` would take first;
- its migration tests now expect schema 3 after an upgrade, and use version 4 as the unknown one.

The guard that only the API records decisions inside `app/` caught the first version of the case-set check, which
lived in `app/eval/` and simulated clicks; it was moved to `tests/handoff_check.py`.

## 3. The service as it runs on Render, locally

`python -m app.serve` (API and supervised Runner, the container's command) with a temporary data folder, then
`examples/service_smoke_test.py` against it, stopped and started again, then `--after-restart`: every check passed,
including the new ones (an approval hands on once; the same click again hands on nothing more; the apply job records
the approval with a Core receipt; a forged `case_triage.v2.apply` request gets `400 unknown_workflow_type`; the apply
job and its handoff survive the restart). The *Service container* workflow runs the same script in the built image.

## 4. The page

A headless Chromium walk through the page on that local service: a case was sent, approved on the decision card,
and both jobs were opened. No console errors. The approved case showed "ส่งต่อแล้ว" with the out-translator, the
five facts with their origins ("คนตัดสิน", "คนพิมพ์เข้ามา"), the three facts left out (the AI's opinion, the rules'
suggestion, the case text) and the in-translator; the apply job showed "บันทึกผลเสร็จแล้ว", the approved queue, and
"งานนี้ถูกส่งต่อมาผ่านตัวกลาง" with a button back to the case.

## 5. Limits

- One session, synthetic data, the mock AI. Render has not run it; the owner's test on the live page is after the
  merge and the deploy (on the free plan the deploy empties the queue).
- The traces of the two jobs are not linked yet (H5).
- The check's decisions are scripted, not a person's.
