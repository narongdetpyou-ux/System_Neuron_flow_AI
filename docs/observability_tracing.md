# Tracing to Honeycomb (roadmap 5.1)

**Status:** built in PR #30 and tested offline (28 tests in `tests/test_tracing.py`). On every push,
*Actions → Tracing check* runs the service with tracing pointed at the OpenTelemetry Collector and checks
what arrives. On Render it is on since the owner's Ingest key went in, and the first case's trace was seen
in Honeycomb on 2026-11-03 with all 9 spans
([evidence note](evidence/2026-11-03-first-trace-honeycomb.md)). That check found one gap: no step carried
its agent version, because the queue's copy of the spec lacks the versions Core records. The Runner now
reads them from Core. No Core (`neuron_flow/`) file was changed and no dependency was added (ADR-017).

## สรุปสำหรับเจ้าของโปรเจกต์ (ภาษาไทย)

### ระบบส่งอะไรไปที่ Honeycomb

1. ทุกเคสกลายเป็นเส้นทาง 1 เส้น (trace) ที่เรียงเป็นชั้น:
   คำขอที่ส่งเคส → ตัวงาน (job) → รอคิว (queue wait) → ทำงาน (run) → แต่ละขั้น
   (กฎคำสำคัญ, AI, เทียบผล, เตรียมข้อเสนอ) → การเรียก AI (chat)
2. แต่ละช่วง (span) บอกว่าเริ่มเมื่อไร ใช้เวลานานเท่าไร สำเร็จหรือไม่ ถ้าไม่สำเร็จ ผิดพลาดแบบไหน
   และขั้นนั้นลองครั้งที่เท่าไร ถ้า AI ล้มครั้งแรกแล้วระบบลองใหม่ จะเห็นเป็น 2 ช่วง
3. ช่วงของการเรียก AI บอกรุ่น AI (model) จำนวน token ขาเข้าและขาออก และเวลาที่ AI ใช้ตอบ
   (AI จำลองนับ token แบบประมาณ และช่วงนี้บอกไว้ว่าเป็นค่าประมาณ)
4. คำขอทุกคำขอที่เข้า API (ที่อยู่ขึ้นต้นด้วย `/v1/`) เป็นเส้นทางสั้น ๆ ของตัวเองด้วย เช่น หน้าเว็บถามสถานะทุก 4 วินาที
   ส่วนการเปิดหน้าเว็บและการตรวจชีพจรของ Render (`/healthz`) ไม่ส่ง

**ไม่ส่งเด็ดขาด:** ข้อความเคส รหัสเคส prompt คำตอบหรือเหตุผลของ AI คีย์ทุกชนิด ที่อยู่ IP
และข้อความผิดพลาด (ส่งแค่ชื่อชนิดของความผิดพลาด) ระบบมีรายชื่อช่องข้อมูลที่อนุญาตไว้ล่วงหน้า
ข้อมูลที่ไม่อยู่ในรายชื่อส่งไม่ได้ และมีการทดสอบที่ใส่ข้อความลับลงในเคสแล้วสแกนทุกอย่างที่ส่งออกไป

