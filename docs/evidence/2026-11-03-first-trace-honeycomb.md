# First trace in Honeycomb (roadmap 5.1)

**Date:** 2026-11-03, 17:23 UTC (00:23 on 4 November, Bangkok time). **Environment:** Render web service
`neuron-flow` (free plan, Singapore), image `3a38034` (the PR #30 merge), mock AI (`mock/mock-keyword-1`);
Honeycomb US instance (`api.honeycomb.io`), environment `test`, dataset `neuron-flow`. **Source:** the
Honeycomb connector (span list, raw rows, the trace, the dataset's columns) and the Render connector
(deploys and app logs). The owner submitted the case from the web page. All data was synthetic.

## สรุปสำหรับเจ้าของโปรเจกต์

- **เส้นทางงานแรกเข้า Honeycomb แล้ว** ครบ 9 ช่วง (span) ตามแบบ: คำขอที่ส่งเคส → ตัวงาน → รอคิว กับ ทำงาน →
  4 ขั้น → การเรียก AI ช่วงทั้งหมดต่อกันเป็นเส้นเดียว ทั้งส่วนที่มาจากตัวรับคำขอ (API) และตัวรันงาน (Runner)
- **เห็นจุดที่ช้าได้ทันที** เคสนี้เป็นเคสแรกหลังระบบรีสตาร์ต ใช้เวลารวม 10.5 วินาที เวลาเกือบทั้งหมดอยู่ใน 2 ขั้นแรก
  ส่วน 2 ขั้นสุดท้ายใช้ขั้นละ 0.014 วินาที
- **ไม่มีข้อมูลส่วนตัวหลุด** Honeycomb ได้รับข้อมูล 52 ช่อง ไม่มีช่องไหนเก็บข้อความเคส prompt คำตอบของ AI หรือคีย์
- **ก่อนจะสำเร็จ Honeycomb ปฏิเสธคีย์ 3 รอบ (401)** เพราะค่าที่ใส่เป็นรหัสประจำคีย์ (Key ID) ไม่ใช่ค่าเต็มของคีย์
  ต้นเหตุคือคำแนะนำของเราเองที่เขียนกำกวม ตอนนี้แก้ทั้งหน้าเว็บและเอกสารแล้ว
- **เจอข้อมูล 1 ช่องที่ควรมีแต่ไม่มี** คือรุ่นของตัวทำงานแต่ละขั้น (agent version) แก้แล้วใน PR เดียวกับบันทึกนี้

## 1. The trace

Trace `ebd3dbbeea82acdda9b10281f678cd82`: job `job_1fc69d5f3297ac7629a52c9b`, request
`req_15e844c38fcdbf41`, admitted at 17:23:29.59 UTC. It was the first case after the restart at 17:23:03.
Every span carries `service.version = 0.4.0+3a38034fa459` and status UNSET (no errors).

| Span | Process | Parent | Starts at | Lasts |
|---|---|---|---|---|
| `POST /v1/jobs` (server, 202) | api | — (root) | +0.0 ms | 11.0 ms |
| `job case_triage.v2` (claims 1) | runner | `POST /v1/jobs` | +0.2 ms | 10,498.1 ms |
| `queue wait` | runner | job | +0.2 ms | 401.0 ms |
| `run` | runner | job | +401.2 ms | 10,097.0 ms |
| `step classify_rules` (attempt 1, SUCCEEDED) | runner | run | +434.9 ms | 10,011.6 ms |
| `step classify_llm` (attempt 1, SUCCEEDED, AI status ok) | runner | run | +6,232.6 ms | 4,218.2 ms |
| `chat mock-keyword-1` (client; 316 in, 32 out, estimated; 0 masked) | runner | `step classify_llm` | +10,450.7 ms | 0.06 ms |
| `step compare` (attempt 1, SUCCEEDED) | runner | run | +10,454.2 ms | 13.9 ms |
| `step prepare` (attempt 1, SUCCEEDED) | runner | run | +10,471.7 ms | 13.9 ms |

What it shows:
- **The shape matches the design** and the CI *Tracing check*: the same 9 names and parent links, the
  request span as the root, and the API's and the Runner's spans in one trace.
- **Where the time went.** The case took 10.5 s, which fits the cold start already recorded for this
  service (first job 9–10 s, [2026-11-03-render-operations.md](2026-11-03-render-operations.md)). The trace
  puts that time in the first two step attempts: `classify_rules` from +0.4 s and `classify_llm` from +6.2 s,
  both recorded as finished at about +10.45 s. `compare` and `prepare` took 14 ms each. A step span runs
  from Core starting the attempt to Core recording its outcome, including starting the step's worker
  process; what inside the attempt took the time is not broken down (see Limits in
  [observability_tracing.md](../observability_tracing.md)). A later case on an already running instance
  finished in 0.1 s (Runner log, 16:56:15 UTC).
- **Nothing private arrived.** The dataset has 52 columns: the allow-listed span attributes
  (`neuron_flow.*`, `gen_ai.*`, `http.*`), the resource attributes (`service.*`, `telemetry.sdk.*`,
  `deployment.environment.name`, `neuron_flow.process`) and Honeycomb's own fields (`name`, `duration_ms`,
  `trace.*`, `span.*`, `status_code`, `type`, `meta.signal_type`, `library.*`). None holds case text, a
  case id, a prompt, an AI answer or rationale, or a key.
- **A gap: no step carried its agent version.** There is no `neuron_flow.agent.version` column. The Runner
  built the spans from the queue's frozen spec, which lacks the `agent_versions` that Core adds to its own
  copy on submit; the unit test used a hand-made spec that had them. Fixed in the PR that adds this note:
  the Runner reads the versions Core recorded, and the end-to-end test now checks every step's version
  (it fails without the fix).

## 2. What failed first

Times are UTC (Bangkok is +7). Restarts after environment changes show in Render as deploys with the
trigger `service_updated` or `manual`.

| When | What happened | Seen in |
|---|---|---|
| 16:40:57 | Manual deploy of `3aa76a1`. At start `NEURON_FLOW_ACCESS_KEY` was missing; the page got 503 at 16:44:51 | deploys, app log |
| 16:45:36, 16:46:53 | Merge of PR #30: a Blueprint sync deploy (`render.yaml` changed), then the `new_commit` deploy. Tracing on; the access key was present again with a different value (the key saved in the page got 401 at 16:52:17) | deploys, app log |
| 16:52:20, 16:54:14 | Honeycomb answered 401; 1 and 8 spans dropped | app log |
| 17:00:38 | Environment changed; 401 again at 17:01:33 and 17:01:50 (2 and 8 spans) | deploys, app log |
| 17:06:34–17:09:04 | Environment changed three times: tracing off at 17:06 (no Honeycomb key); the access key missing at 17:08:12 (503 at 17:08:35); set again at 17:09 | deploys, app log |
| 17:12:59 | Environment changed; 401 at 17:13:31 and 17:13:52 (1 and 8 spans) | deploys, app log |
| 17:22:49 | Environment changed; tracing on at 17:23:03; the case at 17:23:29 was exported with no failure logged, and the trace above arrived | deploys, app log, Honeycomb |

- **The 401s.** The owner reported seeing two values, a Key ID and a second one, and using the Key ID, as
  our instruction said to copy "the key, starting with `hcaik_`", which fits both. Honeycomb's
  documentation: the Key ID is a label that identifies the key, and the value an Ingest key sends is the
  Key ID and the secret joined with no separator, shown in full only when the key is created. The page's
  setup step and its 401 message, and the owner steps in observability_tracing.md, now ask for the full
  64-character value and warn that the 32-character Key ID is not enough. The code was right: a 401 is
  what a wrong key should produce, and the service kept working throughout.
- **The access key.** It disappeared twice while the environment was edited. The first time it came back
  with a new value at 16:45, most likely from the Blueprint sync that the PR #30 merge triggered
  (`render.yaml` declares it with `generateValue: true`, and nothing else deployed in between); the owner
  then copied the new key into the page. The owner steps now say to add `HONEYCOMB_API_KEY` as a new row
  and leave `NEURON_FLOW_ACCESS_KEY` alone, and CLAUDE.md §7 records what a sync does with a missing key.

## 3. What this does not show

- **Mock AI only.** The AI call's tokens are estimated (`neuron_flow.ai.usage_estimated = true`) and its
  latency is close to zero; real Claude has never been run (roadmap 0.3).
- **One trace of one case.** The 10.5 s is a single cold start, not a performance measurement.
- **The Runner's export results** are only in its log; the page shows the API's (Limits in
  observability_tracing.md).
