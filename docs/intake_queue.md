# Intake API, job queue, Runner and web page (round 2, Milestone B)

**Status:** built in PR #11 and tested offline (98 tests, including killing the Runner mid-step). The
container build is checked on every push by *Actions → Service container*. **Not deployed yet**; the
host is Render (`render.yaml`). Railway was the first choice, but it has paused new sign-ups since
22 Oct 2026 after a security incident; `railway.json` stays in the repository for later. Synthetic data
only. Review decisions (approve/reject) come with Milestone C, so in this round every case ends at
"waiting for a person". No Core (`neuron_flow/`) file was changed.
Design principles: [design_philosophy.md](design_philosophy.md).

## ภาพรวมการทำงาน (ภาษาไทย)

### เมื่อมีคนส่งเคส 1 เคส ระบบทำอะไรบ้าง

1. **ส่งเคส** ผ่านหน้าเว็บ หรือผ่าน API (`POST /v1/jobs`) พร้อม "รหัสส่งงาน" (idempotency key) หนึ่งรหัสต่อการกดส่งหนึ่งครั้ง หน้าเว็บสร้างรหัสนี้ให้เอง
2. **ตรวจก่อนรับ** ระบบตรวจรหัสเข้าใช้ ขนาดคำขอ และข้อมูลเคส (รหัสเคส + ข้อความ 8–500 ตัวอักษร) ถ้าไม่ผ่าน ระบบตอบกลับทันทีและยังไม่สร้างงานใด ๆ
3. **บันทึกลงคิวถาวรก่อนตอบ** ระบบตอบว่า "รับแล้ว" (202) หลังบันทึกเสร็จเท่านั้น
   - ส่งซ้ำด้วยรหัสส่งงานเดิมและข้อความเดิม → ได้งานเดิมกลับมา (200) ไม่เกิดงานซ้ำ
   - รหัสส่งงานเดิมแต่ข้อความต่าง → ปฏิเสธ (409)
4. **ตัวรันงานมีตัวเดียว** หยิบงานตามลำดับที่เข้ามา บันทึก "สเปกงาน" ฉบับที่จะใช้จริงไว้ก่อน แล้วจึงส่งให้แกนระบบ (Core)
5. **Core ทำงานทีละขั้นเหมือนรอบ 1** กฎเดิมกับ AI ทำคู่กัน → เทียบสองความเห็น → เตรียมข้อเสนอ และตรวจผลทุกขั้นก่อนบันทึก
6. **บันทึกผล** สถานะสุดท้ายคือ "รอคนตรวจ" (`REVIEW_REQUIRED`) พร้อมสรุปที่อ่านง่าย ไม่มีที่อยู่ไฟล์ภายในหรือรหัสลับ
7. **ดูผล** หน้าเว็บอัปเดตเอง หรือเรียก `GET /v1/jobs/{job_id}`

### ถ้ามีอะไรผิดพลาด

