# Roadmap — what to build next, in order

**Written 2026-11-01** on `main` @ `6d1f548`, after Milestone B (PR #11) and the Claude Code session hook
(PR #12). It is the working plan for Claude Code sessions and for the owner.

This file decides **what to do next, in which order, and how to know each step is done**. Why the system
is shaped this way is explained elsewhere:
- [architecture.md](architecture.md) covers layers, Core constraints, ADRs and gates.
- [design_philosophy.md](design_philosophy.md) is the owner's compass.

An older Thai planning document ("Architecture Roadmap v3") lives only in the claude.ai Project. Where it
differs, this file and architecture.md win.

## สรุปสำหรับเจ้าของโปรเจกต์

**ตอนนี้ระบบทำอะไรได้แล้ว**
- รับเคสผ่านหน้าเว็บภาษาไทยหรือ API แล้วบันทึกลงคิวถาวรก่อนตอบ
- ตัวรันงานหยิบเคสไปทำทีละเคส:
  - กฎคำสำคัญเสนอหมวด
  - AI ให้ความเห็นที่สอง
  - ถ้าสองฝ่ายเห็นไม่ตรงกัน เคสจะถูกยกให้คนดูก่อน
- ถ้าเครื่องดับกลางทาง ระบบทำต่อได้ ส่งซ้ำก็ไม่เกิดงานซ้ำ
- ผ่านชุดทดสอบอัตโนมัติ 98 ข้อ และพร้อมขึ้น Render

**ลำดับต่อจากนี้** แต่ละขั้นจบด้วยสิ่งที่คุณลองเองได้

| ขั้น | ทำอะไร | คุณจะได้ลองอะไร |
|---|---|---|
| 0 | เปิดใช้ออนไลน์บน Render และวัดผล Claude จริงครั้งแรก | ใส่เคสบนหน้าเว็บจริง และอ่านผลวัดของ Claude |
| 1 | เก็บงานเล็ก ๆ ให้ระบบแน่นขึ้น | ยกเลิกเคสที่ยังรอคิวได้ |
| 2 | ให้คนรีวิวได้จริง: ผู้รีวิวมีรหัสของตัวเอง กดอนุมัติหรือไม่อนุมัติได้ และ n8n แจ้งเตือน | กล่อง "รอรีวิว" บนหน้าเว็บ และข้อความแจ้งเตือน |
| 3 | ผู้ช่วยแนะนำแหล่งเรียน (`study_guide.v1`) ตามหลักปรัชญาของคุณ | พิมพ์เรื่องที่อยากรู้ด้วยคำธรรมดา แล้วได้แหล่งเรียนไม่เกิน 5 แหล่งพร้อมลำดับการเรียน |
| 4 | ช่องคุยภาษาธรรมดา: ระบบเข้าใจว่าคุณขออะไร บอกตรง ๆ เมื่อเรื่องอยู่นอกกรอบ และถามกลับ 1 คำถามเมื่อข้อมูลไม่พอ | คุยกับระบบได้เลย ไม่ต้องเลือกประเภทงานเอง |
| 5 | ติดตามเส้นทางของแต่ละงาน (เวลา token จุดที่ช้า) | ดูเส้นทางงานใน Honeycomb |
| 6 | AI วางแผนงานหลายขั้น ระบบตรวจแผนก่อนรัน และเครื่องมืออื่นเรียกใช้ผ่าน MCP ได้ | สั่งงานจากแอป Claude ได้ |
| 7 | เตรียมพร้อมก่อนให้คนอื่นใช้ หรือก่อนเปิด repo สาธารณะ | รายงานตรวจความปลอดภัย และรายการตรวจก่อนเปิดตัว |

**เรื่องที่คุณต้องตัดสินใจเอง** อยู่ในตาราง [Owner decisions](#owner-decisions) ข้างล่าง เช่น
- จะจ่ายค่า Render เพื่อให้เคสไม่หายหรือไม่
- จะใส่ Claude API key หรือไม่
- ใครเป็นผู้รีวิว
- จะเปิด repo เป็นสาธารณะเมื่อไร

## How to use this file (for Claude Code)

1. **Pick the next item.** Work from the top. Take the first item that is not ✅ and whose **Needs** are
   met. Items marked **owner** need clicks or a decision from the owner, so prepare everything first, then
   give them the steps in Thai.
2. **One work package ≈ one PR.** Split big packages. Never mix two packages in one PR.
3. **When a package is done:**
   - tick it in the status table;
   - update architecture.md (§5–§10 as relevant), the feature doc and the README;
   - add a dated evidence note if you measured anything (see [Evidence track](#evidence-track)).
4. **When reality differs from this plan** (a tool changed, or the owner decided something), update this
   file in the same PR and say so in the PR description. The plan serves the work. If the owner wants them,
   packages can be mirrored as GitHub or Linear issues, but this file stays the source of truth.
5. **How each package is written.** It has some or all of these parts:
   - **Goal** and **Why**;
   - **Tasks**;
   - **Done when** (automated tests, unless it says otherwise);
   - **Owner test** (in Thai);
   - **Don't**.

## Status at a glance

Done before this plan: A (v1 rules), A2 (AI gateway, shadow mode, scorecard, Sentry), B (intake API, queue,
Runner, web page), the docs refresh and the Claude Code session hook.

| ID | Work package | Status | Needs |
|---|---|---|---|
| 0.1 | Put round 2 online on Render | ⬜ owner | — |
| 0.2 | Free or paid hosting | ⬜ owner decision D1 | 0.1 |
| 0.3 | First scorecard run with real Claude | ⬜ owner (API key, D2) | — |
| 0.4 | Claude for the online page | ⬜ optional | 0.1, 0.3 |
| 0.5 | Skip Render deploys for docs-only commits | ⬜ | 0.1 |
| 0.6 | Open Dependabot PRs #1–#5 | ⬜ | — |
| 1.1 | Neutral telemetry phase names (the one planned Core change) | ⬜ | — |
| 1.2 | Request ids to follow a request through the logs | ⬜ | — |
| 1.3 | Cancel a job that is still queued | ⬜ | — |
| 1.4 | Backup, restore and retention | ⬜ | D1 = paid (disk) |
| 1.5 | Docs truth checks in CI | ⬜ optional | — |
| 2.1 | Personal access tokens and roles (replaces the shared key) | ⬜ | — |
| 2.2 | Review ledger and decisions API | ⬜ | 2.1 |
| 2.3 | Linked phase-B job on approval | ⬜ | 2.2 |
| 2.4 | Reviewer inbox on the web page | ⬜ | 2.2 |
| 2.5 | n8n intake and reviewer notifications | ⬜ | 2.1, 2.2, D3 |
| 2.6 | Side-effect contract | ⬜ when needed | before any outward action |
| 2.7 | Artifact store with hash checks | ⬜ when needed | — |
| 2.8 | Measure rules vs AI against reviewer labels | ⬜ | 2.2, 0.3 |
| 3.1 | Topic catalog and verified resource library | ⬜ | — |
| 3.2 | `study_guide.v1` workflow | ⬜ | 3.1 |
| 3.3 | Study-guide evaluation set and scorecard | ⬜ | 3.2 |
| 3.4 | Study guide on the web page | ⬜ | 3.2 |
| 4.1 | The frame: a versioned catalog of what the system can do | ⬜ | 3.2 |
| 4.2 | `intake.route.v1`: the plain-language router | ⬜ | 4.1 |
| 4.3 | Layered answers (summary → steps → details) | ⬜ | 4.2 |
| 4.4 | Chat-style page | ⬜ | 4.2 |
| 5.1 | OpenTelemetry tracing to Honeycomb | ⬜ | 1.1, 1.2 |
| 5.2 | Evaluation gate in CI | ⬜ | — |
| 5.3 | Queue and run-time metrics on the status page | ⬜ | — |
| 6.1 | Pattern A: bounded read-only tool loop | ⬜ | 3.2 |
| 6.2 | Pattern B: planner → checked plan → linked job | ⬜ | 2.2, 4.2 |
| 6.3 | MCP server (submit, get, list; never review decisions) | ⬜ | 2.1 |
| 7.1 | Mask personal data before AI calls; narrow key exposure | ⬜ | before any real data |
| 7.2 | Production HTTP server and authentication hardening | ⬜ | before other users |
| 7.3 | Independent security review | ⬜ owner | 7.1, 7.2 |
| 7.4 | Public-release checklist | ⬜ owner decision D5 | — |
| 7.5 | Consented pilot with real volunteers | ⬜ owner decision D4 | 7.1–7.3 |

Phase 2 can be built and tested without a disk. Real use needs D1 = paid: on the free plan, tokens and
decisions would vanish on every sleep.

---

## Phase 0 — Go live, and measure the real AI once

### 0.1 Put round 2 online on Render (owner + Claude)

- **Goal:** the owner opens a public link, enters the access key and submits cases.
- **Why:** Milestone B is built but has only run in CI. The owner tests by using it.
- **Tasks:**
  1. **Check what already exists.** PR #11 is merged, so the owner may already have created the service.
     Look with the Render connector (`list_services`) if it is available; otherwise ask once.
  2. **If there is no service yet,** give the owner the Thai steps in [intake_queue.md](intake_queue.md)
     ("สิ่งที่ต้องทำเพื่อเปิดใช้บน Render"):
     sign in with GitHub → New → Blueprint → this repo → Deploy Blueprint → copy `NEURON_FLOW_ACCESS_KEY`
     from the Environment tab.
  3. **After the first deploy:**
     - check that `GET /healthz` returns `{"ok": true, "access_key": "configured"}`;
     - read the deploy and app logs (`list_deploys`, `list_logs`, `list_events`);
     - fix anything that fails.
- **Done when** (checked by hand and recorded in the PR or chat):
  - the deploy is Live and `/healthz` reports the key as configured;
  - the example cases on the page reach "รอคนรีวิว" (`REVIEW_REQUIRED`);
  - pressing "ส่งซ้ำ" returns the same job;
  - `/v1/status` shows the Runner as alive.
- **Owner test (ไทย):**
  1. เปิดลิงก์ `https://neuron-flow….onrender.com` แล้วใส่รหัสเข้าใช้
  2. กดเคสตัวอย่าง ทุกเคสต้องขึ้น "รอคนรีวิว"
  3. กด "ส่งซ้ำ" ต้องได้เลขงานเดิม
  4. ทิ้งไว้ 20 นาทีแล้วเปิดใหม่ หน้าเว็บจะรอประมาณ 1 นาที และเคสเก่าจะหายตามที่ป้ายเตือนไว้ (แผนฟรี)
- **Don't:** paste the access key into chat, issues, docs or commits, or change the plan in the dashboard.

### 0.2 Free or paid hosting (owner decision D1)

- **Goal:** decide whether cases must survive restarts.
- **Facts** (check current prices before quoting them):
  - **Free:** $0. It sleeps after 15 idle minutes, has no disk, and loses the queue on every sleep, restart
    and deploy.
  - **Paid:** the `0.5c-512mb` instance (about $7 a month) plus a 1 GB disk (about $0.25 a month).
- **Tasks if paid:**
  1. In `render.yaml`, set `plan: 0.5c-512mb`, uncomment the `disk` block (mount path `/var/data`) and set
     `NEURON_FLOW_DATA_DIR=/var/data`.
  2. Open a PR.
  3. After the merge, check that a case survives a manual redeploy.
- **Done when:** a case submitted before a redeploy is still there after it (checked by hand), and the
  page's storage label shows persistent storage.
- **Owner test (ไทย):**
  1. ส่งเคส 1 เคส
  2. ใน Render กด Manual Deploy
  3. เปิดหน้าเว็บใหม่ เคสเดิมต้องยังอยู่

### 0.3 First scorecard run with real Claude (owner adds the key)

- **Goal:** the first honest measurement of a real model, failures included (funding evidence gate 2).
- **Tasks:**
  1. **Owner:** create an API key in the Claude Console, set a monthly spend limit there, and add the key
     as the repository secret `ANTHROPIC_API_KEY` (GitHub → Settings → Secrets and variables → Actions).
  2. Run *Actions → Shadow eval with Claude (manual)* with the default model (`claude-haiku-5-5`) and
     `limit` 5, then again on all 61 cases.
  3. Record the result in `docs/evidence/<date>-first-live-claude.md`:
     - the commit SHA, the run link, the model and the served model;
     - every rate as numerator/denominator;
     - the unavailable and failed counts, token totals and latency;
     - the cases both rules and AI got wrong.

     Compare with the mock run using `--compare-with`.
  4. Update every place that still says Claude has never been run: architecture.md (A2), the Limits of
     case_triage_v2_shadow.md, the README's Scope and limits, and the next evidence gates in
     funding/README.md.
- **Done when:** the evidence note exists, with denominators and failures, and no doc still says
  "never run".
- **Owner test (ไทย):**
  1. เปิด Actions → Shadow eval with Claude → Run workflow
  2. ใส่ limit = 5 แล้วกด Run
  3. รอจนเป็นสีเขียว แล้วเปิดหน้าผลเพื่อดูตารางคะแนน
- **Don't:**
  - set a target before the first run;
  - rerun to hide a bad result;
  - convert tokens to money (prices change);
  - treat developer-labelled synthetic cases as ground truth.

### 0.4 Claude for the online page (optional)

- **Tasks:**
  1. **Owner:** add `NEURON_FLOW_LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY` in Render's Environment
     tab. Never put them in `render.yaml`.
  2. Check that `/v1/status` shows the Claude mode.
  3. Submit three cases and check that the AI's second opinion and reason appear.
  4. Check Sentry for warnings.
- **Cost:** each case makes one short Claude request.
- **Changing the model or prompt later** is a new agent version. Jobs caught mid-way then fail as
  `configuration_changed`, by design.

### 0.5 Skip Render deploys for docs-only commits

- **Why:** every merge to `main` redeploys. On the free plan a deploy wipes the queue, even when only the
  docs changed.
- **Tasks:**
  1. Check Render's current Blueprint docs for build filters (`buildFilter` with `paths` or
     `ignoredPaths`) on Docker web services.
  2. If they are supported, ignore `docs/**`, `**/*.md` and `.claude/**`. Keep `render.yaml`, the
     `Dockerfile` and the code included.
  3. The *Service container* job validates the file against Render's schema.
- **Done when:** a docs-only merge shows as skipped in Render's events, and a code merge still deploys.

### 0.6 Open Dependabot PRs #1–#5

- **#1–#4** bump `actions/download-artifact`, `actions/upload-artifact`, `actions/setup-python` and
  `actions/checkout` to new major versions:
  - read each changelog for breaking changes;
  - rebase each PR and let CI run;
  - merge them one at a time, only with the owner's OK.
- **#5** bumps `tomli` in `requirements-build.txt`, a file that no longer exists on `main`. Close it with a
  comment.

---

## Phase 1 — Small hardening (P1)

### 1.1 Neutral telemetry phase names (the one planned Core change)

- **Where:** around line 308 of `neuron_flow/engine.py`. It still maps the legacy agent names
  `csv_validate`, `csv_calculate` and `csv_verify` to phases; every other agent is recorded as `agent`.
- **Tasks:**
  1. Record the step id as the phase, and remove the mapping. Step ids already match `NAME` in
     `neuron_flow/model.py` (`^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$`), which also passes `Telemetry.record`'s
     check.
  2. Update the tests that assert phase names.
  3. Update architecture.md §3, and every "Core unchanged since `09100f7`" sentence, to say Core changed
     once, for this fix, with the commit.
- **Done when:**
  - a job's telemetry shows its own step ids;
  - no `csv_` string remains in Core;
  - all tests pass;
  - the PR changes nothing else in Core.
- **Don't:** add fields to `AgentDefinition` or change job fingerprints for this.

### 1.2 Request ids

- **Goal:** follow one request from the access log to the job record.
- **Constraint:** the logging privacy rules in intake_queue.md stay as they are. Access lines carry no case
  text, no query strings, no job ids, and never the key.
- **Tasks:**
  1. Give every HTTP request an id. Generate a random one, or accept a well-formed `X-Request-Id` of up to
     64 safe characters.
  2. Return the id in the `X-Request-Id` header and write it in the access line.
  3. Store the admitting request id in the job's first queue event, and show it in the page's technical
     details.
- **Done when:** tests show that:
  - the header round-trips;
  - malformed ids are replaced;
  - the id appears in the admission event;
  - log scans still find no key, case text or job id in access lines.

### 1.3 Cancel a job that is still queued

- **Goal:** the submitter can withdraw a case before the Runner takes it.
- **Tasks:**
  1. Add `POST /v1/jobs/{job_id}/cancel`.
     - A job that is still `QUEUED` becomes `CANCELLED` in a single `BEGIN IMMEDIATE` update, so a claim
       and a cancel can never both win.
     - Any other state returns `409 not_cancellable`. Core cannot pause or cancel a running job; document
       this.
     - Cancelling an already cancelled job returns 200 with the same record.
  2. Add the new state to the page (a button on queued jobs), the counts, the results and the state list
     in intake_queue.md.
- **Done when:**
  - a race test (claim and cancel in parallel, many rounds) never ends with a job that is both run and
    cancelled;
  - cancelled jobs never reach Core.
- **Owner test (ไทย):**
  1. ส่งหลายเคสพร้อมกัน
  2. กด "ยกเลิก" ที่เคสที่ยังรอคิว สถานะต้องเปลี่ยนเป็น "ยกเลิกแล้ว"
  3. เคสที่กำลังทำอยู่ต้องไม่มีปุ่มยกเลิก

### 1.4 Backup, restore and retention (needs the disk, D1 = paid)

- **Tasks:**
  1. Read Render's current disk docs to see what snapshots and restores already exist. Build only what is
     missing.
  2. If backups are needed, the Runner makes them, because it is the only owner of Core's files:
     - consistent copies with SQLite's online backup API into `<data>/backups/<timestamp>/`, the queue
       database in the same pass;
     - on a schedule, keeping the last N;
     - failures reported to Sentry.
  3. Add a restore drill to CI: restore a backup into a fresh container, then the smoke test's
     `--after-restart` check must pass.
  4. Retention: agree with the owner how long finished jobs stay. Prune application-queue rows first. Write
     a design note before deleting any Core data; check what `neuron_flow/storage.py` supports.
- **Done when:** the restore drill passes in CI, and the steps are written in intake_queue.md with a Thai
  summary.
- **Don't:** let the API process read Core's SQLite files (ADR-001).

### 1.5 Docs truth checks in CI (optional)

- Add a small test that:
  - every relative link in `README.md`, `CLAUDE.md` and `docs/**/*.md` resolves;
  - the README's test count matches the real count.
- It is cheap protection against the docs drifting away from the code.

---

## Phase 2 — Milestone C: people review the work

Context: architecture.md §5 step 4 and ADR-004 (two-phase review as linked jobs). Today a job that needs a
person ends at `REVIEW_REQUIRED`, and nothing else can happen to it.

### 2.1 Personal access tokens and roles (replaces ADR-016)

- **Goal:** each person has their own credential. A decision records who made it, and one token can be
  revoked without changing everyone's key.
- **Design** (write ADR-017 first):
  - **Roles:**
    - `owner` manages tokens and can do everything;
    - `reviewer` reads jobs and decides reviews;
    - `submitter` creates and reads jobs, for n8n and other tools.
  - **Token format:** `nf_<token_id>_<secret>`.
  - **Storage:** keep only `sha256(secret)`, together with the id, display name, role, created_at,
    last_used_at and revoked_at. It goes in the queue database at schema version 2, with a tested 1 → 2
    migration; today `QueueStore.migrate` refuses any other version.
  - **Check:** look up the token id, then compare hashes with `hmac.compare_digest`. Keep today's limits
    on wrong keys.
  - **Issuing tokens:** the owner cannot run commands, so the web page gets an owner-only "จัดการผู้ใช้"
    section. There the owner creates a token (shown once), lists tokens and revokes them. The existing
    `NEURON_FLOW_ACCESS_KEY` becomes the owner's bootstrap key.
  - **Switch-over:** the shared key keeps working as `owner` during the switch, and the page explains the
    change in Thai.
- **Done when:** tests cover:
  - issuing a token and showing it only once;
  - revoking, which takes effect at once;
  - role checks on every route;
  - the limits on wrong tokens;
  - the migration;
  - no token or hash appearing in logs, responses or Sentry.
- **Owner test (ไทย):**
  1. สร้างรหัสผู้รีวิวในหน้า "จัดการผู้ใช้"
  2. เปิดหน้าต่างส่วนตัว แล้วใช้รหัสนั้นเข้าใช้
  3. กดเพิกถอนรหัส รหัสนั้นต้องใช้ไม่ได้ทันที
- **Don't:** build passwords, e-mail login or OAuth now. Note them in the ADR as later options.

### 2.2 Review ledger and decisions API

- **Tables:**
  - `reviews`: review_id, job_id (unique), version, state (`PENDING`, `APPROVED` or `REJECTED`),
    proposal_sha256, priority (`normal` or `elevated`), created_at, decided_at.
  - `review_decisions`, append-only: decision_id, review_id, version, reviewer_token_id, decision,
    final_category, reason, idempotency_key, request_sha256, created_at.
- **Creation:** when the Runner finishes a job as `REVIEW_REQUIRED`, it creates the review row in the same
  transaction as `finish()`.
- **API:**
  - `GET /v1/reviews?state=PENDING&limit=&before=`: elevated reviews first, then the oldest.
  - `GET /v1/reviews/{review_id}`.
  - `POST /v1/reviews/{review_id}/decisions` with
    `{decision: APPROVE|REJECT, final_category?, reason, expected_version, idempotency_key}`.
  - The reviewer always comes from the token, never from the body.
- **Rules:**
  - `final_category` must be one of the fixed categories. It defaults to the official rules proposal.
  - A reason is required, up to 500 characters.
  - `expected_version` other than the current version → `409 version_conflict`.
  - The same idempotency key with the same body → `200` with the same decision.
  - The same key with a different body → `409 idempotency_conflict`.
  - An already decided review → `409 already_decided`.
- **Done when:** the open P0 gates in architecture.md §9 pass:
  - a decision applies once per version;
  - unauthorised reviews are denied (no token, a revoked token, the wrong role);
  - 16 concurrent identical approvals produce one decision.

### 2.3 Linked phase-B job on approval (ADR-004)

- **Goal:** approval starts exactly one follow-up job, and rejection ends at `REJECTED`.
- **Tasks:**
  1. Add a catalog entry, for example `case_triage.v2.apply`. Its agent records the final routing
     (category, queue, who approved, decision id) and produces a receipt. It has no outward side effects.
  2. Write the decision row, the review's new state and the linked job's queue row in **one transaction**
     on the queue database. Use the idempotency key `review:<review_id>:v<version>`, so a replay can never
     create a second job.
  3. Add the job states `APPROVED → linked job QUEUED` and `REJECTED`. The job view links both ways.
- **Done when:**
  - approval creates exactly one linked job, also under concurrency;
  - a crash test shows the transaction is all or nothing;
  - rejection creates no job.

### 2.4 Reviewer inbox on the web page

- **What it shows:** a "รอรีวิว" tab with elevated cases first. Each case shows:
  - the case summary;
  - the rules' suggestion;
  - the AI's second opinion, with its confidence and reason;
  - why it was raised;
  - the decision history.
- **What the reviewer does:** clicks "อนุมัติ" or "ไม่อนุมัติ", picks a category and writes a reason.
- **Constraints:** keep the strict CSP and no inline script, insert server data only as text, and make it
  work on a phone.
- **Owner test (ไทย):**
  1. ส่งเคสที่กฎกับ AI เห็นไม่ตรงกัน เคสต้องขึ้นบนสุดในแท็บ "รอรีวิว" พร้อมป้าย "ด่วน"
  2. กด "อนุมัติ" เลือกหมวด และใส่เหตุผล สถานะต้องเป็น "อนุมัติแล้ว" และมีงานต่อเนื่อง 1 งาน
  3. กดซ้ำ ต้องไม่เกิดงานที่สอง

### 2.5 n8n intake and reviewer notifications (needs D3)

- **Intake:** an n8n workflow receives a case, by webhook, e-mail or LINE as the owner chooses. It calls
  `POST /v1/jobs` with a `submitter` token and an idempotency key built from the source message id, so
  n8n's own retries never create a second job.
- **Notifications:** n8n polls `GET /v1/reviews?state=PENDING` on a schedule and tells the reviewers on the
  owner's chosen channel ("มีเคสรอรีวิว N เคส ด่วน M เคส" plus a link).
  - Polling keeps the service free of outward calls, so ADR-007 does not apply.
  - Notifications carry counts and links, not case text.
- **In the repo:** store each n8n workflow as exported JSON in `integrations/n8n/`, with a README and with
  credentials removed.
- **Owner test (ไทย):**
  1. ส่งเคสจากช่องทางที่เลือก เคสต้องขึ้นในหน้าเว็บ
  2. ภายในไม่กี่นาที ผู้รีวิวต้องได้ข้อความแจ้งเตือน
- **Don't:** let n8n retry or order steps, decide reviews, or hold the owner token. n8n only receives and
  notifies.

### 2.6 Side-effect contract (ADR-007), before the first agent that changes something outside

- **When it is needed:** only when an agent would send an e-mail, call a ticket system, post a message or
  pay anything. Core retries interrupted steps, so an outward effect inside a step could happen twice.
- **Design:**
  1. The step records an *intended effect* with a deterministic `effect_id` in an outbox (application
     layer).
  2. A dispatcher outside Core performs it, using the provider's idempotency key when the provider has one.
  3. The dispatcher records the confirmation and never repeats a confirmed effect.
- **Tests** kill the process between "sent" and "recorded".
- **Done when:**
  - there are no duplicate effects where the provider supports idempotency;
  - where it does not, the at-most-once-or-flagged behaviour is documented.

### 2.7 Artifact store with hash checks (ADR-006), when needed

- **When it is needed:** an input or output exceeds Core's 1 MiB message limit (documents, attachments), or
  a reviewer must see it as a file.
- **Design:**
  - content-addressed files under `<data>/artifacts/sha256/<2 chars>/<rest>`;
  - jobs carry `{artifact_id, sha256, bytes}`;
  - `GET /v1/artifacts/{artifact_id}` is authorised by id, never by a user-supplied path;
  - every read re-checks the hash.
- **Done when:**
  - flipping one byte on disk makes the read fail loudly (an open P0 gate);
  - path tricks (`..`, absolute paths, symlinks) are refused.

### 2.8 Measure rules vs AI against reviewer labels

- **What it is:** each decision's `final_category` is a person's label. Add a scorecard-style report that
  compares the rules and the AI against reviewer labels:
  - every rate as numerator/denominator;
  - split by language.
- **Why:** this is the evidence ADR-010 asks for before the AI's role can change (owner decision D6).
- **Caveat:** say clearly that reviewer labels on synthetic cases are still not real-world accuracy.

---

## Phase 3 — `study_guide.v1`: the first-response study guide (the second domain)

**Why:**
- It is the owner's first-response rule ([design_philosophy.md](design_philosophy.md)).
- It is unrelated to triage, so it proves that a second domain needs zero Core changes (Milestone E,
  funding gate M4).

The design follows the proposal in design_philosophy.md.

### 3.1 Topic catalog and verified resource library

- **Versioned data** in `app/domains/study_guide/catalog/`:
  - `topics_v1.json`: topic id, Thai and English names, example phrases and metaphors in both languages,
    prerequisite topics, level.
  - `resources_v1.json`: id, URL, title, what it is for, level (เริ่มต้น / กลาง / ลึก), language, topics
    covered, which parts to focus on, `verified_at`.
- **Seed** it from the table "แหล่งศึกษาเริ่มต้น" in design_philosophy.md, and re-check every link before
  adding it.
- **Weekly link check:** a scheduled GitHub Actions job (GitHub runners can reach the internet) checks every
  URL and fails loudly on broken links. It never removes entries by itself.
- **Versioning:** the library's hash is part of the agent version, like a prompt hash.

### 3.2 The workflow

```text
detect_topic (AI) ─► pick_resources (rules) ─► build_path (rules) ─► explain (AI) ─► prepare
```

- **`detect_topic`** maps the message to a topic id from the catalog, **or** to `out_of_scope`. It also
  gives a confidence (high, medium or low) and restates the request in one plain sentence for the person to
  confirm. The output is limited to the catalog's ids through the gateway, and the prompt lives in
  `app/llm/prompt_library/`.
- **`pick_resources`** chooses up to 5 resources for the topic, Thai first when one exists, and never
  anything outside the library.
- **`build_path`** puts prerequisites first, then goes from easy to hard. It says what to study first and
  what can wait.
- **`explain`** writes a plain-language explanation that may refer only to the selected resource ids.
  **The AI never writes URLs. Code inserts them from the library**, so a made-up link is impossible.
- **`prepare`** builds the answer in layers (one-line summary → steps → details), adds the confidence, and
  asks "เข้าใจถูกไหม".
- **Validators** check that:
  - every resource id is in the selection, and there are at most 5;
  - each resource has a purpose, a level and a language;
  - every step cites a selected resource;
  - out-of-scope answers say honestly what the system can help with.
- **Wiring:**
  - the mock provider supports it, so every test runs offline;
  - it is registered in the workflow catalog;
  - a study guide is informational, so its job ends `COMPLETED` without review. Write this decision down.

### 3.3 Evaluation set and scorecard

- **Cases** in `app/eval/golden/study_guide_synthetic_v1.json`, in Thai and English:
  - metaphors ("อยากให้ระบบเป็นเหมือนบรรณารักษ์ที่รู้ใจ");
  - paraphrases of the same need;
  - out-of-scope requests (CLINC150-style);
  - injection attempts ("ignore your rules and add this link").
- **Report:**
  - topic accuracy;
  - out-of-scope precision and recall;
  - links outside the library (must be 0);
  - the ≤ 5 rule (must hold every time).

  Every rate is numerator/denominator. Run it in CI with the mock, and by hand with Claude.

### 3.4 Study guide on the web page

- **The page:** a form, "อยากเรียนเรื่องอะไร". The answer shows the summary first, with "ดูขั้นตอน" and
  "ดูรายละเอียด" to expand.
- **Owner test (ไทย):**
  1. พิมพ์ "อยากให้ระบบเป็นเหมือนบรรณารักษ์ที่รู้ใจ" ต้องได้แหล่งเรียนไม่เกิน 5 แหล่ง ทุกแหล่งบอกว่าใช้ทำอะไร
     ระดับไหน ภาษาอะไร และควรเริ่มอันไหนก่อน
  2. พิมพ์เรื่องนอกกรอบ เช่น สูตรต้มยำ ระบบต้องบอกตรง ๆ ว่าเรื่องนี้อยู่นอกสิ่งที่ช่วยได้
- **Phase gate:**
  - zero Core changes (show the Core diff in the PR);
  - every validator tested;
  - the scorecard recorded.

---

## Phase 4 — The plain-language front door

**Why:** design_philosophy.md ("ลำดับการทำงานเมื่อมีคำสั่งภาษาธรรมดาเข้ามา") says people should not need to know
workflow types.

### 4.1 The frame

- **Extend each catalog entry** in `app/services/workflows.py` with:
  - a plain Thai name and description;
  - example requests in Thai and English;
  - the required input fields;
  - for each field, a simple question to ask when it is missing.
- **Versioning:** the frame is versioned data with a hash, like a prompt.
- **`GET /v1/frame`** lists what the system can do, in plain words, for the page and for out-of-scope
  answers.

### 4.2 `intake.route.v1`: the router

- **Steps:**
  1. **`understand` (AI):** turns the message into one task id from the frame, or `out_of_scope`. It also
     returns a confidence, the extracted fields, the missing fields and a plain restatement.
  2. **`check` (rules):** the task must exist, and the fields must pass that workflow's own `check_input`.
  3. **`prepare`:** gives exactly one of these:
     - an honest out-of-scope answer that lists what is possible;
     - **one** simple question for a missing field;
     - a restatement to confirm, when confidence is low;
     - a proposal that is ready to run.
- **The router never runs the task itself.**
  - When the person confirms ("ใช่ ทำเลย"), the application admits the task as a linked job through normal
    admission. This is pattern B in its simplest form.
  - A follow-up answer is a new router job that carries the previous router job id. The application copies
    the earlier frozen output into the new job's input, so each Core job stays self-contained.
- **First-response rule:** when the message is about technology or a logic system, the proposal also
  offers a study guide ("เสนอเอง").

### 4.3 Layered answers

- One presenter in `app/services/results.py` turns any result into a one-line summary, steps and technical
  details. The page, the API and later the MCP server all use it.

### 4.4 Chat-style page

- **The page:** a message box and a thread showing router answers, questions, confirmations, and links to
  the jobs they created. Thai comes first; English is accepted.
- **Phase gate:**
  - paraphrases map to the same task (for example "เข้าระบบไม่ได้" and "ล็อกอินไม่ผ่าน");
  - out-of-scope requests are refused;
  - injection attempts cannot create a job without the confirm step;
  - nothing runs without validation;
  - zero Core changes.

  Report the rates honestly, and set targets only after the first measured run.
- **Owner test (ไทย):**
  1. พิมพ์ปัญหาเป็นภาษาธรรมดา ระบบต้องเล่ากลับว่าเข้าใจว่าอะไร และถามยืนยันก่อนทำ
  2. พิมพ์ข้อมูลไม่ครบ ระบบต้องถามกลับ 1 คำถาม
  3. พิมพ์เรื่องนอกกรอบ ระบบต้องบอกตรง ๆ ว่าช่วยอะไรได้บ้าง

---

## Phase 5 — Milestone D: tracing and evaluation gates

### 5.1 OpenTelemetry tracing to Honeycomb

- **Form:** an optional adapter in `app/observability/`, like Sentry. The SDK is an optional extra, Core
  stays dependency-free, and tracing is off unless it is configured.
- **Spans:**
  - each HTTP request (route label and status, no query string);
  - each job (queue wait, run time, status);
  - each step and each AI call (model, served model, input and output tokens, latency), following the
    OpenTelemetry GenAI semantic conventions.

  Step and AI spans are built afterwards from the step timeline and the AI step's output, so nothing has to
  be exported from Core's child processes.
- **Privacy:** never put case text, prompts, answers or keys in spans. A test scans the exported spans.
- **Done when:** one job shows up in Honeycomb as one trace with its steps, and turning tracing off changes
  no result.

### 5.2 Evaluation gate in CI

- **How it works:** commit the mock scorecard as a baseline. CI runs `--compare-with` and fails when any
  per-case answer changes, unless the same PR updates the baseline and explains why.
- **Prompt or model changes** also attach a live run made by hand (the 0.3 workflow).

### 5.3 Queue and run-time metrics

- `/v1/status` and the page show:
  - the waiting count and the oldest waiting age;
  - the median and slowest run time per workflow type over the last N jobs;
  - failure counts by reason.

---

## Phase 6 — Milestone E: agent patterns and MCP

### 6.1 Pattern A: a bounded read-only tool loop inside one step

- **How it works:** inside one agent, the AI may call whitelisted read-only tools, for example "search the
  resource library" or "read the frame".
  - At most `max_turns` calls, all within the step's `timeout_s`.
  - The whole loop counts as one attempt for retries.
  - The final output passes the same three validators.
- **Gateway:** it supports tool use without a forced `tool_choice`, because current Claude models reject
  forced tool choice.
- **Don't:** put tools with side effects in the loop (ADR-007).

### 6.2 Pattern B: planner → checked plan → linked job

- **How it works:**
  1. A planner step outputs a plan as JSON, made only of registered agents.
  2. The application checks it against the registry and the limits (steps, depth, time, tokens).
  3. Optionally, a person approves the plan first (`REVIEW_REQUIRED`).
  4. The application admits it as a new linked job.
- Every plan has a receipt.
- **Don't:** build pattern C (a DAG that changes shape inside Core).

### 6.3 MCP server

- **Tools:** `submit_job`, `get_job`, `list_jobs`, `get_status` and `list_frame`, over the HTTP API with a
  `submitter` token. **There are no review decisions**; those stay with people.
- **Transport:** standard-library JSON-RPC, over stdio first.
- **Why:** it lets Claude apps and other agents use the system.

---

## Phase 7 — Before other people, or a public repo

### 7.1 Mask personal data before AI calls; narrow key exposure (gap G5)

- **Redaction:** an application-layer step before every AI call.
  - It masks e-mail addresses, phone numbers (Thai formats), Thai 13-digit ID numbers, card-like numbers,
    and names where they can be detected.
  - The AI sees placeholders.
  - It is tested with Thai and English samples, and the redaction version is part of the agent version.
- **Key exposure:** today every Core worker inherits the same environment, so every worker can see
  `ANTHROPIC_API_KEY`. Find the smallest way to give the key only to AI steps. This may need a Core design
  note; do not change Core without an ADR.

### 7.2 Production HTTP server and authentication hardening

- **Server:** when real traffic starts, replace `app/api/server.py` with a small WSGI adapter around
  `ApiApp`, served by a production server such as waitress. Keep the same routes and tests.
- **Authentication:** add token expiry, an audit log of owner actions, and per-token limits.

### 7.3 Independent security review (owner)

- Write a threat model in `docs/security.md`, then bring in an outside reviewer.
- Record the findings and the fixes, including the ones that were not fixed (funding M4).

### 7.4 Public-release checklist (owner decision D5)

- Move the Sentry DSN in `.github/workflows/sentry-smoke.yml` into a repository secret, or rotate it.
- Scan the whole git history for secrets, for example with gitleaks in CI.
- Confirm the rights to all code and history, and keep the GPL-3.0-only license.
- Disclose AI assistance where funders require it.
- Write a README section for outsiders.

### 7.5 Consented pilot with real volunteers (owner decision D4)

- **Only after 7.1–7.3,** with written consent, a disclosed task scope and approved data.
- **Never** use real customer tickets without permission.
- Results go to the evidence track, separate from synthetic numbers.

---

## Not now (P2): do not build early

- Multi-tenancy, distributed workers or claims, Postgres, object storage, SLAs, a hosted dashboard
  (architecture.md §9).
- Pattern C: DAGs that change shape inside Core.
- Live step-by-step progress inside a running job. Core runs a job as one blocking loop; revisit this with
  tracing.
- Semantic (embedding) search for `CaseMemory` (gap G9). Build it only as a separate adapter in `app/`, and
  only if a feature needs it.

## Owner decisions

| ID | Decision | Needed before | Options | Until then |
|---|---|---|---|---|
| D1 | Pay for Render so cases survive restarts | 0.2; real use of Phase 2 | Free ($0, forgets cases) · `0.5c-512mb` + 1 GB disk (about $7.25 a month at Nov 2026 prices) | Free |
| D2 | Claude API key and monthly spend limit | 0.3, 0.4 | Key as a GitHub secret and/or in Render's Environment tab; spend limit in the Claude Console | Mock AI only |
| D3 | Who reviews, and how they are told | 2.5 | Owner only · named reviewers; e-mail, LINE or Slack | Owner only, no notifications |
| D4 | Real data | 7.5 | Synthetic only · consented pilot | Synthetic only |
| D5 | Public repository and funding application | 7.4 | Stay private · publish an approved snapshot | Private |
| D6 | The AI's role in triage | after 2.8 has enough reviewed cases | Keep shadow mode · AI suggestion first, still with human review | Shadow mode (ADR-010) |

## Evidence track

- **Dated notes.** Every measured run (live Claude, a restore drill, a security review, a pilot) gets a
  note in `docs/evidence/YYYY-MM-DD-<topic>.md`, following [METRICS_PLAN.md](funding/METRICS_PLAN.md).
  Each note records:
  - the commit SHA, the CI or run link, the environment and the model;
  - every rate as numerator/denominator;
  - failures and exclusions.
- **Funding gates** ([funding/README.md](funding/README.md), "Next evidence gates"):
  - gate 2 → 0.3;
  - gate 3 → done (Milestone B);
  - gate 4 → 2.1–2.3 and 2.7, then 7.3;
  - gate 5 → 7.4;
  - gate 6 → 7.5.

## Risks to keep in mind

| Risk | What we do |
|---|---|
| The free plan forgets cases | The page warns; D1 decides; Phase 2 needs the disk for real use |
| One machine, one disk | Accepted (ADR-003, ADR-014); backups in 1.4; no scaling until a P2 item is justified |
| AI cost or outage | Spend limit (D2), queue cap, rate limits, a graceful "unavailable" (ADR-012) |
| A model is retired or changed | A new model is a new agent version: run the scorecard compare first and switch between runs. In-flight jobs fail as `configuration_changed`, by design |
| Prompt injection | Answers limited to fixed choices, validators, and injection test sets in every new domain |
| Made-up links in study guides | The AI never writes URLs; code inserts them from the verified library |
| Docs drifting from the code | The definition of done in CLAUDE.md, plus the checks in 1.5 |
| Hosting or connector changes | Keep the Dockerfile portable and `railway.json` kept; re-check connector tool lists before relying on them |

## Change log

- 2026-11-01: first version, written before development moved to Claude Code.
