# Effectiveness baseline: the hard cases with Typhoon, the keyword list, and the first case after a start

**Date:** 2026-11-10 (the runs were made on 2026-11-09 between 23:50 and 23:55 UTC, which is 06:50 on
2026-11-10 in Bangkok). **Where:** a Claude Code cloud session on `main` @ `95d3560`; Python 3.13.18 for the
scorecards and 3.12.3 for the import timing. **Model:** `typhoon-v2.5-30b-a3b-instruct` by SCB 10X through its
free research API (ADR-021). The key is a network secret of the cloud environment: its proxy adds it to each
request, so the key never entered the session, a file or a log. **Data:** synthetic and open-dataset text only
(CLINC150 and BANKING77 under ADR-024), because the service collects usage data. **Why:** the owner asked for
a plan to make the system more effective; these measurements are the baseline of
[effectiveness_plan.md](../effectiveness_plan.md).

## สรุปสำหรับเจ้าของโปรเจกต์

- **วัดเคสยาก 116 ข้อกับ AI จริง (Typhoon) เป็นครั้งแรก:** AI จัดหมวดถูก 104 จาก 116 กฎคำสำคัญถูก 48 จาก 116
  เคสภาษาไทย AI ถูก 13 จาก 13 (กฎถูก 3 จาก 13) AI ตอบได้ทุกข้อตั้งแต่ครั้งแรก
- **AI พลาด 12 ข้อ ทุกข้อเป็นแบบเดียวกัน:** เฉลยว่า "อื่น ๆ" แต่ AI จับใส่หมวดที่ใกล้ที่สุด เช่น "โทรศัพท์หาย" ถูกจัดเป็นเรื่องเข้าระบบ
  ทั้ง 12 ข้อเป็นคำขอจากชุดข้อมูลเปิดที่ผู้พัฒนาจับคู่ป้ายเอง จึงยังไม่ใช่ความแม่นยำจริง
- **ระดับความมั่นใจของ AI ใช้เตือนไม่ได้:** AI บอกว่า "มั่นใจสูง" ทั้ง 116 ข้อ รวม 12 ข้อที่ผิดด้วย
- **เคสถูกยกเป็น "ต้องดูก่อน" เกินครึ่ง:** 64 จาก 116 เคส (ชุดปกติ 33 จาก 61) เพราะกฎผิดบ่อย ป้าย "ต้องดูก่อน" จึงแทบไม่ช่วยจัดลำดับ
- **แค่เพิ่มรายการคำสำคัญ กฎก็ดีขึ้นมาก:** รายการคำสำคัญที่ยาวกว่าและมีภาษาไทย (ของ AI จำลอง) ถูก 74 จาก 116
  เทียบกับกฎปัจจุบัน 48 จาก 116 แต่ยังห่างจาก AI จริง (104)
- **เคสแรกหลังระบบตื่นใช้เวลาราว 10 วินาทีทุกครั้งที่วัดได้ (4 จาก 4 ครั้ง)** เคสถัดไปใช้ 0.1–0.4 วินาที
  สาเหตุที่น่าจะใช่: โปรแกรมต้องแปลโค้ดใหม่ทุกครั้งที่เริ่ม เพราะในเครื่องไม่มีไฟล์ที่แปลไว้ล่วงหน้า (bytecode)
  ในเครื่องทดสอบ การเริ่มแบบไม่มีไฟล์ที่แปลไว้ช้ากว่าราว 3.7 เท่า (434 กับ 116 มิลลิวินาที)
- **ระบบที่ออนไลน์ถูกใช้น้อยมาก:** 7 วันที่ผ่านมามี 3 งาน (เคส 2 คำถามเรียน 1) และ Sentry ไม่มีข้อผิดพลาดค้างอยู่
  ปัญหาจึงไม่ใช่ระบบรับงานไม่ทัน

## 1. The 116 edge cases with Typhoon (first live run of this set)

`python -m app.eval.triage_shadow_eval --golden tests/robustness/triage_edge_golden_v1.json --min-interval-s 1`
with `NEURON_FLOW_LLM_PROVIDER=typhoon`, after the connection check (`.github/scripts/llm_probe.py`) answered
with valid JSON and the same served model. Cases `triage_edge_robustness_v1` (SHA-256 `a6127ad36a82…`):
43 synthetic edge items written to break keyword rules, 39 CLINC150 requests and 34 BANKING77 requests.
Prompt `triage_classify_v1` (`5cb3b35cb3bc`). The report was written at 23:54:44 UTC after 179.5 s.

The mock column is the offline keyword simulation on the same file at the same commit
(the same command without the provider variable). It is not a model.

