# The quality report of 2026-11-19: every point checked, three fixed, the rest planned

## สรุปสำหรับเจ้าของโปรเจกต์

คุณส่งรายงานประเมินคุณภาพโครงการ (7 หน้า ตรวจที่ `main` commit `3a4b97f`) มาให้อ่านทีละข้อและวางแผนเริ่มงาน
ผมตรวจทุกข้อกับโค้ดจริงและรันซ้ำ: **ทุกข้อตรงกับที่รายงานบอก** ผลคือ

| หน้า | รายงานบอกว่า | ตรวจแล้ว | ทำอะไร | เหลืออะไร |
|---|---|---|---|---|
| 1–2 | ระบบเป็นต้นแบบที่ทดสอบซ้ำได้ ทดสอบผ่านครบ | ตรง | ไม่ต้องแก้ (การทดสอบเพิ่มเป็น 571 ข้อ) | — |
| 3 | กฎถูก 22/40 ในชุดที่กันไว้ เช่น "ลากไฟล์มาวางแล้วไม่มีอะไรเกิดขึ้น" ได้ "อื่น ๆ" | ตรง (วัดใหม่ได้เท่าเดิม) | ไม่เพิ่มคำในกฎจากชุดที่กันไว้ (กติกาโปรเจกต์ ข้อ 5) | ทางแก้คือ E5 หรือใช้ AI จริงบนหน้าเว็บ (คุณเลือก) |
| 4 | ป้าย "บันทึกถาวร" ดูแค่การตั้งค่า และ `/healthz` บอก "ปกติ" แม้ตัวรันงานติด | ตรง (ลองซ้ำบนเครื่องแล้วเห็นเหมือนกัน) | วางแผนเป็นขั้น 1.7 (งานถัดไป) | ดิสก์ถาวรเป็นการตัดสินใจของคุณ (D1) |
| 5 ข้อ 1 | แก้วิธีอ่านคำตอบ AI แต่รหัสรุ่นไม่เปลี่ยน | ตรง และเคยเกิดแล้ว 2 ครั้ง (PR #42, #74) | **แก้แล้ว:** รุ่นของ AI รวมรุ่นของด่านตรวจคำตอบ มีการทดสอบล็อกพฤติกรรมไว้ | — |
| 5 ข้อ 2 | ตารางคะแนนรวมผลของการตั้งค่า AI ต่างกัน | ตรง | **แก้แล้ว:** ทุกเคสเก็บรุ่น AI แบบครบ ตารางแยกตามรุ่น เคสเก่าแสดง "ไม่ทราบรุ่น" | ให้คนเลือกหมวดก่อนเห็นข้อเสนอ (2.9) รอคุณเห็นชอบ |
| 5 ข้อ 3 | ใส่ ฿ แล้วประโยคอังกฤษถูกนับเป็นไทย | ตรง | **แก้แล้ว:** นับเป็นเคสไทยเมื่อมีตัวอักษรไทยจริง | — |
| 6 | ข้อมูลส่วนตัว ความเร็วเมื่อมีหลายเคส การทดสอบหน้าเว็บด้วยการกดจริง | ตรง | วางแผน (7.5, 5.7, 1.8, 7.2) | ข้อมูลจริงต้องรอคุณ (D4) |
| 7 | ลำดับงานก่อนทดลองใช้จริง 5 ข้อ | — | จับคู่กับขั้นใน ROADMAP ครบ (ตารางท้ายบันทึกนี้) | — |

ทั้ง 3 ข้อที่แก้อยู่ใน pull request เดียว ไม่เปลี่ยนคำตอบของเคสใดในชุดข้อสอบ (ด่านตรวจผลรายเคสผ่านเหมือนเดิมทุกด่าน)

## The report

- **Read on:** `main` @ `3a4b97f` (2026-11-19), seven pages in Thai: an overall rating ("Working Prototype ที่ทดสอบซ้ำได้"),
  the architecture and its reproduced results, the rules' and the AI's effectiveness, operational readiness, three
  findings from reading the code and running it, data protection and maintenance, and a work order with acceptance
  evidence. Its own scope: the source, local runs and the CI of that commit; it called no external model, did not
  check the Render account and did not try a phone; real-model and Render figures cite the project's dated notes.
- **Shared by:** the owner, on 2026-11-19, with the request to read it point by point and plan the start of work.
- **Answered on:** the branch `claude/vigilant-goodall-1ezoxz`, one pull request: the three code findings fixed, every
  other point checked and planned. Checked in this session on Python 3.13.18, 3.10.20 and 3.12.3, mock AI only.

## Pages 1–2: the overall rating and the reproduced results

Agreed; nothing to fix. The report re-ran the main suite (561/561), the handoff check over 217 cases (174 approvals →
174 apply jobs with receipts, 43 rejections → none, a repeated click adds nothing) and a stop and restart over the
same folder. With this pull request the suite has 571 tests.

## Page 3: how well the rules and the AI classify

**Checked.** The rules re-run at this commit give the report's figures: 61/61 on the development set (Thai cases
26/26), 105/116 on the edge set (13/13) and 22/40 on the held-out set (10/20). The Thai example is `HO-TH-UPL-05`
of the held-out set; the rules answer `other`. The Typhoon columns, the attention costs (12/32 → 32/32 raised, 234 →
379 of 1,320 to look at first, 1,157 → 1,147 of 1,513 categories right) and the study-guide figures (mock 2/48, the
local 4B 44/48 and 58/61) match the dated notes they come from.

