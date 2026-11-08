# First smoke run of the local open model (roadmap 5.8, ADR-026)

**Date:** 2026-11-08. **Model:** Typhoon 2.5 Qwen3 4B by SCB 10X (Apache-2.0), the file
`typhoon2.5-qwen3-4b-q4_k_m.gguf` from `typhoon-ai/typhoon2.5-qwen3-4b-gguf` at commit `386874d02430`,
2,497,276,128 bytes, SHA-256 `b365302922688f3a3c9ac8e3c00ab97a152cac0cdbf4eb5a734ecb483ae3e511` (the publisher's
value, matched by the download; pinned in the workflow after this run). Model id
`typhoon2.5-qwen3-4b-q4_k_m:b36530292268`. **Server:** llama.cpp `b12198` (`f477f795cb07`), built on the runner
with AVX2, FMA and F16C, listening on 127.0.0.1:8080; temperature 0, repeat penalty 1.05, thinking off, context
16384 over 2 slots. **Where:** GitHub Actions, a standard `ubuntu-latest` runner of this public repository, the
workflow *Local open model eval*, started by pull request #46 on its merge commit `c69f129dc9d2` (head
`9805eea`). **Data:** synthetic only, the first 5 cases and the first 5 requests. Nothing was sent to an AI
company and no key was used. **Source:** the job log, read through the GitHub API.

## สรุปสำหรับเจ้าของโปรเจกต์

- **ต่อติดครบทุกขั้นตั้งแต่รอบแรก** เครื่องทดสอบของ GitHub สร้างโปรแกรมรันโมเดล ดาวน์โหลดไฟล์โมเดล 2.5 GB
  ตรวจลายนิ้วมือ (SHA-256) ผ่าน เปิดโมเดลในเครื่อง แล้วตอบประโยคทดสอบเป็น JSON ถูกรูปแบบตั้งแต่ครั้งแรก
  (ต่างจาก Typhoon ออนไลน์รอบแรกเมื่อ 6 พ.ย. ที่ตอบผิดรูปแบบ เพราะโปรแกรมรันโมเดลบังคับรูปแบบคำตอบได้)
- **คัดแยกเคส 5 เคสแรก:** AI ตอบได้ 5/5 จัดหมวดถูก 5/5 กฎเดิมถูก 3/5 และความผิดของกฎทั้ง 2 เคสถูกยกให้คนดูก่อน
  ไม่มีเคสที่ AI ใช้งานไม่ได้ เวลาตอบกลาง (p50) ราว 2.7 วินาทีต่อเคส (Typhoon ออนไลน์ราว 0.7 วินาที)
- **ผู้ช่วยแนะนำแหล่งเรียน 5 ข้อแรก:** หัวข้อถูก 5/5 ไม่มีลิงก์นอกคลัง (0 จาก 10) ไม่มีคำตอบเกิน 5 แหล่ง
  เวลาตอบกลางของขั้นถอดความราว 6.1 วินาที แต่ครั้งที่ช้าที่สุดใช้เกือบ 79 วินาที น่าจะเป็นครั้งแรกที่เครื่องต้องอ่านคำสั่ง (prompt) ยาวทั้งหมด
  ครั้งถัดไปใช้ส่วนที่อ่านแล้วซ้ำได้
- **ทั้งรอบใช้เวลาราว 7.5 นาที** ส่วนใหญ่เป็นการสร้างโปรแกรมครั้งแรก (2 นาที 43 วินาที) ซึ่งเก็บไว้ในแคชแล้ว
- **ยังไม่ใช่ความแม่นยำ:** แค่ 5 ข้อต่อชุด 5 เคสแรกเป็นเคสภาษาอังกฤษเรื่องเข้าระบบทั้งหมด เคสและเฉลยเขียนโดยผู้พัฒนาเอง
  และรันรอบเดียว ผลนี้เป็นของไฟล์โมเดลนี้กับการตั้งค่านี้เท่านั้น ไม่ใช่ของ Typhoon รุ่น 30B ผ่าน API และไม่ใช่ของ Claude
- **ขั้นต่อไป:** merge แล้วกดรันครบทั้งชุดใน Actions (ขั้น 5.8) ผลรอบเต็มจะจดเป็นบันทึกฉบับใหม่

## 1. The run