| เหตุการณ์ | ระบบทำอะไร | คุณเห็นอะไรบนหน้าเว็บ |
|---|---|---|
| ข้อความสั้นหรือยาวเกิน ข้อมูลเกินที่กำหนด | ปฏิเสธทันที ไม่สร้างงาน (400) | ข้อความเตือนใต้ฟอร์ม |
| กดส่งซ้ำ หรือเน็ตหลุดแล้วส่งใหม่ | ใช้งานเดิม (200) | "ระบบรู้ว่าเป็นเคสเดิม จึงไม่สร้างงานใหม่" |
| เครื่องดับหรือรีสตาร์ทกลางงาน | เปิดใหม่แล้วทำต่อ นับครั้งที่ลองตามงบเดิมของขั้นนั้น | เคสเดินต่อ ในรายละเอียดเห็น "ตัวรันงานหยิบเคสนี้ 2 ครั้ง" |
| งบลองใหม่ของขั้นนั้นหมดแล้ว | หยุดเคสนั้นพร้อมเหตุผล ไม่รันเกินงบ | "ไม่สำเร็จ" และหมายเหตุ "ตัวรันงานหยุดกลางคัน" |
| เปลี่ยนรุ่น AI หรือ prompt ระหว่างที่เคสค้างอยู่ | ไม่รันต่อด้วยค่าใหม่โดยไม่บอก | "ตั้งค่า AI หรือ prompt ถูกเปลี่ยนหลังรับเคส" |
| เคสเดิมทำให้ตัวรันงานล่มซ้ำ 3 ครั้ง | พักเคสนั้นไว้ เพื่อไม่ให้วนล่มไม่จบ | "ตัวรันงานหยุดกลางคันระหว่างทำเคสนี้หลายครั้ง" |
| ตัวรันงานล่ม | ตัวเปิดระบบเปิดตัวรันงานใหม่ให้ใน 1–30 วินาที ระหว่างนั้นยังรับเคสเข้าคิวได้ | ป้าย "ตัวรันงาน: ไม่ตอบ" ชั่วคราว |
| ตั้งค่า AI ไม่ครบ (เช่น เลือก Claude แต่ไม่ใส่ key) | ไม่เริ่มงานใด ๆ เคสรอในคิวจนกว่าจะแก้ | แถบเตือนสีเหลืองบอกสาเหตุ |
| คิวเต็ม หรือส่งถี่เกินไป | ปฏิเสธชั่วคราว (503 / 429) | "คิวเต็ม" หรือ "ส่งถี่เกินไป รอ N วินาที" |
| ใส่รหัสเข้าใช้ผิด 10 ครั้งในหนึ่งนาที | พักการลองจากเครื่องนั้นชั่วคราว (429) | "ลองรหัสผิดหลายครั้งเกินไป" |

ทุกกรณีที่ระบบกู้งานหลังตัวรันงานหยุด จะส่งแจ้งเตือนเข้า Sentry ด้วย (ถ้าตั้งค่า `SENTRY_DSN` ไว้) ดู [observability_sentry.md](observability_sentry.md)

### สิ่งที่ต้องทำเพื่อเปิดใช้บน Render (ครั้งแรก ทำครั้งเดียว)

ไฟล์ `render.yaml` ในโปรเจกต์บอก Render ไว้หมดแล้วว่าต้องสร้างอะไร คุณจึงแค่กดยืนยัน

1. **Merge PR นี้** เข้า `main` (Render จะดึงโค้ดจาก `main`)
2. **สมัคร Render** ที่ render.com ด้วยบัญชี GitHub แผนฟรีไม่ต้องใช้บัตร
3. **สร้างจาก Blueprint** ในหน้า Dashboard กด New → Blueprint → Connect GitHub แล้วอนุญาตให้ Render เห็น repo `System_Neuron_flow_AI` → เลือก repo นี้ Render จะแสดงว่าจะสร้างบริการ `neuron-flow` แผน Free ที่ Singapore → กด **Deploy Blueprint**
4. **รอ build** ประมาณ 3–5 นาที จนสถานะเป็น Live
5. **คัดลอกรหัสเข้าใช้** เปิดบริการ `neuron-flow` → แท็บ Environment → ค่าของ `NEURON_FLOW_ACCESS_KEY` (Render สุ่มให้แล้ว) เก็บไว้ อย่าแชร์
6. **ลองใช้** เปิดลิงก์ `https://neuron-flow….onrender.com` ที่หัวหน้าบริการ ใส่รหัสเข้าใช้ แล้วส่งเคสแรก
7. **เชื่อมตัวเชื่อม Render ใน claude.ai** (ไม่บังคับแต่แนะนำ) แล้ว Claude จะดูสถานะการ deploy, log และการใช้ทรัพยากรให้ได้ ตัวเชื่อมสร้างบริการแบบ Docker ได้ก็จริง แต่ตั้ง health check การรอให้ชุดทดสอบผ่านก่อน deploy การสุ่มรหัสเข้าใช้ และดิสก์ไม่ได้ จึงควรสร้างจาก Blueprint ในขั้นที่ 3 (กดเองครั้งเดียว)

