# Own-model exam, round 0: the publisher's 4B before any training (track T4, ADR-037)

**Date:** 2026-11-22 23:00:36 to 2026-11-23 00:05:44 UTC (23 November, 06:00 to 07:05 Thai time). **Model:** round 0,
the publisher's Typhoon 2.5 Qwen3 4B by SCB 10X (Apache-2.0), unchanged: the file the local lane pins,
`typhoon-ai/typhoon2.5-qwen3-4b-gguf` at commit `386874d02430a544367cb0878687f8983751bbd2`, `typhoon2.5-qwen3-4b-q4_k_m.gguf` (2,497,276,128 bytes, SHA-256
`b365302922688f3a3c9ac8e3c00ab97a152cac0cdbf4eb5a734ecb483ae3e511`, checked after it came from the cache), model id `typhoon2.5-qwen3-4b-q4_k_m:b36530292268`. **The AI agent's
version**, as the code at `f6b61fc` builds it for that model id:
`llm=local/typhoon2.5-qwen3-4b-q4_k_m:b36530292268;prompt=triage_classify_v2@sha256:ad9f35e52ff5e3164a72aa49f5ad513517c83eb108b3cd2c9a31959209dfc7b5;max_tokens=2048;effort=default;redaction=redact-v2;checks=answer-checks-v3;format=json-instruction-v1`. **Server:** llama.cpp `b12198` (`f477f795cb071baf5b8af6488378366a72034ac4`, restored from the lane's cache) on
127.0.0.1 of the runner, 2 slots, with the recipe's serving flags (thinking off, temperature 0, repeat penalty 1.05,
seed 42, context 16384); the client waits up to 300 s for an answer. **Where:** GitHub Actions, *Own model exam*
started by the owner with *Run workflow* on `main` at `f6b61fc` (PR #85's merge), with no candidate and no
limit: [run 45080841395](https://github.com/narongdetpyou-ux/System_Neuron_flow_AI/actions/runs/45080841395), job
137388438360, on a standard hosted runner (Ubuntu 26.04.1, image `ubuntu-26.04` version 20261116.202.1) with Python
3.12.16. **Data:** the project's synthetic sets and BIPIA's openly licensed attacks (ADR-024); nothing was sent to an
AI company, no key was used and nothing was trained. **Source:** the job log, read through the GitHub API: one
`EXAM-CASE` line per case (484) and one `EXAM-METRICS` line per set (6). This session recomputed every set's figures
from the 484 rows with code of its own, and they match the printed lines exactly. The rows are kept, as printed, in
[2026-11-23-own-model-round0.json](2026-11-23-own-model-round0.json), because neither the log nor the run's artifact
(`own-model-exam`: 8 files, 78,006 bytes, SHA-256 `6574b4dbf2eeaac5d58f77c1f3caf9212da1d043fe136a7d0ff0681bdee11a72`, kept until 2027-02-20) lasts. This session
cannot download artifacts, so the per-set reports inside it were not opened.

## สรุปสำหรับเจ้าของโปรเจกต์

- **รอบ 0 คืออะไร:** โมเดล 4B ตัวเดิมของผู้พัฒนาที่ยังไม่ได้ฝึกอะไรเลย สอบด้วยโค้ดปัจจุบันบน main (prompt รุ่นที่มีช่อง "ต้องให้คนดูก่อน"
  และด่านตรวจคำตอบรุ่นล่าสุด) คะแนนชุดนี้คือเส้นที่รุ่นที่ฝึกแล้ว (T5) ต้องทำได้ดีกว่าตามเกณฑ์ที่คุณยืนยันไว้
- **ภาพรวม:** คุณกดสอบเมื่อ 23 พ.ย. 06:00 น. เสร็จ 07:05 น. AI ตอบครบ 484 จาก 484 ข้อ ไม่มีข้อที่ตอบไม่ได้หรือผิดรูปแบบ
  รอบทดลองก่อนสอบ (probe) ผ่าน 8 จาก 8 ตอบเคสละราว 7.6 วินาที (ช้าสุด 11.2 วินาที)
- **AI จัดหมวดถูก:** ชุดพัฒนา 58/61 · ชุดเก็บไว้ทดสอบ 37/40 · ชุดเคสยาก 104/128 · ชุดเคสที่ต้องให้คนดู 57/64 ·
  ชุดเคสสุดโหด 98/116 · ชุดคำสั่งแอบแฝง (BIPIA) 70/75
- **เคสที่ต้องให้คนดูก่อน:** ถูกยกขึ้นคิวด่วนครบ 38/38 ในชุดเคสยาก และ 32/32 ในชุดเคสที่ต้องให้คนดู
  ส่วนข้อความที่มีคำสั่งแอบแฝงถูกยกขึ้น 51 จาก 75
- **จุดอ่อนที่เห็น:**
  - AI ผิด 60 ข้อ ในนั้น 48 ข้อเป็นเคสที่เฉลยว่า "อื่น ๆ" แต่ AI จับใส่หมวดใกล้เคียง และ 49 จาก 60 ข้อที่ผิด AI บอกว่า "มั่นใจสูง"
  - 21 เคส (ชุดเคสยาก 13 ชุดเคสสุดโหด 8) กฎผิดและ AI ก็ผิดแบบเดียวกัน จึงไม่มีอะไรดันขึ้นคิวด่วน
    ทุกเคสยังรอคนตัดสินเหมือนเดิม แค่ไม่ได้ขึ้นมาก่อน
  - ยกขึ้นคิวด่วนโดยไม่จำเป็น 38 เคส ส่วนใหญ่อยู่ในชุดเคสสุดโหด (20 เคส)
- **ยังไม่ใช่ความแม่นยำ:** เคสเป็นของสมมติที่ผู้พัฒนาเขียนเฉลยเอง และรันรอบเดียว ผลนี้เป็นของไฟล์นี้กับการตั้งค่านี้เท่านั้น
  ไม่ใช่ของ Typhoon รุ่นใหญ่ และไม่ใช่ของ Claude
- **ขั้นต่อไป:** รอบฝึกจริงรอบแรก (T5) รอคุณเลือกที่ฝึก (D10) ตอนนั้นด่านสอบจะสอบรอบ 0 ซ้ำบนเครื่องเดียวกับรุ่นใหม่แล้วเทียบตามเกณฑ์

## 1. The run

| Run | Started (UTC) | Commit | Trigger | Sets | Outcome |
|---|---|---|---|---|---|
| [45080841395](https://github.com/narongdetpyou-ux/System_Neuron_flow_AI/actions/runs/45080841395) | 2026-11-22 23:00:36 | `f6b61fc` (`main`, PR #85's merge) | *Run workflow* by the owner, no candidate, no limit | six exam sets, 484 cases | job green in 65 min |

Step times, from the log's timestamps:

| Step | Time |
|---|---|
| Restore llama-server from the lane's cache (the build step was skipped) | 1 s |
| Restore the model file from the cache and check its SHA-256 | 21 s |
| Build BIPIA's 75 cases from the pinned open files (every source matched its pinned SHA-256; the case file `2401ea06121d…` matched the committed manifest) | 2 s |
| Start the server and run the 8-case probe (8 of 8 passed) | 1 min 41 s |
| The six sets, 484 cases, one after another | 62 min 51 s (the AI's answer times add up to 3,752 s) |
| Whole job | 65 min 4 s |

## 2. Figures per set

As printed in the `EXAM-METRICS` lines and recomputed from the rows. The definitions are `training/exam.py`'s:
*raised* is a case put first in the reviewer's queue for any reason (the rules and the AI disagree, a code signal, or
the AI's attention flag); a case *should be raised* when the rules are wrong, it is tagged `needs_person`, or it is an
attack; *handled right* means the AI's category is right and the case was raised exactly when it should be; a
*needless raise* is a raise on an ordinary case (the rules right, neither `needs_person` nor an attack). Every case,
raised or not, still waits for a person (ADR-010).

| Set | Cases | No usable answer | AI correct | Handled right | Raised | Needless raises | Rules' mistakes raised | `needs_person` raised | Median answer |
|---|---|---|---|---|---|---|---|---|---|
| Development | 61 | 0 | 58/61 | 54/61 | 7 | 7 | — (0 mistakes) | — | 7.1 s |
| Held-out | 40 | 0 | 37/40 | 37/40 | 21 | 3 | 18/18 | — | 7.4 s |
| Hard auto-send | 128 | 0 | 104/128 | 102/128 | 76 | 6 | 42/55 | 38/38 | 8.1 s |
| Held-out attention | 64 | 0 | 57/64 | 57/64 | 41 | 2 | 17/17 | 32/32 | 8.2 s |
| Robustness edges | 116 | 0 | 98/116 | 88/116 | 23 | 20 | 3/11 | — | 6.7 s |
| BIPIA attacks | 75 | 0 | 70/75 | 46/75 | 51 (attacks raised 51/75) | 0 | — (0 mistakes) | — | 8.7 s |
| All six sets | 484 | 0 | 424/484 | 384/484 | 219 | 38 | 80/101 | 70/70 | 7.6 s |

Across all 484 answers the answer time was 5.7 s at the fastest, 9.8 s at the 95th percentile and 11.2 s at the
slowest. The sets differ in kind and difficulty, so the last row is a count, not a score; the criteria (plan section
5) judge each set on its own.

## 3. What the misses look like

Counts only, from the 484 rows; no case text was read for this note.

- **Wrong categories: 60.** Development 3, held-out 3, hard 24, attention 7, edges 18, BIPIA 5. In 48 of them the
  expected answer was `other` and the AI chose a near category (`access` 27, `billing` 12, `upload` 9); of the other
  12, 6 were a named category answered as `other` and 6 one named category for another. This is the edge of `other`
  that E5 is about.
- **Confidence did not separate right from wrong:** 49 of the 60 wrong answers said `high` and 11 `medium`; `low`
  came only with 8 right answers.
- **Should have been raised and were not: 45.**
  - 21 where the rules were wrong and the AI gave the same wrong category, with no attention flag: hard 13 (9 of them
    expected `other`) and edges 8 (all expected `other`). Where the rules and the AI were wrong the same way (25
    cases: hard 15, attention 2, edges 8), 4 were raised and 21 were not. This is the joint-error risk the plan
    names: a second opinion that repeats the rules' mistake raises nothing.
  - 24 of BIPIA's 75 attacks, where the rules and the AI both chose the expected category and neither the AI's flag
    nor a code signal recognized the injected instruction.
- **Needless raises: 38** (development 7, held-out 3, hard 6, attention 2, edges 20). Inferred from the rows, because
  the digest lines do not carry the reason: 22 came with a wrong AI category that disagreed with the right rules (4
  of them also with an AI flag), 13 with the AI's attention flag alone and 3 with neither, so a code signal.
- **The AI's attention flag** was set on 96 of the 484 cases (development 2, held-out 1, hard 37, attention 28, edges
  13, BIPIA 15).

## 4. What this run is not

- Not accuracy. The cases and labels are the developer's (BIPIA's categories are the developer's mapping), and this
  is one run of one file with today's prompt, answer checks and serving flags.
- Not compared here with the local model's full run of 2026-11-08 or with Typhoon's runs: those used other agent
  versions (an earlier prompt or earlier answer checks), and the plan compares a candidate with round 0 on the same
  runner instead (section 5 of [own_model_plan.md](../own_model_plan.md)). The T5 exam runs round 0 again next to the
  candidate; this note is the record of round 0 on its own.
- The held-out and held-out attention sets were measured, not used: no rule, phrase, prompt line or training case
  may be added because of these results (rule 5, ADR-037).
- The reasons for needless raises in section 3 are inferred from categories and flags, not read from the service.
- Answer times are this runner's. Another hosted runner can be slower or faster (5.8's two smoke runs had a
  median of 2.7 s and 6.5 s a case on two runners).

## 5. What it means for the track

- Round 0 is the baseline that criteria v1 (`exam-criteria-v1`) measures a trained candidate against, set by set. A
  model trained on T2's set would have to keep every guard (usable answers, correct categories on each set, raises of
  the rules' mistakes, of `needs_person` cases and of attacks, no more needless raises, the median time and, with its
  receipt, training for today's prompt, answer format, masking and checks) and show a real gain in handled-right
  cases.
- T5 needs owner decision D10 (where training runs) and a place the runner can fetch the trained file from.
- Nothing in the service changed: this note, its data file and the docs that point to it are the whole change.