| Run | Started (UTC) | Commit | Trigger | Sets | Outcome |
|---|---|---|---|---|---|
| [42444910984](https://github.com/narongdetpyou-ux/System_Neuron_flow_AI/actions/runs/42444910984) | 03:58:59 | `c69f129` (PR #46's merge commit; head `9805eea`) | pull request (smoke, limit 5) | triage: first 5 cases; study guide: first 5 requests | job green; the AI answered 5/5 in each set |

Step times, from the log's timestamps:

| Step | Time |
|---|---|
| Build llama-server at the pinned commit (no cache yet) | 2 min 43 s |
| Download and check the model file (2,497,276,128 bytes) | 30 s |
| Start the server until `/health` answers | under 5 s |
| Connection check (one fixed sentence) | 14 s |
| Triage scorecard, 5 cases | 14 s |
| Study guide scorecard, 5 requests | 3 min 26 s |
| Whole job, from setup to the saved caches | about 7.5 min |

The build and the model file were saved to the Actions cache at the end of the job.

## 2. The connection check

The fixed sentence ("I cannot upload a file to my ticket.") got HTTP 200, `application/json; charset=utf-8`,
816 bytes, the served model `typhoon2.5-qwen3-4b-q4_k_m:b36530292268` (the server's alias), no Authorization
header sent, and this message content:

```text
{"category": "upload", "confidence": "high", "rationale": "The case explicitly mentions inability to upload a file, which directly relates to upload issues."}
```

The verdict was **answered**. Typhoon's hosted API answered its first check with plain `key: value` lines
(ADR-022); this server enforces `response_format` as a grammar and gets the same format words. One reply is
not a rate.

## 3. Case triage: the first 5 cases

Cases `case_triage_synthetic_v1`, prompt `triage_classify_v1` (`5cb3b35cb3bc`). The Typhoon column is run 2
of [the 2026-11-06 note](2026-11-06-first-live-typhoon.md), the same five cases.

| Measure | Local 4B (this run) | Typhoon 30B API, run 2 (2026-11-06) |
|---|---|---|
| Jobs completed | 5/5 | 5/5 |
| Rules correct | 3/5 | 3/5 |
| AI answered | 5/5 | 5/5 |
| AI correct (of answered) | 5/5 | 5/5 |
| Rules and AI agree | 3/5 | 3/5 |
| Raised for review first (elevated) | 2/5 | 2/5 |
| Rule mistakes raised | 2/2 | 2/2 |
| Raises that were needed (rules wrong) | 2/2 | 2/2 |
| AI unavailable / failed | 0 / 0 | 0 / 0 |
| Tokens in / out | 1,978 / 168 | 1,978 / 154 |
| AI latency p50 / p95 | 2,708.1 / 3,002.0 ms | 709.7 / 755.8 ms |

- The five cases are all English `access` cases (EN-ACC-01 to 05), and both models gave the labelled category
  for all five. They show that the path works, not how well.
- The input token count is the same as Typhoon's for the same five requests; both models are built on Qwen3.
- The median latency is 3.8 times Typhoon's (2,708.1 ms against 709.7 ms), on a CPU-only runner.

## 4. Study guide: the first 5 requests

Requests `study_guide_synthetic_v1` (three in Thai, two in English; three paraphrases and two metaphors),
library `v1@sha256:1cfcff2d5fc9…`. The Typhoon column is run 3 of the 2026-11-06 note, the same five requests.

| Measure | Local 4B (this run) | Typhoon 30B API, run 3 (2026-11-06) |
|---|---|---|
| Jobs completed | 5/5 | 5/5 |
| Topic step answered | 5/5 | 5/5 |
| **Topic correct (in scope)** | 5/5 | 5/5 |
| All correct | 5/5 | 5/5 |
| In-scope requests turned away | 0/5 | 0/5 |
| **Links outside the library** (must be 0) | 0 of 10 | 0 of 10 |
| **Answers with more than 5 resources** (must be 0) | 0 of 5 | 0 of 5 |
| Asked "did I understand you?" | 5/5 | 5/5 |
| Explanation written by the AI | 5/5 | 5/5 |
| AI unavailable / failed | 0 / 0 | 0 / 0 |
| Tokens in / out (both AI steps) | 15,377 / 824 | 15,510 / 942 |
| Topic step latency p50 / p95 | 6,114.4 / 78,885.2 ms | 1,271.4 / 1,813.2 ms |

- With five requests, the p95 is the slowest call. The page gives no per-call times; the likely cause is the
  first call, which read the whole prompt before the server's prompt cache held its start.
- The explanation step's prompt carries what the first step answered, so the token totals differ a little.

## 5. What this shows, and what it does not

- **Shows:** the whole path works on a free runner with no key and no outside AI service: the build from a
  pinned commit, the download with its SHA-256 check, the server on 127.0.0.1, the client's request, the
  answer format, the validators, both workflows end to end and the run page's notes.
- **Does not show accuracy:** five items per set, the easiest ones first, labels written by the developer, one
  run.
- **Latency** belongs to this runner. A Render machine would differ and must be measured there (roadmap 5.8,
  step 4).

## Limits

- One smoke run on the first five items of each set.
- This session cannot download the run's artifacts, so the job log is the record; the server table with the
  runner's CPU count is on the run page only.
