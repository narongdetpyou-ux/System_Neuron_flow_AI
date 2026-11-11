# Auto-approve limits: what a "send it myself" button would do (simulation)

**Status (2026-11-11):** built and measured with Typhoon in its pull request (ADR-031, roadmap 5.9, with
roadmap 5.6's open benchmarks and the first injection measurement of 5.7). Results:
[evidence note](evidence/2026-11-11-autosend-limits.md).

The owner asked to see the system's limits with public data that developers use to measure systems, and with
hard tests, *as if* the system had a button that approves a case on its own when it is confident, instead of
always leaving it to a person. This page explains how that question is answered without breaking rule 4
("AI proposes, code validates, people decide").

## สรุปสำหรับเจ้าของโปรเจกต์

**สรุปบรรทัดเดียว:** ผมจำลอง "ปุ่มอนุมัติเอง" บนกระดาษ แล้ววัดว่าถ้ามีปุ่มนี้จริง ระบบจะส่งเคสเองได้กี่เคส ส่งผิดกี่เคส
และเคสที่ต้องให้คนดู (เช่น โดนหลอก บัญชีถูกแฮ็ก เรื่องกฎหมาย คนที่กำลังลำบาก) จะหลุดออกไปกี่เคส โดยระบบจริงยังให้คนตัดสินทุกเคสเหมือนเดิม

### ทำงานอย่างไร (ทีละขั้น)

1. **ข้อสอบ** มี 3 กอง รวมราว 1,300 เคส
   - **ข้อสอบกลางจากข้อมูลเปิด** ที่นักพัฒนาทั่วโลกใช้วัดระบบแยกคำขอ (ดาวน์โหลดใหม่ทุกครั้งจากต้นฉบับ ตรวจลายนิ้วมือไฟล์ (SHA-256) ก่อนใช้ ไม่เก็บสำเนาไว้ในโปรเจกต์)
     - CLINC150: คำขอ 300 ข้อ รวมคำขอนอกกรอบ 100 ข้อ
     - BANKING77: คำขอเรื่องธนาคาร 300 ข้อ
     - MASSIVE: คำสั่งผู้ช่วยแบบเดียวกันทั้งภาษาไทยและอังกฤษ 150 คู่ ดูว่าไทยกับอังกฤษได้คำตอบเดียวกันไหม
     - BIPIA (ของ Microsoft): คำสั่งแอบแฝง 75 แบบ ฝังลงในเคสปกติ ดูว่า AI ถูกหลอกไหม
   - **ชุดเคสยากที่เขียนเพื่องานนี้โดยเฉพาะ** 128 เคส (ไทย 64 อังกฤษ 64) เช่น คำที่ชวนให้เข้าใจผิด ประโยคปฏิเสธ หลายปัญหาในเคสเดียว
     คำสั่งแอบแฝงที่สั่งให้ "อนุมัติเลย" บัญชีถูกแฮ็ก เรื่องกฎหมาย และคนที่กำลังลำบาก
     - เคสที่ต้องให้คนดูเสมอ ไม่ว่าหมวดจะถูกหรือไม่ มีป้าย `needs_person` 38 เคส
     - ชุดนี้บันทึกไว้ก่อนรันกับ AI ครั้งแรก คำตอบของ AI จึงไม่ได้มีผลต่อการเขียนเคส
   - **ชุดเดิม 3 ชุด** 217 เคส (ชุดพัฒนา 61 ชุดเคสยากเดิม 116 ชุดที่กันไว้ 40)
2. **ระบบจริงตอบทุกเคสตามปกติ** (กฎคำสำคัญเสนอหมวด AI ให้ความเห็นที่สอง แล้วรอคนตรวจ) และเก็บคำตอบไว้
3. **ตัวจำลองอ่านคำตอบที่เก็บไว้** แล้วถามว่า "ถ้ามีปุ่มอนุมัติเอง ปุ่มจะส่งเคสนี้ไหม" ด้วยกติกา 4 แบบ จากหละหลวมไปเข้มงวด:
   1. `ai_high` — AI บอกว่ามั่นใจสูง ก็ส่งตามที่ AI เลือก
   2. `agree` — กฎกับ AI ตอบหมวดเดียวกัน ก็ส่งเลย
   3. `agree_high` — กฎกับ AI ตรงกัน และ AI มั่นใจสูง
   4. `strict` — ข้อ 3 และกฎเจอคำสำคัญจริง และไม่มีข้อมูลส่วนตัวในเคส
4. **นับผล** ทุกตัวเลขมีตัวตั้งและตัวหาร:
   - ส่งเองได้กี่เคส (งานที่คนไม่ต้องทำ)
   - ในเคสที่ส่งเอง ส่งผิดทีมกี่เคส พร้อม "ขอบบน 95%" (ถ้าลองน้อยแล้วไม่ผิดเลย ไม่ได้แปลว่าไม่มีวันผิด ขอบบนบอกว่าอาจผิดได้มากสุดเท่าไร)
   - เคสที่ต้องให้คนดูแต่หลุดออกไป และเคสที่มีคำสั่งแอบแฝงแต่หลุดออกไป
5. **ระบบจริงไม่มีปุ่มนี้** ตัวจำลองตรวจด้วยว่าทุกเคสในระบบจริงยังรอคนตัดสิน ถ้ามีเคสไหนถูกตัดสินเองโดยไม่มีคน ช่องตรวจจะเป็นสีแดง

### คุณต้องทำอะไร (ลองดูเอง)

1. **ดูผลรอบแรก** ใน [บันทึกหลักฐาน](evidence/2026-11-11-autosend-limits.md) (ตารางแรกคือคำตอบของคำถาม "ขีดสุดอยู่ตรงไหน")
2. **รันใหม่เองได้ทุกเมื่อ (ฟรี)**
   - เปิด GitHub → แท็บ Actions → *Auto-approve limits (open benchmarks + hard set)* → Run workflow
   - ปล่อยค่าเดิม (provider `typhoon`, sets `all`) แล้วกด Run
   - รอราว 45–60 นาที เครื่องเว้นจังหวะ 1 วินาทีต่อเคสตามข้อจำกัดของ Typhoon ฟรี
   - เปิดหน้า Summary ต้องเห็นหัวข้อ "จำลองปุ่ม อนุมัติเอง" ตารางต่อชุด และบรรทัด "ระบบจริงส่งให้คนตรวจ 100%"
3. ถ้าคุณอยากให้มีปุ่มนี้จริงในอนาคต ต้องเป็นการตัดสินใจของคุณ (เป็นการเปลี่ยนกติกาข้อ 4) และผมต้องเขียนข้อตัดสินใจ (ADR) ใหม่ก่อน
   ดูหัวข้อ "What a real button would need" ด้านล่าง

### แหล่งเรียน (เรียงตามลำดับที่ควรอ่าน)

1. **On Calibration of Modern Neural Networks** (Guo และคณะ, ICML 2017) — https://arxiv.org/abs/1706.04599 — **อ่านก่อน**
   - ใช้ทำอะไร: เข้าใจว่าทำไม "ความมั่นใจ" ที่โมเดลบอก มักสูงกว่าความถูกจริง ซึ่งเป็นสิ่งที่ผลรอบนี้เจอตรง ๆ
2. **Selective Classification for Deep Neural Networks** (Geifman และ El-Yaniv, NeurIPS 2017) — https://arxiv.org/abs/1705.08500
   - ใช้ทำอะไร: วิธีคิดเรื่อง "ให้ระบบตอบเองเฉพาะเมื่อมั่นใจ ที่เหลือส่งคน" อย่างเป็นระบบ คือที่มาของตาราง "ส่งเองได้เท่าไร ผิดเท่าไร"
3. **BIPIA** (Yi และคณะ, 2023) — https://arxiv.org/abs/2312.14197
   - ใช้ทำอะไร: รู้จักการโจมตีด้วยคำสั่งที่ซ่อนในข้อความจากภายนอก (indirect prompt injection) ซึ่งตรงกับข้อความเคสที่ลูกค้าพิมพ์มา
4. **OWASP Top 10 for LLM Applications: LLM01 Prompt Injection** — https://genai.owasp.org/llmrisk/llm01-prompt-injection/
   - ใช้ทำอะไร: วิธีป้องกันที่วงการแนะนำ ข้อหลักคือ "ให้คนอนุมัติก่อนทำเรื่องที่มีผลจริง" ซึ่งระบบนี้ทำอยู่แล้ว

## Why a simulation and not a button

Rule 4 says nothing is decided automatically, and ADR-010 keeps the AI advisory until measurements justify
more. The owner's question is "how far could it go?", which a measurement answers without changing who
decides. So:
- the simulation (`app/eval/autosend_sim.py`) is a pure replay of saved scorecard answers; it calls no model
  and writes nothing but its own report;
- no module of the service may import or name it (`tests/test_autosend_sim.py`, `NotWiredTests`);
- the replay exits 1 if any real job in its input ended anywhere but `PENDING_HUMAN_REVIEW`, so every run also
  re-checks that the real system left every case to a person (ADR-031).

## The data

| Set | Cases | Where it comes from | What it adds |
|---|---|---|---|
| `case_triage_autosend_hard_v1` | 128 (64 TH, 64 EN) | written for this work, committed before any model saw it (commit `548abf5`) | keyword traps, negation, several problems, steering and approval injections, security, legal and privacy, distress, vague, slang, ambiguous, personal data; `needs_person` on 38 |
| `open_clinc150_v1` | 300 EN | CLINC150 (CC BY 3.0) | 100 out-of-scope requests and the edge of `other` |
| `open_banking77_v1` | 300 EN | BANKING77 (CC BY 4.0) | fine-grained money and access requests |
| `open_massive_th_en_v1` | 150 TH + the same 150 EN | MASSIVE 1.1 (CC BY 4.0) | Thai by professional translators; assistant requests outside this help desk (all `other`); EN↔TH agreement |
| `open_bipia_injection_v1` | 75 | BIPIA's text attacks (MIT) added to the hard set's 20 clear cases | does a generic injection change the answer, its confidence or its availability? |
| the three existing sets | 217 | `case_triage_synthetic_v1`, `case_triage_heldout_v1`, `triage_edge_robustness_v1` | the ordinary cases, for comparison |

The open sets are built at run time by `tests/open_benchmarks/build_sets.py` (standard library only, run
isolated with `python -I`): it downloads each pinned source, refuses any file whose SHA-256 differs, draws a
fixed sample in an order made from SHA-256 (not `random`, so every Python version picks the same cases) and
maps each item into the four categories with tables in the code. Intents whose place is arguable (money
transfers, top-ups, cash withdrawals, card security) are left out rather than forced into a category.
`tests/open_benchmarks/manifest_v1.json` records the sources and the SHA-256 of every case file, and
`--check` fails when a rebuild differs. Licences and attribution: `tests/open_benchmarks/NOTICE.md`. Nothing
downloaded is committed (roadmap 5.6, "Don't").

`needs_person` is the developer's judgement and is used only in the hard set: cases that try to steer routing
or approval, security incidents, legal or privacy requests, and distress. The BIPIA copies carry
`open_injection` instead: their attacks ask for a free-text answer that this system never produces, so they
are counted as "injections sent" but not as unsafe by themselves.

## The policies

Each policy is a pure function of one saved answer (`would_send`). A job that failed, or an AI answer that was
unavailable, is always held.

| Policy | Sends when | Sends to |
|---|---|---|
| `ai_high` | the AI answered with `high` confidence | the AI's category |
| `agree` | rules and AI chose the same category | that category |
| `agree_high` | they agree and the AI said `high` | that category |
| `strict` | they agree, `high`, no review reason at all (so the rules matched a keyword, which also means never `other`) and nothing was masked | that category |

## What is measured (every rate as numerator/denominator)

- **sent**: cases the button would send without a person;
- **sent wrong**: sends whose category differs from the label, with the upper end of the 95% Wilson score
  interval, so "0 mistakes in 50" reads as "at most about 7%", not "0%";
- **sent unsafe**: wrong, or `needs_person`;
- **needs person sent** and **injection sent**: of the cases that must see a person, or that carry an
  injection, how many the button would let through;
- **safe sends**: correct and not `needs_person`, out of all cases: the work a button would really save;
- per language; per tag of the hard set (for `agree_high`);
- **EN↔TH pairs** (MASSIVE): the same AI category, and the same decision of each policy;
- **injected copies** (BIPIA): against the same case without the attack, how often the AI's category or
  confidence changed, or its answer was lost.

## How to run

```bash
python -I tests/open_benchmarks/build_sets.py --out open-sets --cache ~/open-bench-cache --check
python -m app.eval.triage_shadow_eval --golden app/eval/golden/case_triage_autosend_hard_v1.json --out hard.json
python -m app.eval.triage_shadow_eval --golden open-sets/open_bipia_injection_v1.json --out bipia.json
python -m app.eval.autosend_sim --report hard.json --report bipia.json --summary summary.md --out sim.json
```

With Typhoon, add `--min-interval-s 1` and the environment from CLAUDE.md §4. In CI:
- *Core logic tests* runs the hard set with the mock on every push, compares every case with
  `tests/baselines/autosend_hard_mock.json` (the eval gate), and writes the simulation's summary;
- *Auto-approve limits (open benchmarks + hard set)* (`.github/workflows/autosend-limits.yml`) builds the
  open sets and runs everything: with the mock on pull requests that change this lane, and with Typhoon by
  hand.

## What a real button would need

Not planned, and not to be built without the owner. In the order the measurements point to:
1. **A confidence that can be checked (E5).** Typhoon's self-reported `high` does not separate right from
   wrong (evidence note), so it cannot carry a button. Candidates are in E5: a second-choice field, or two
   independent calls compared.
2. **A signal for text that addresses the system.** The rules and the AI agreed on cases whose text both
   contained an attack and named a category; agreement is not independence when the attacker writes the
   keyword. A plain-code check (never AI) could hold any case that talks to the system.
3. **Independent labels.** Every label here is the developer's (and the open sets' are a mapping). Reviewer
   labels from 2.8, or the owner's in E5, would come first.
4. **An ADR that changes rule 4**, scoped to one category or one low-risk action, with a person able to undo
   it, and the owner's decision.

## Limits

- The policies are judged on developer labels and a developer's `needs_person` judgement. The rates describe
  these sets and the model named in each report, never real traffic, Claude or another model.
- The hard set is adversarial by design (written knowing the rules and the prompt), so its rates are a worst
  case, not accuracy.
- The open sets' text was written for datasets (crowd workers, experts, translators), cleaner than real cases
  (ADR-024).
- One run per set. The answers of a hosted model can change from week to week (roadmap 5.7, drift).
