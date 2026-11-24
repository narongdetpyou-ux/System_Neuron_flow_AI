# The plain-language router: `intake.route.v1` (roadmap 4.2, ADR-039)

## ภาพรวมสำหรับเจ้าของโปรเจกต์

**ตัวอ่านข้อความ** รับข้อความภาษาธรรมดา ภาษาไทยหรืออังกฤษ แล้วตอบได้ 1 ใน 5 แบบ:

| แบบ | เมื่อไร | ระบบพูดว่าอะไร |
|---|---|---|
| เสนองาน | เข้าใจว่าต้องการงานไหนในสมุดงาน และข้อมูลพอ | เล่ากลับว่าเข้าใจอะไร แล้วถาม "เข้าใจถูกไหม" |
| เล่ากลับให้ยืนยัน | AI ไม่ค่อยมั่นใจ | เล่ากลับแล้วถาม "เข้าใจถูกไหม" เหมือนกัน |
| ถามกลับ 1 คำถาม | รู้ว่าเป็นงานไหน แต่ข้อมูลยังไม่พอ | คำถามจากสมุดงาน เช่น "ลูกค้าแจ้งปัญหาอะไรเข้ามา…" |
| นอกกรอบ | ไม่ตรงกับงานไหนเลย | บอกตรง ๆ แล้วบอกว่าช่วยอะไรได้บ้าง พร้อมตัวอย่าง |
| ยังอ่านไม่ได้ | AI ไม่ตอบ (เช่น ระบบ AI ขัดข้อง) | ให้เลือกงานจากรายการเอง |

**สิ่งที่ตัวอ่านข้อความไม่ทำ:**
- ไม่สร้างงานเอง ต้องมีคนกด "ใช่ ทำเลย" ก่อน ซึ่งเป็นขั้น 4.2 ส่วนที่สอง ยังไม่ได้ทำ
- AI ไม่เขียนข้อความของคุณใหม่ งานที่เสนอใช้คำของคุณเองทุกตัวอักษร
- ไม่ตัดสินอะไรแทนใคร

**ตอนนี้ดูได้ที่ไหน:** ยังไม่มีบนหน้าเว็บ (หน้าแชทคือขั้น 4.4) ดูได้ที่ GitHub
- *Actions → Core logic tests → Summary*: หัวข้อ "ตัวอ่านข้อความ: ตัวอย่างคำตอบ" มีข้อความตัวอย่าง 5 ข้อพร้อมคำตอบ
- หัวข้อ "ผลวัดตัวอ่านข้อความ" ในหน้าเดียวกัน คือผลของ AI จำลองกับชุดข้อสอบ ไม่ใช่ความแม่นยำ
- ผลวัดกับ AI จริง (Typhoon) อยู่ใน[บันทึกหลักฐาน](evidence/2026-11-24-intake-router-typhoon.md)

## The workflow

```text
understand (AI) ─► check (rules) ─► respond (rules)
      └───────────────────────────────┘ (respond reads both)
```

- **The input:** `{"message": "..."}`, 4–500 characters after trimming, counted the way a reader sees them (invisible
  format characters do not count), with at least one letter, digit or sign, and no characters that change the
  direction of the text. It is admitted like any workflow type: `POST /v1/jobs` with
  `"workflow_type": "intake.route.v1"`.
- **`understand`** (agent `route.understand`):
  - masks personal data (`redact-v3`), then asks the AI, through the gateway, which task of the frame the message asks
    for, or `out_of_scope`;
  - the prompt is `app/llm/prompt_library/intake_understand_v1.json`, completed from the frame (ADR-019): one line per
    task (its names, what it does, what it needs, its examples), and `task` is limited to the frame's ids;
  - the answer also carries `confidence` (low, medium, high), `language` (th, en), `needs_more` (yes when the message
    says too little), `also_study` (yes when study resources could help, the first-response rule) and a one-sentence
    `restatement`;
  - like the study guide, a hiccup or an off-contract answer is retried once; then the step answers `unavailable`
    (ADR-012).
- **`check`** (agent `route.check`, rules):
  - the task must be one of the frame's;
  - the person's message must give the task's one field: its length, from the frame, whose limits were probed against
    the task's own input check (ADR-038);
  - the AI's `needs_more` can only add a question, never skip a check.