| Measure | Rules (`keywords-v1`) | Mock keyword list | Typhoon (this run) |
|---|---|---|---|
| Jobs completed | 116/116 | 116/116 | 116/116 |
| Correct | 48/116 | 74/116 | **104/116** |
| AI answered | – | 116/116 | 116/116, each on the first attempt |
| Rules and AI agree | – | 90/116 | 52/116 |
| Raised for review first (elevated) | – | 26/116 | 64/116 |
| Rule mistakes raised | – | 26/68 | **60/68** |
| Raises that were needed (rules wrong) | – | 26/26 | 60/64 |
| Wrong for both rules and AI | – | 42 | 8 |
| AI unavailable / failed | – | 0 / 0 | 0 / 0 |
| Tokens in / out | – | (estimated) | 46,191 / 3,443 |
| AI latency p50 / p95 | – | (no model) | 1,324.6 / 2,444.5 ms |

| Split | Cases | Rules correct | Mock list correct | Typhoon correct |
|---|---|---|---|---|
| English | 103 | 45/103 | 63/103 | 91/103 |
| Thai | 13 | 3/13 | 11/13 | 13/13 |
| Synthetic edge items | 43 | 16/43 | 29/43 | 43/43 |
| CLINC150 requests | 39 | 18/39 | 21/39 | 30/39 |
| BANKING77 requests | 34 | 14/34 | 24/34 | 31/34 |
| Label `access` | 35 | 11/35 | – | 35/35 |
| Label `upload` | 8 | 3/8 | – | 8/8 |
| Label `billing` | 44 | 15/44 | – | 44/44 |
| Label `other` | 29 | 19/29 | – | 17/29 |

Typhoon's 12 mistakes. Every one is an open-dataset request that the developer's mapping labels `other`:

| Request | Rules | Typhoon | Text (CLINC150 CC BY 3.0, BANKING77 CC BY 4.0) |
|---|---|---|---|
| `CLINC150-test-0294` | billing | billing | it is damaging to my credit score if i miss one credit card payment |
| `CLINC150-test-0299` | billing | billing | will only having five late payments really make my credit bad |
| `CLINC150-test-0380` | billing | billing | what day will i earn my payment from work |
| `CLINC150-test-0383` | billing | billing | what day can i expect to receive payment on |
| `CLINC150-test-0385` | billing | billing | when will my payment be deposited |
| `CLINC150-test-4378` | billing | billing | what is my payment going to be |
| `CLINC150-oos_test-0121` | access | access | can you sign out of my bank login |
| `CLINC150-oos_test-0484` | upload | upload | upload the pictures to the correct album |
| `CLINC150-oos_test-0004` | other | access | what is the account number to the internet service i have |
| `BANKING77-test-1640` | other | access | My phone was stolen |
| `BANKING77-test-1641` | other | access | My phone was stolen yesterday.  What should I do? |
| `BANKING77-test-1880` | other | access | Can you remove my account please? |

- **The model's one weak spot here is the edge of `other`.** It was right on every case labelled `access`,
  `upload` or `billing` (87/87) and on 17/29 labelled `other`: it puts a request that is near a category into
  that category. The first eight are wrong for the rules too, so nothing raised them (the 8 "wrong for both").
  The same pattern is in the 61-case set (`EN-ADV-04`, 2026-11-06) and in the local 4B model's three mistakes
  (2026-11-08).
- **These 12 labels are the developer's mapping** of assistant and banking requests into four support
  categories. Whether "when will my payment be deposited" is `other` or `billing` is a judgement call, so
  the 12 show a boundary to look at, not 12 proven errors.
- **Confidence carried no signal:** all 116 answers said `high`, the 12 mistakes included, so the review
  reason `llm_low_confidence` never appeared. The local 4B model did the same on the study guide's 67
  requests (2026-11-08).
- **More than half of the cases were raised:** 64/116 here and 33/61 on the main set (2026-11-06), because
  the rules are wrong on 68/116 and 32/61. A flag on every second case orders little.
- On the 43 synthetic edge items (homoglyphs, zero-width characters, negation, words hidden in other words,
  Thai script, typos) Typhoon was right on 43/43 where the rules were right on 16/43.

## 2. How much of the rules' weakness is the keyword list

The official rules (`app/domains/case_triage/agents.py`, `keywords-v1`) know 10 English keywords. The mock's
simulation (`app/llm/providers/mock.py`) is the same idea with a longer list: 52 keywords, 20 of them Thai.
Its list was last changed on
2026-11-01 (commit `74dd10c`), six days before the edge set was written (2026-11-07, commit `05deefa`), so
the edge set is unseen text for it. It was written alongside the 61-case set, so that score is inflated.