หลังจากนี้ ทุกครั้งที่มีการ merge เข้า `main` และชุดทดสอบบน GitHub ผ่าน Render จะอัปเดตระบบให้เอง ยกเว้นเมื่อแก้แค่เอกสาร ชุดทดสอบ หรือไฟล์ตั้งค่า GitHub Actions Render จะไม่อัปเดตระบบ (ตั้งไว้ใน `buildFilter` ของ `render.yaml`) เคสในคิวจึงไม่หายเพราะการแก้เอกสาร

**แผนฟรีควรรู้:** ระบบหลับเมื่อไม่มีคนเข้า 15 นาที เปิดครั้งถัดไปรอประมาณ 1 นาที และไม่มีดิสก์ถาวร เคสเก่าจึงหายทุกครั้งที่ระบบหลับ รีสตาร์ท หรืออัปเดต (หน้าเว็บจะขึ้นป้ายเตือน) ระบบยังทำงานครบทุกขั้นตามปกติ

**ถ้าอยากให้เคสไม่หาย:** แผน `0.5c-512mb` ($7/เดือน) + ดิสก์ 1 GB ($0.25/เดือน) ต้องผูกบัตร บอก Claude ให้แก้ `render.yaml` (เปลี่ยนแผน เปิดดิสก์ที่ `/var/data` และตั้ง `NEURON_FLOW_DATA_DIR`) แล้ว merge ห้ามแก้แผนในหน้า Dashboard เพราะ Blueprint จะเขียนทับค่าที่ขัดกับไฟล์

ไม่บังคับ (เพิ่มในแท็บ Environment ได้เลย Blueprint จะไม่ลบตัวแปรที่ไฟล์ไม่ได้กำหนด):
- ใช้ Claude จริงแทน AI จำลอง: เพิ่ม `NEURON_FLOW_LLM_PROVIDER=anthropic` และ `ANTHROPIC_API_KEY` (เสียค่า API ประมาณ 1 คำขอสั้น ๆ ต่อเคส)
- แจ้งเตือนข้อผิดพลาด: เพิ่ม `SENTRY_DSN`

## How it works

### Processes and data

```text
browser / n8n / curl
      │  HTTPS (Render's edge)
      ▼
container: tini ─► python -m app.serve
                    ├─ HTTP API + web page (app/api, app/web) ── admits, reads ──► <data>/app/queue.sqlite3
                    └─ Runner child process (app/services/runner.py), restarted with back-off if it exits
                         ├─ claims jobs, freezes specs, records results and a heartbeat in queue.sqlite3
                         └─ the only owner of Runtime(<data>/core): Core SQLite, reports, workspace lock
```