**Not done, on purpose.** The held-out set exists to measure, so no keyword is added because of its result (rule 5,
and the E2 note); fixing `HO-TH-UPL-05` with a keyword would make the set's next result meaningless. The ways forward
are already planned: E5 (the edge of `other`, with about 20 borderline requests the owner labels), a real model behind
the page (E3, roadmap 0.4, the owner's choice) and new development cases written apart from the held-out set.

**Planned.** The report asks to measure the reviewer's time beside the cases a flag catches: roadmap 2.10.

## Page 4: data after a restart, and the Runner's status

**Checked, and reproduced on a local service at this branch** (`python -m app.serve`, Typhoon chosen and no key,
`NEURON_FLOW_DATA_DIR` set to a scratch folder that is not a mount point):

```text
healthz: {"ok":true,"access_key":"configured"} HTTP 200
runner: {'state': 'blocked_config', 'alive': True}
storage: {'kind': 'configured', 'persistent': True}
retention: {'persistent': True, 'lost_on': []}
```

- **Storage.** `Settings.persistent` is `storage != "local_default"`: any `NEURON_FLOW_DATA_DIR` counts as persistent,
  so a wrong path or a disk that is not attached would make the page say "บันทึกถาวรแล้ว" while a deploy still
  empties the queue. On the free plan today the variable is not set and the page correctly says "ชั่วคราว"; the risk
  is the day D1 is switched on.
- **Readiness.** `/healthz` checks only that the queue database answers, by design, because Render restarts a service
  whose health check fails and, on the free plan, a restart empties the queue. Nothing else tells a watcher that the
  Runner cannot work.

**Planned next: roadmap 1.7.** `persistent` only when the folder is confirmed on its own mounted filesystem (not the
container's root, `overlay`, `tmpfs` or `ramfs`); `GET /readyz` beside `/healthz` (503 with a state code while the
Runner is blocked, not alive or starting; cases are still admitted); a Sentry event when the Runner is blocked; the
container smoke test covering a volume, a plain folder and a blocked Runner that recovers with the queue intact.
The disk itself and the restore drill stay with D1 and roadmap 1.4, which gains the report's acceptance: cases,
decisions, Core receipts and token states read back after a deploy and after a restore into new storage.

## Page 5: three findings from the code, fixed

### Finding 1: the way AI answers are read changed and kept its version

**Checked.** An AI agent's version (`LLMConfig.version_tag`) named the provider, model, prompt hash, `max_tokens`,
effort, masking rules and answer format, but not the gateway's answer checks (`gateway.parse_answer` and the stop
reasons `structured_answer` refuses). PR #74 changed those checks (invisible format characters removed, a free-text
field left empty refused) and PR #42 had changed them before (lone surrogates turned into U+FFFD); neither changed a
version, so Core's check that an interrupted job resumes under the agents it started with (ADR-005, ADR-015) could
not see the change.