- **`respond`** (agent `route.respond`, rules): exactly one `kind`, in the person's language:
  - `proposal`: the task, its workflow type, the restatement, "เข้าใจถูกไหม", and `input`, which is **the person's own
    message** copied by code into the task's field. `system_fields` names the fields the application fills when a
    person confirms (a case's id).
  - `confirm`: the same, when the AI said `low`.
  - `question`: the frame's one question for the missing field.
  - `out_of_scope`: the frame's honest sentence (`intro`) and every task with one example (`can_help_with`).
  - `not_understood`: the AI gave no answer; the same list, so the person can still choose.
  - With `also_study`, a proposal for another task also offers the study guide in `also`. It is an offer, never a
    replacement.

The router decides nothing and runs nothing (ADR-018): it ends `COMPLETED`, no answer carries a `decision`, and its
domain (`app/domains/intake/`) imports no admission, queue or services code; `tests/test_intake_route.py` reads the
imports to make sure.

**What is frozen into each job (ADR-015):**
- every step carries the frame (the view `app.services.frame.Frame.view` hands over, as plain data, so the domain
  never imports the services layer) and its tag;
- every agent version names the tag, so a changed frame is a new version;
- the AI step also carries the AI settings, the prompt's SHA-256 and the masking rules.

**The mock** (`app/domains/intake/mock_answers.py`) is a keyword simulation: the triage simulation's word lists for a
case, a short list of "want to learn" phrases for the study guide, and `needs_more` for a matched message under 15
visible characters. It cannot read a paraphrase or a metaphor whose words it does not list, and it never offers the
study guide. Its restatements start with "[จำลอง]" or "[simulated]".

## Measuring it

Two message sets, written by the developer before the prompt's wording and never copied from the frame's examples or
another exam set (a test checks):
- `app/eval/golden/intake_route_v1.json`: 60 messages, the development set. It covers cases, paraphrases (Phase 4's
  gate pair "เข้าระบบไม่ได้" and "ล็อกอินไม่ผ่าน" among them), wishes to learn, metaphors, out-of-scope requests,
  messages that say too little and injection attempts.
- `intake_route_heldout_v1.json`: 30 messages, never used to choose wording.

`expected.needs_more` is `null` where either answer is fair. The training set's overlap check
(`training/check_set.py`) covers both sets.

`python -m app.eval.intake_route_eval` runs a set through the real workflow and reports:
- the task right;
- out of scope (precision, recall, in-scope messages turned away);
- one question when needed, and needless questions;
- the kinds of answer, the study offers, injections, tokens and latency.

It fails (exit 1) when a promise breaks: a job that does not end, or a proposal whose input is not the person's own
message. With `--compare-with` it is an eval gate (exit 3 on any changed answer). CI runs both sets with the mock
against `tests/baselines/intake_route_mock.json` and `intake_route_heldout_mock.json`, and shows the demo
(`examples/intake_route_demo.py`) on the run page.

**A live run** goes from a cloud session, whose proxy adds Typhoon's key (synthetic data only):

```bash
TYPHOON_API_KEY=proxy-injected NEURON_FLOW_LLM_PROVIDER=typhoon \
  python -m app.eval.intake_route_eval --min-interval-s 1 --out intake-route-v1-typhoon.json
```

The first run, on 2026-11-24 ([evidence](evidence/2026-11-24-intake-router-typhoon.md)):

| Set | Task right | Right over every message | Proposals in the person's own words |
|---|---|---|---|
| Development | 47/48 | 58/60 | 43/43 |
| Held out | 22/22 | 30/30 | 19/19 |

The two misses were a request for a secret (proposed as a case) and a wish to learn about sign-in design (proposed as
a case). Typhoon said `high` on 57 of 60 development messages, so the `confirm` kind never appeared, and it never
offered the study guide. These figures describe Typhoon only, on developer-written text.

## What comes next (roadmap Phase 4)

1. **Confirm and reply** (4.2's second part):
   - `POST /v1/jobs/{router_job_id}/confirm` admits the proposal through normal admission, with the key
     `confirm:<router job>` and a link row;
   - `POST /v1/jobs/{router_job_id}/reply` makes a new router job carrying the earlier answer, copied by the API from
     the store.
2. **Layered answers** (4.3): one presenter for every result.
3. **The chat page** (4.4):
   - every message goes to the router;
   - the case / study switch stays as a fallback while the page runs the mock;
   - Phase 4's gate is measured again.

## Tests

`tests/test_intake_route.py`:
- the contract and the frame it needs;
- the prompt completed from the frame, and a new frame is a new version;
- every kind end to end with the mock, the study offer, an injected instruction, and masking before the AI;
- the validators refuse an unknown task, a reply that differs from the rules and a proposal not in the person's words;
- the domain imports no admission code, and through the API a router job completes and creates nothing else;
- both message sets load and are new phrases, and the gate notices a changed answer.

Also:
- `tests/test_web_page.py` keeps a Thai name for each of the router's steps;
- the *Service container* smoke test sends a message to the router on the real image.