- `<data>` is `NEURON_FLOW_DATA_DIR` (on Render, the disk's mount path), else Railway's
  `RAILWAY_VOLUME_MOUNT_PATH`, else `./neuron_workspace` (not persistent in a container).
- The launcher starts as root only to take ownership of the disk (hosts may mount it as root), then
  switches to the unprivileged `neuron` user before it opens anything.
- The API never opens the Core `Runtime` (ADR-001). A disk attaches to one instance only, and a service
  with a disk cannot scale out, so two Runners never share it. Without a disk (Render's free plan) each
  instance has its own throwaway data, so an overlapping deploy cannot share anything either.

### Job states

```text
QUEUED ──► RUNNING ──► REVIEW_REQUIRED      the proposal waits for a person (every case_triage job)
                  ├──► COMPLETED            a workflow without a review step
                  ├──► FAILED               see failure.reason
                  └──► DELIVERY_FAILED      all steps done, but the report conflicted with an existing one
```

`failure.reason` is one of `step_failed`, `configuration_changed`, `runner_attempts_exhausted`,
`runtime_error`, `delivery_failed`, `unknown_workflow_type`.

### Recovery rules (the Runner at start-up)

For every job the queue still shows as `RUNNING`:
1. `claims >= NEURON_FLOW_MAX_CLAIMS` (default 3) → `FAILED: runner_attempts_exhausted`.
2. The spec the current settings would build differs from the spec frozen at the first claim → `FAILED:
   configuration_changed`. The job is never finished silently under another model, prompt or code version.
3. Otherwise the frozen spec is submitted again (Core treats an identical spec as a no-op) and run. Core
   marks the interrupted step `ControllerInterrupted` and retries it only if the step has attempts left.
   If Core had already finished the job before the crash, its saved result is used and nothing runs again.

In `case_triage.v2` only the AI step has a second attempt; the rule, compare and prepare steps take
milliseconds and have one. A planned stop is graceful: on SIGTERM the Runner finishes its current job
first, and the host waits 30 seconds before it stops the container (Render's default, which its free
plan does not let `render.yaml` change; `drainingSeconds` in `railway.json`). The launcher gives the Runner
25 of those seconds.

## API reference

Every `/v1` route needs `Authorization: Bearer <NEURON_FLOW_ACCESS_KEY>`. Bodies are JSON, at most 16 KiB.

| Method and path | What it does | Success | Errors |
|---|---|---|---|
| `GET /healthz` | Liveness for the host's health check (no key); also says whether an access key is set | 200 `{"ok": true, "access_key": "configured"}` | 503 |
| `GET /v1/status` | Runner heartbeat, queue counts, AI mode, storage, limits | 200 | 401, 429 |
| `POST /v1/jobs` | Admit a job | 202 new, 200 duplicate | 400, 401, 409, 411, 413, 415, 429, 503 |
| `GET /v1/jobs?limit=20&before=<seq>` | Newest first; `next_before` is the next cursor | 200 | 400, 401 |
| `GET /v1/jobs/{job_id}` | Status, reviewer proposal, step timeline, AI provenance, receipt hash | 200 | 401, 404 |
| `GET /v1/jobs/{job_id}/events?after=<seq>&limit=50` | History in bounded pages (`limit` 1–100) | 200 | 400, 401, 404 |

```bash
curl -s https://<your-service>.onrender.com/v1/jobs \
  -H "Authorization: Bearer $NEURON_FLOW_ACCESS_KEY" -H "Content-Type: application/json" \
  -d '{"workflow_type": "case_triage.v2", "idempotency_key": "n8n-2026-11-01-0001",
       "input": {"case_id": "CASE-001", "summary": "อัปโหลดไฟล์แนบไม่ได้ ค้างที่ 99%"}}'
# 202 {"job_id": "job_…", "status": "QUEUED", "queue_position": 1, "created": true, …}
```

- `workflow_type`: `case_triage.v2` (shadow mode, used by the page) or `case_triage.v1` (rules only).
- `idempotency_key`: 8–128 characters `[A-Za-z0-9._:-]`. Use one key per real submission and reuse it
  only to retry that submission.
- A request never carries agent names, import paths, steps, params or callbacks.

Error bodies look like `{"error": "<code>", "message": "<English text>"}`. Codes: `invalid_fields`,
`invalid_json`, `unknown_workflow_type`, `invalid_idempotency_key`, `invalid_input`,
`idempotency_conflict` (with the existing `job_id`), `queue_full`, `rate_limited` and
`too_many_attempts` (with `retry_after_s` and a `Retry-After` header), `unauthorized`,
`access_key_not_configured`, `body_too_large`, `unsupported_media_type`, `length_required`,
`invalid_parameter`, `job_not_found`, `method_not_allowed`, `not_found`, `internal_error`.

## What proves it (P0 gates for Milestone B)

| Gate (docs/architecture.md §9) | Test |
|---|---|
| Concurrent identical requests produce one job; a mismatched payload is a conflict | `test_service_api`: `test_concurrent_identical_requests_create_exactly_one_job`, `test_concurrent_mismatched_requests_get_conflicts_not_new_jobs` |
| Admission stays responsive while jobs run | `test_service_runner`: `test_admission_stays_responsive_while_a_job_runs` |
| Only one Runner holds the lock | `test_only_one_runner_can_own_the_workspace` |
| Killing the Runner mid-step reconciles within the retry budget | `test_a_runner_killed_mid_step_is_recovered_within_the_retry_budget`, `test_no_retry_budget_left_means_a_clear_failure` |
| Invalid input is rejected before any agent runs | `test_invalid_requests_are_refused_before_any_job_exists` |
| A failed validator blocks only the dependent steps | `test_a_failed_validator_blocks_only_the_steps_that_depend_on_it` |
| Delivery conflicts get their own status | `test_a_delivery_conflict_gets_its_own_status` |
| Changed settings never finish an interrupted job silently | `test_changed_ai_settings_never_finish_an_interrupted_job_silently` |
| The access key never appears in responses, stored files or logs | `test_the_key_is_never_in_a_response_or_a_stored_file`, `test_the_service_starts_works_and_stops_cleanly`, CI container job |
| The container runs without root, keeps data across a restart and stops cleanly | *Actions → Service container* (`examples/service_smoke_test.py`) |

The review-related P0 gates (one decision per version, unauthorised reviews denied, exactly one phase-B
job) belong to Milestone C and are still open.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `NEURON_FLOW_ACCESS_KEY` | none (the API refuses `/v1`) | Shared access key, at least 16 characters |
| `NEURON_FLOW_DATA_DIR` | Railway volume, else `./neuron_workspace` | Where the queue and Core data live; on Render, the disk's mount path (`/var/data`) |
| `PORT` / `NEURON_FLOW_HOST` | `8000` / `0.0.0.0` | Listening address |
| `NEURON_FLOW_LLM_PROVIDER`, `NEURON_FLOW_LLM_MODEL`, `ANTHROPIC_API_KEY` | `mock` | AI second opinion (see [case_triage_v2_shadow.md](case_triage_v2_shadow.md)) |
| `NEURON_FLOW_MAX_QUEUED` | `100` | Admission refuses new jobs above this many waiting |
| `NEURON_FLOW_SUBMIT_PER_MINUTE` | `30` | Submissions per client per minute (4× for everyone together) |
| `NEURON_FLOW_MAX_CONNECTIONS` | `32` | Concurrent HTTP connections |
| `NEURON_FLOW_RUNNER_WORKERS` | `2` | Core child processes |
| `NEURON_FLOW_MAX_CLAIMS` | `3` | Runner stops tolerated per job before it is failed |
| `SENTRY_DSN` | none | Error reporting (optional) |

## Security notes

- One shared access key, compared in constant time, sent as a bearer token. The page keeps it in the
  browser (session storage, or local storage when "remember" is ticked). There are no per-person accounts
  yet; Milestone C adds reviewer identity.
- Ten wrong keys in a minute from one client pause that client's attempts.
- The page loads nothing from other sites and allows no inline script (strict Content-Security-Policy).
  Server data is always inserted as text. The API sends no CORS headers.
- Body cap (16 KiB, checked before reading), connection cap, socket timeouts, queue cap and rate limits.
- Logs and Sentry events carry no case text, no query strings, no job ids in access lines and never the
  key. Responses carry no file paths.
- Data is synthetic. There is no redaction of personal data before the AI call yet (gap G5), so do not
  enter real customer information.

## Limits

- The HTTP server is Python's standard library server with the guards above. It suits a single-owner
  pilot; for real traffic, replace `app/api/server.py` with a production server (for example a small
  WSGI adapter around `ApiApp`, served by waitress or gunicorn).
- One machine, SQLite, one Runner (ADR-003). With a disk, each redeploy has a short downtime while the
  disk moves to the new instance. On Render's free plan the service sleeps after 15 idle minutes and
  forgets its cases.
- Rate limits live in memory and reset on restart.
- Live progress inside a running job is not shown step by step; the page shows the step timeline when the
  job finishes. Jobs with the mock AI finish in well under a second.
- Review decisions, the n8n intake and reviewer notifications are Milestone C.