**ค่าใช้จ่าย:** แผนฟรีของ Honeycomb รับได้ถึง 20 ล้านช่วงต่อเดือน ([ราคา](https://www.honeycomb.io/pricing)).
เคส 1 เคสใช้ 9 ช่วง (นับในชุดทดสอบและใน CI) ส่วนหน้าเว็บที่เปิดดูอยู่ใช้ 2 ช่วงทุก 4 วินาที
(ถามสถานะและรายการเคส) ระบบนี้จึงใช้น้อยกว่าเพดานมาก

### เปิดใช้อย่างไร (ทำครั้งเดียว)

1. ที่ [ui.honeycomb.io](https://ui.honeycomb.io): Team Settings → Environments → กดเฟืองของพื้นที่ `test` →
   API Keys → **Create Ingest API Key** → ตั้งชื่อ → ติ๊ก **Can create services/datasets** → Create →
   ในหน้าต่างที่เด้งขึ้น กดคัดลอก **ค่าเต็มของคีย์** ทันที ค่านี้ยาว 64 ตัว และแสดงครั้งเดียว
   - **อย่าใช้รหัสประจำคีย์ (Key ID) อย่างเดียว** Key ID ยาวแค่ 32 ตัวและขึ้นต้นเหมือนกัน ถ้าใส่ Key ID
     Honeycomb จะตอบว่าไม่รู้จักคีย์ (401) ค่าเต็มคือ Key ID ต่อด้วยรหัสลับ (secret) โดยไม่เว้นวรรค
   - ถ้าปิดหน้าต่างไปแล้ว ให้สร้างคีย์ใหม่ เพราะดูค่าเต็มซ้ำไม่ได้
2. ที่ Render: บริการ `neuron-flow` → แท็บ Environment → เพิ่มเป็น **แถวใหม่** ชื่อ `HONEYCOMB_API_KEY` → วางค่าเต็ม
   → Save (อย่าวางคีย์ในแชท ไฟล์ หรือ issue)
   - **อย่าแก้ชื่อหรือค่าของแถว `NEURON_FLOW_ACCESS_KEY`** ถ้าแถวนั้นหาย หน้าเว็บจะใช้ไม่ได้ (503) และเมื่อ Render
     สร้างรหัสให้ใหม่ ต้องคัดลอกรหัสใหม่ไปใส่ในหน้าเว็บ
3. รอระบบรีสตาร์ท 1–2 นาที (แผนฟรี: เคสเก่าในคิวจะหาย) แล้วเปิดหน้าเว็บ → แท็บ "ตั้งค่า" →
   กล่อง "เส้นทางงานใน Honeycomb" ต้องขึ้น **"เปิด — ส่งไป api.honeycomb.io"**
4. ถ้าบัญชี Honeycomb อยู่ฝั่งยุโรป (ที่อยู่เว็บเป็น `ui.eu1.honeycomb.io`) ให้เพิ่ม
   `HONEYCOMB_API_ENDPOINT` = `https://api.eu1.honeycomb.io` ด้วย

**ปิดชั่วคราวโดยไม่ลบคีย์:** เพิ่ม `NEURON_FLOW_TRACING` = `off` ใน Render การปิดไม่เปลี่ยนผลของเคสใด ๆ
(มีการทดสอบยืนยันว่าเคสเดียวกันได้ผลเหมือนกันทั้งตอนเปิดและปิด)

### ดูเส้นทางของเคส

1. ส่งเคสตัวอย่างในหน้าเว็บ กดยืนยัน รอจนขึ้น "รอคนตรวจ"
2. กด "รายละเอียดเชิงเทคนิค" ใต้เคสนั้น คัดลอก "รหัสเส้นทางใน Honeycomb (trace id)"
3. เปิดลิงก์แบบนี้ แล้ววางรหัสต่อท้าย:
   `https://ui.honeycomb.io/<ชื่อทีม>/environments/test/trace?trace_id=<รหัสเส้นทาง>`
   (ชื่อทีมดูได้จากที่อยู่เว็บตอนเปิด Honeycomb; ลิงก์นี้หาเส้นทางในช่วง 2 ชั่วโมงล่าสุด)
4. ต้องเห็นแถบเรียงเป็นชั้น 9 แถบ: `POST /v1/jobs` อยู่บนสุด ใต้มันคือ `job case_triage.v2`
   แล้วแตกเป็น `queue wait` กับ `run` และใต้ `run` มี 4 ขั้น โดยใต้ `step classify_llm` มี `chat …`

ถ้ากล่องในหน้าตั้งค่าขึ้น "ส่งไม่สำเร็จ" ข้อความจะบอกสาเหตุ เช่น คีย์ไม่ถูกต้อง (401) ระบบยังทำเคสได้ตามปกติ
เพราะการส่งเส้นทางงานไม่มีผลกับการทำงาน

## How it works

### Design (ADR-017)

- **Form.** An optional adapter in `app/observability/`, like Sentry. It is off unless `HONEYCOMB_API_KEY`
  is set, and Core stays dependency-free.
- **No SDK.** `app/observability/tracing.py` encodes spans as OTLP/HTTP JSON and posts them with `urllib`.
  The OpenTelemetry SDK would bring its API, SDK and OTLP exporter packages and their dependencies
  (protobuf and requests among them) for features this service does not use: most spans are built after
  the fact with explicit times, and there is no automatic instrumentation. Attribute names still follow the
  OpenTelemetry semantic conventions (HTTP, GenAI), so moving to the SDK later would keep the data the same.
- **One trace per job.** Each process (the API and the Runner) has its own exporter.
  - The API makes a span for every `/v1` request, before handling it. A request that admits a job stores
    its span as a W3C `traceparent` in the job's `job.queued` event.
  - The Runner builds the job's spans after recording its outcome (`app/observability/job_spans.py`) and
    makes the job span a child of that request span. So both processes write into the same trace, and
    nothing is exported from Core's child processes.

### The trace of one job

```text
POST /v1/jobs                    SERVER  the request that admitted the case (API process)
└── job case_triage.v2           admitted → outcome; status, claims, failure reason, wait and run ms
    ├── queue wait               admitted → first claim
    └── run                      first claim → outcome
        ├── step classify_rules  one span per attempt: attempt, max attempts, outcome, agent version, error type
        ├── step classify_llm
        │   └── chat <model>     CLIENT  the AI call: GenAI attributes, tokens, latency
        ├── step compare
        └── step prepare
```

- **Times are wall-clock times** written by the API, the Runner and Core on one machine.
- **A step span** runs from the moment Core started the attempt to the moment it recorded the outcome.
  It includes starting a worker process for the step, which is most of the time with the mock AI.
- **The AI call's length** is the gateway's measurement. Its position inside the step is not recorded, so
  the span is placed to end with its step attempt (`neuron_flow.ai.placement = ends_with_attempt`); the
  call is the agent's last action. It can be off by the few milliseconds Core needs to collect and check
  the answer.
- **A failed AI attempt that Core retried** has no AI span; its step span carries the error type (for
  example `LLMTransientError`). An "unavailable" second opinion has no AI span either; its step span
  carries `neuron_flow.ai.status = unavailable` and the reason code.
- **A job Core never ran** (`configuration_changed`, `unknown_workflow_type`) has only the job, queue-wait
  and run spans. A job admitted while tracing was off starts its own trace.
- **Recovery.** A job finished by a new Runner after a restart shows `neuron_flow.job.claims = 2`. The
  interrupted attempt ends with `error.type = ControllerInterrupted`.

### What a span may carry

Only the attributes listed in `SPAN_ATTRIBUTES` (`app/observability/tracing.py`), with fixed types. Every
text value must be printable ASCII, at most 256 characters.

| Span | Attributes |
|---|---|
| HTTP | `http.request.method`, `http.route` (a template such as `/v1/jobs/{job_id}`, never the path), `http.response.status_code`, `error.type` (5xx), `neuron_flow.request_id` |
| job, queue wait, run | `neuron_flow.job.id`, `workflow_type`, `job.status`, `job.claims`, `core.status`, `failure.reason`, `queue.wait_ms`, `job.run_ms`, `request_id`, `error.type` |
| step | `neuron_flow.job.id`, `step.id`, `step.agent`, `step.attempt`, `step.max_attempts`, `step.outcome`, `agent.version`, `error.type`, `ai.status`, `ai.reason` |
| AI call | `gen_ai.operation.name` (`chat`), `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.response.model`, `gen_ai.request.max_tokens`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `neuron_flow.ai.usage_estimated`, `ai.prompt_id`, `ai.prompt_sha256`, `ai.redaction`, `ai.masked_items` (a count), `ai.latency_ms`, `ai.placement` |

Resource (every span): `service.name`, `service.version` (`<version>+<commit>` on Render and in CI),
`service.instance.id`, `deployment.environment.name` (`render`, `ci` or `local`), `neuron_flow.process`
(`api` or `runner`), `telemetry.sdk.*`.

**Never carried:** case text, case ids, prompts, AI answers and rationales, error messages, step params,
file paths, client addresses, user agents, URL paths and query strings, and keys. Job ids are carried,
as in Sentry events, so a job's spans can be found; access log lines still carry none.

### Sending

- **Batches.** One background thread per process sends a batch every 2 seconds, or sooner when 256 spans
  wait. The queue holds 2048 spans. A job's spans are queued whole, or dropped whole when there is no room.
- **Retries.** 408, 429, 5xx and network errors are retried twice (after 1 s and 3 s). Other answers
  (for example 401 for a wrong key) are not retried. Spans that cannot be sent are dropped and counted.
  Each change of outcome is logged once, without the key.
- **The key** is read from the environment for every request (ADR-013) and sent only in the
  `x-honeycomb-team` header. Redirects are refused, so it can never be forwarded to another host.
- **On stop,** each process spends at most 2 seconds sending what is queued. The launcher stops the Runner
  within 25 seconds, so this stays inside Render's 30-second stop window.
- **Never in the way.** Building or sending a trace never changes a job or a response. Errors in either
  are logged with their type only.

### Configuration

| Variable | Default | Meaning |
|---|---|---|
| `HONEYCOMB_API_KEY` | none (tracing off) | Honeycomb Ingest key, the full value (key ID followed by the secret, 64 characters; the 32-character key ID alone gets 401); set it in Render's Environment tab, never in a file |
| `HONEYCOMB_API_ENDPOINT` | `https://api.honeycomb.io` | EU: `https://api.eu1.honeycomb.io`. Any OTLP/HTTP receiver works; plain `http` only on this machine |
| `OTEL_SERVICE_NAME` | `neuron-flow` | The service, and the dataset name in Honeycomb |
| `NEURON_FLOW_TRACING` | on when the key is set | `off` turns tracing off without removing the key |
| `NEURON_FLOW_ENVIRONMENT` | `render` / `ci` / `local` | `deployment.environment.name` |

A value the service cannot use turns tracing off and names the problem. The service still starts.
`GET /v1/status` → `tracing` shows the state, and so does the page's settings tab:

```json
"tracing": {"enabled": true, "problem": null, "destination": "api.honeycomb.io", "service_name": "neuron-flow",
            "exported_spans": 42, "dropped_spans": 0, "failed_exports": 0, "queued_spans": 0,
            "last_ok_at": "2026-11-03T12:00:01.234Z", "last_error": null, "last_error_at": null}
```

The export figures are those of the API process, which answers the status request. The Runner exports
the job spans with the same settings, to the same place, and logs its own failures.

`GET /v1/jobs/{job_id}` includes `trace_id` (`null` when the job was admitted with tracing off), and the
page shows it in the case's technical details.

## What proves it

| Check | Where |
|---|---|
| One job is one trace: request → job → queue wait and run → each step (with its agent version) → AI call, linked parent to child | `tests/test_tracing.py`: `test_one_job_is_one_trace_with_its_steps_and_the_ai_call`; CI *Tracing check* with the OpenTelemetry Collector; seen in Honeycomb on Render ([evidence note](evidence/2026-11-03-first-trace-honeycomb.md)) |
| Turning tracing off changes no result (same cases, same statuses, reviews, steps, AI answers and history) | `test_turning_tracing_off_changes_no_result` |
| Nothing private is sent: sentinels in the case text (Thai text, an e-mail address, a phone number, a Thai ID number), the case id, the AI rationale, the prompt and both keys are absent from every request body | `test_nothing_private_is_ever_sent`; CI *Tracing check* (the smoke test's cases) |
| Only listed, typed, ASCII attributes can be sent | `test_only_listed_short_ascii_attributes_are_accepted` |
| A wrong key, a busy or unreachable receiver, a redirect, a full queue, a missing key and a broken trace never affect the work | `ExporterTests`, `test_a_trace_that_cannot_be_built_never_touches_the_job` |
| A retried step shows both attempts | `test_a_retried_step_shows_both_attempts` |
| The encoding is accepted by the reference OTLP receiver | CI *Tracing check* (`.github/workflows/tracing-check.yml`) |

## Limits

- **Seen in Honeycomb once.** One case's trace was checked in Honeycomb on 2026-11-03, with the mock AI
  ([evidence note](evidence/2026-11-03-first-trace-honeycomb.md)). Traces with real Claude, retries or
  recoveries have only been checked offline and against the Collector.
- **Per step, not inside a step.** A step's span covers the whole attempt, including the worker start; what
  the agent does inside (masking, the provider's own retries) is not broken down.
- **No metrics or logs signals**, and no sampling: every span is sent. At this volume the free plan is
  enough.
- **The Runner's export figures** are not on the status page (only the API's). A failure on the Runner side
  appears in its log.
- **Cancelled jobs** never reach the Runner, so they have no job span; the cancel request has its own span.