**Reproduced.** A `case_triage.v2` job accepted by Core, interrupted, then resumed by a Runner whose checks have
another version (only the checks; same model, prompt and budget):

| Agent version | Outcome of the resumed job |
|---|---|
| without the checks (`main` @ `3a4b97f`) | `REVIEW_REQUIRED`: finished silently under the other checks |
| with the checks (this pull request) | `FAILED`, `configuration_changed` |

**Fixed (ADR-035).**
- `config.ANSWER_CHECKS_VERSION = "answer-checks-v3"`, added to every AI agent's version as `;checks=answer-checks-v3`.
  The history is named so it reads in order: v1 until 2026-11-07, v2 from PR #42, v3 from PR #74. Results from before
  this pull request cannot tell which applied.
- `tests/test_answer_checks_version.py` runs `parse_answer` over 31 fixed replies (control characters, separators,
  half an emoji, bidi controls, zero-width characters, text with only invisible characters, marks or spaces, Thai with
  ฿, a reply over 200 characters, wrong choices, missing or extra fields, non-text values, not JSON, a list, two
  objects, a repeated key, NaN, a byte order mark, a code fence, no text) and the gateway over 7 stop reasons, and
  hashes the outcomes (the cleaned fields or the error class) with the text limit and the cut-off reasons. The hash of
  v3 is pinned: `9a2ff957…`. The checks as they were before PR #74 give `1f4eba42…`, so this test would have stopped
  PR #74 until it named a new version. The hash is the same on Python 3.10, 3.12 and 3.13.
- `tests/test_service_runner.py` gained the reproduction above as a test.

**Effects.** Every AI agent's version changes once with this deploy, so a job caught mid-way by it fails as
`configuration_changed` (on the free plan the deploy empties the queue anyway). The study guide's two AI agents use
the same gateway, so their versions change too; no file in `app/domains/study_guide/` changes (the study guide is
paused). No answer changes: every eval gate and the robustness gate are as before.

### Finding 2: the scorecard added up results of different AI settings

**Checked.** The reviewer-label scorecard (roadmap 2.8) grouped by workflow, rules, and the AI's provider, model and
prompt hash; the same mock with `max_tokens` 256 and 2,048 therefore made one group with two labels, while Core held
two versions.

**Fixed.**
- The Runner records the AI step's version as Core checked it with each result (`result.ai.agent_version`, read from
  Core's copy of the spec, as the trace already did).