| Set | Rules `keywords-v1` | The mock's longer list | Typhoon |
|---|---|---|---|
| 61 cases (written alongside the mock's list) | 29/61 | 59/61 | 60/61 (2026-11-06, two runs) |
| ... Thai | 7/26 | 25/26 | 26/26 |
| 116 edge cases (unseen by the list) | 48/116 | 74/116 | 104/116 (this note) |
| ... Thai | 3/13 | 11/13 | 13/13 |

Both columns come from the mock scorecard's own lines "กฎเดิมจัดหมวดถูก" and "AI จัดหมวดถูก" (the mock's
answer is its keyword list's category), so they can be re-run offline with the commands in section 1.

- A longer list with Thai words lifts the unseen hard set from 48 to 74 of 116. That is the size of the
  gain a list alone can give; the remaining 42 need what a list cannot do (word boundaries, negation, typos,
  look-alike letters, meaning).
- With the mock as the second opinion, as on the online page today, only 26 of the rules' 68 mistakes on
  the hard set were raised; Typhoon raised 60.

## 3. The first case after a start

**From Honeycomb** (environment `test`, dataset `neuron-flow`, the 7 days to 2026-11-09 23:51 UTC; the
service on Render's free plan with the mock AI):

| Span | Count | Duration |
|---|---|---|
| `job case_triage.v2` | 2 | 9,904 ms and 10,498 ms |
| ... `run` (first claim to outcome) | 2 | 9,480 ms and 10,097 ms |
| ... `step classify_rules` | 2 | 9,393 ms and 10,012 ms |
| ... `step classify_llm` | 2 | 4,218 ms and 4,402 ms |
| ... `step compare`, `step prepare` | 2 each | at most 14 ms |
| `job study_guide.v1` | 1 | 418 ms (its five steps: 16 to 74 ms each) |
| `queue wait` (admitted to first claim) | 3 | median 401 ms, slowest 423 ms |
| `POST /v1/jobs` | 3 | median 12.8 ms, slowest 13.8 ms |

- The whole week held 3 jobs. Both triage jobs were the first job after a start and took about 10 s; the
  study question ran while the service was warm and took 0.4 s. With the two starts measured on 2026-11-01
  (9.8 s and 9.0 s, [evidence](2026-11-03-render-operations.md)), the first job after a start took 9.0 to
  10.5 s in 4 of 4 observations. Later jobs took 0.1 to 0.4 s.
- Sentry lists no unresolved issue in the last 30 days.

**Reading of the code** (not measured on Render): Core starts a worker process when a step first needs one
and waits until it reports ready, at most 10 s (`neuron_flow/engine.py`, `Worker`). The first triage job
needs two workers, and the loop starts them one after the other before it collects any result. `step
classify_llm` (4.2 to 4.4 s) then covers the second worker's start, and `step classify_rules` (9.4 to 10.0 s)
covers both, which leaves about 5.0 to 5.8 s for the first. A worker start is a new Python process that
imports the Runner's modules.

**Import timing in this session** (Python 3.12.3, a fresh process importing `app.services.runner`, 214
modules of which 143 have a bytecode cache file; 10 runs each; `-B` with `PYTHONPYCACHEPREFIX` pointing at a
full, a partial or an empty cache folder):

| Bytecode cache present | min | median | max |
|---|---|---|---|
| Every module | 96 ms | 116 ms | 169 ms |
| The standard library only (101 files) | 123 ms | 166 ms | 216 ms |
| None | 377 ms | 434 ms | 458 ms |

- The image is built with `PYTHONDONTWRITEBYTECODE=1` and no compile step (`Dockerfile`), and the service
  cannot write into its code folder, so `app/` and `neuron_flow/` have no cache there. Whether the base
  image's standard library has one was **not checked** (there is no Docker in this session); the first task
  of E1 in the plan checks it in the *Service container* job.
- If nothing is cached, a start costs about 3.7 times the processor time of a fully cached one here
  (434 ms against 116 ms). Render's free instance is much slower than this container, so the same ratio
  there would be seconds. This is an estimate until it is measured on Render.
- By that reading a worker start takes 4.2 to 5.8 s on Render, within a factor of about 2 of Core's 10 s
  start limit. A worker that is not ready in time fails the step attempt (`WorkerStartError`), and
  `classify_rules` has one attempt, so a slower moment on the free instance could turn the first case after
  a start into a failed job instead of a wait. This has not been observed.

## What this shows, and what it does not

- **Shows:** where the triage flow loses effectiveness on these sets: the official rules (48/116 and 29/61),
  not the second opinion (104/116 and 60/61), and the share of cases raised (over half).
- **Shows:** the real model stayed right on unseen hard text in both languages, and answered every case in
  the right format on the first attempt (116/116).
- **Does not show accuracy.** One run. The labels are the developer's, and for the 73 open requests they are a
  mapping into categories those datasets were not written for. No independent person labelled anything.
- **Does not show latency for users.** The latency was measured from this session through its proxy, not
  from Render.
- **Does not prove the cause of the 10 s.** The spans and the code fit the missing bytecode cache, and the
  timing shows the size of that cost here; only a measurement on Render after the change can confirm it.

## Limits

- The Typhoon run was made from a cloud session, not from GitHub Actions, so there is no run page; the
  figures above are from the scorecard's own report and summary, which are not committed. The mock columns
  can be reproduced offline at commit `95d3560`.
- The service's default sampling applies (the client sends no sampling parameters), so another run can
  differ.
- Honeycomb holds 3 jobs for the week; the durations are single observations, not distributions.