- The scorecard groups by that version; a group's `ai` gains `agent_version` and `version_known`. A result recorded
  before this has no version: it is its own group, `version_known: false`, shown as "ไม่ทราบรุ่น", never added to a
  known version (the report's recommendation for old history).
- The page shows each group's version (the parts the AI and prompt rows do not already say, such as `max_tokens=2048
  · effort=default · redaction=redact-v2 · checks=answer-checks-v3`), and the same in a case's technical details.
- Scorecard reports record it as `provenance.agent_version`, and the run page shows it.
- Tests: the report's experiment end to end (two cases through the Runner with `max_tokens` 256 and 2,048, decided
  over the API: two groups), two budgets or two versions of the checks written directly (three groups), and a result
  without a version (its own group).

**Unchanged, and said on the page as before:** the scorecard reads the newest 500 decided cases, and the person saw
the proposal before deciding, so its "match" is agreement with a person who was shown the proposal, not accuracy.
Labels given before the proposal is seen are roadmap 2.9, which waits for the owner's go-ahead because it changes how
a reviewer works.

### Finding 3: the baht sign made an English sentence a Thai case

**Checked.** `review_labels.language_of` matched the whole Thai block (U+0E00–U+0E7F), which holds the baht sign
(U+0E3F), Thai digits and tone marks as well as letters: "I was charged 500 twice" was `non_th`, "I was charged ฿500
twice" was `th`, and so were Thai digits or tone marks alone.

**Fixed.** A case is `th` when it holds a Thai letter, as the docs already said: Unicode categories Lo and Lm in the
Thai block (a test compares the pattern with that set, character by character). Tests: "I was charged ฿500 twice" and
"Refund ฿1,250 to the card ending ๑๒๓๔" are `non_th`; "I was charged ฿500 twice ค่ะ" and "โดนหัก ฿500 สองครั้ง" are
`th`. The robustness benchmark's own helper, which sets the language of the exported edge cases, now uses the same
rule.

**No committed result changes.** Over every golden file and the robustness sets, no case text changes language; the
exported edge set (`tests/robustness/triage_edge_golden_v1.json`) comes out byte for byte the same, and the robustness
gate gives 246/270, 0 bugs, 13 gaps and 11 notes, as before. The golden sets carry their own language labels, so
their per-language scores never used this rule.

## Page 6: data protection, speed and maintenance

- **Personal data and who sees what.** Agreed. The gateway masks known patterns before any AI call (ADR-028); the
  queue database keeps the case text and reviewers' reasons; the robustness gate lists 10 open masking gaps; and today
  every token may read every case (`GET /v1/jobs` is open to the three roles), which suits one team sharing one queue.
  Planned under 7.5, before the first real case and with the owner's decisions (D4): the kinds of data the pilot will
  receive with synthetic examples of each in the masking tests, a submitter that reads only its own cases, and a
  retention period with a tested deletion. Several organisations on one service is multi-tenancy, a P2 item: not
  planned.
- **Throughput and speed.** Agreed: one Runner, one case at a time (ADR-001, ADR-003); 3.158 s is one observation of
  the first case after a free-plan sleep, with the mock, excluding the page's own wake-up (the E1 note). Planned under
  5.7: several cases at once at a target volume, with the 95th percentile of the queue wait and of send-to-result,
  the backlog and the failures; the target volume is the owner's to give.
- **Maintenance.** Agreed: `app/web/app.js` had 3,178 lines at the reviewed commit (3,195 with this pull request) and
  `app/persistence/queue_store.py` 824, and most page tests read the source. Planned: 1.8, a browser walk in CI on a
  phone-sized screen (send a case, decide it). No split of the files is planned before a walk guards the behaviour.
- **Before a public service.** Agreed: roadmap 7.2 (a production HTTP server) gains measurable service targets.

## Page 7: the report's work order, mapped to the roadmap

| Before … | The report asks | Roadmap | Status | Needs |
|---|---|---|---|---|
| keeping data across days | a disk on the data folder, retention, restoring the queue with Core | 1.4 (its acceptance added), 1.7 task 1 | ⬜ | D1 for the disk |
| leaving the queue to run | the Runner's readiness apart from the API's liveness | 1.7 | ⬜ planned next | — |
| using real data | who sees which case, how long data stays, masking per kind of data | 7.5 (its list added), 7.1 | ⬜ | D4 and the kinds of data |
| using scores to choose an AI | whole versions, the language split, labels before the proposal | ADR-035 and 2.8's fix; 2.9 | ✅ here; 2.9 ⬜ | 2.9: the owner's go-ahead, D1 |
| adding users | a queue at the target volume, reviewer time | 5.7, 2.10 | ⬜ | the target volume; D3, D1 |

## How to re-check

```bash
python -m unittest discover -s tests -v                    # 571 tests
python -m unittest tests.test_answer_checks_version -v     # the checks' version and its pin
python -m unittest tests.test_service_review_labels -v     # the scorecard's groups and language split
python -m tests.handoff_check                              # the report's second command
python -m tests.robustness.bench --compare-with tests/baselines/robustness_v1.json
```

## Limits of this response

- Everything here ran with the mock AI: no live model was called, and none is needed, because no prompt, model or
  answer changed (only the name of the checks' version).
- The pin covers 31 fixed replies; a change to the checks that none of them reaches still depends on the developer
  naming a new version.
- Page 4's findings are planned, not fixed, in this pull request (roadmap 1.7, one topic per pull request).
