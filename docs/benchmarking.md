# Benchmarking plan: robustness, open benchmarks, attacks and live conditions

**Status (2026-11-11):**
- Stage 1, the robustness gate, is built and runs in CI on every push (roadmap 5.4, PR #41). Its first run found 8 bugs,
  45 gaps and 11 notes ([evidence note](evidence/2026-11-07-robustness-stage1.md)).
- The 8 bugs were fixed in PR #42 (roadmap 5.5): 215/270 own items passed, with 0 bugs and 44 gaps.
  After E2 in PR #64, 239/270 own items pass, with 0 bugs, 20 gaps and 11 notes; none of 4,680 sweep checks
  violate a promise. E2 fixes 24 of the original 27 rules gaps and retains three measured limits.
  Deciding the other gaps is the rest of 5.5.
- E2 (PR #64) replaces the shadow workflow's official rules and this benchmark's `rules` layer with
  versioned Thai/English rules. The original v1 demo remains available. The [E2 evidence](evidence/2026-11-11-e2-rules-v2.md)
  records each of the original 27 rules-gap decisions and the new baseline: `SYN-RUL-009` (cross-script
  lookalikes), `SYN-RUL-032` and `SYN-RUL-033` (negation/precedence) stay as known limits. Its live-measurement
  status is explicit.
- Stage 2 (open benchmarks, 5.6) and stage 3 (attacks, privacy, load and live drift, 5.7) are planned below.
- The 116 rules items had their first run with a real model on 2026-11-10 (Typhoon, from a cloud session):
  AI correct 104/116 where the rules are correct on 48/116, with all 12 mistakes on requests labelled `other`
  ([evidence note](evidence/2026-11-10-effectiveness-baseline.md)). What follows from it is in the
  [effectiveness plan](effectiveness_plan.md).

The data rule behind all three stages is ADR-024 in [architecture.md](architecture.md): only openly licensed text
that was written for a dataset, with no real people's records. Real data still waits for the owner's decision D4.

## สรุปสำหรับเจ้าของโปรเจกต์

**สรุปบรรทัดเดียว:** ทดสอบระบบด้วยข้อมูลเปิดที่นักพัฒนาทั่วโลกใช้ (open dataset) ผสมกับเคสสุดโหดที่เขียนเพิ่มทั้งไทยและอังกฤษ
รอบแรกเจอปัญหาจริง 8 จุด และแก้ครบแล้ว (7 จุดแก้นอก Core อีก 1 จุดแก้ Core 1 ฟังก์ชัน พร้อมบันทึกข้อตัดสินใจ ADR-025)

### ภาพรวม 3 ขั้น

| ขั้น | ทำอะไร (ภาษาง่าย) | ใช้ข้อมูลอะไร | วัดอะไร | รันที่ไหน / ค่าใช้จ่าย | สถานะ |
|---|---|---|---|---|---|
| 1. ด่านความทนทาน (robustness) | ป้อนของแปลก ๆ เข้าทุกชั้นของระบบ แล้วดูว่าไม่พัง ไม่รั่ว ไม่เพี้ยน | เคสที่เขียนเอง 270 ข้อ; ข้อความแปลก 515 แบบ (BLNS); ไฟล์ทดสอบ JSON 318 ไฟล์ (JSONTestSuite); คำขอจาก CLINC150 และ BANKING77 รวม 73 ข้อ | ทุกชั้นรักษาคำสัญญาของตัวเองไหม เช่น ข้อมูลผิดต้องได้ "ข้อมูลไม่ถูกต้อง (400)" ไม่ใช่ "เซิร์ฟเวอร์พัง (500)" และเคสต้องถึงมือคนตรวจเสมอ | GitHub ทุกครั้งที่ส่งโค้ด ฟรี ไม่เรียก AI จริง | **สร้างแล้ว** รอบแรกเจอ 8 bug แก้ครบแล้ว (5.5) |
| 2. ด่านข้อสอบกลาง (open benchmarks) | เอาข้อสอบมาตรฐานที่วงการใช้วัดระบบแยกคำขอ มาวัดกฎและ AI ของเรา | CLINC150 (มีคำขอนอกกรอบ 1,000 ข้อ); BANKING77 (คำขอธนาคาร 77 แบบ); MASSIVE ภาษาไทยคู่กับอังกฤษประโยคต่อประโยค | ตอบถูกกี่ข้อ (ทุกตัวเลขมีตัวตั้งและตัวหาร); บอก "นอกกรอบ" ได้ถูกไหม; ประโยคไทยกับอังกฤษที่ความหมายเดียวกันได้คำตอบเดียวกันไหม | คุณกดรันเองในแท็บ Actions กับ Typhoon (ฟรี) | วางแผนแล้ว (5.6) |
| 3. ด่านโจมตีและใช้งานจริง | ลองหลอก AI ด้วยคำสั่งแอบแฝง; ลองให้ข้อมูลส่วนตัวรั่ว; ยิงเคสพร้อมกันเยอะ ๆ; ดับเครื่องกลางทาง; วัดซ้ำทุกสัปดาห์ว่า AI เปลี่ยนนิสัยไหม | คำสั่งแอบแฝง 662 ข้อ (deepset, Apache-2.0) และฉบับภาษาไทยที่เขียนเอง; ข้อมูลส่วนตัวสมมุติแบบไทย; เคสชุดขั้น 1–2 | คำสั่งแอบแฝงทำให้ระบบตัดสินใจเอง หรือได้ลิงก์นอกคลังไหม (ต้องเป็น 0 เสมอ); ข้อมูลส่วนตัวไปถึง AI กี่จุด; เคสหายหรือซ้ำไหม; เวลาต่อเคส | GitHub ฟรี และ Typhoon ฟรี | วางแผนแล้ว (5.7) |

### ขั้นที่ 1 ทำงานอย่างไร

1. ทุกครั้งที่มีการส่งโค้ด GitHub เปิดชุดทดสอบ 343 รายการ แล้วส่งของแปลกเข้าระบบทีละชั้น:
   - ด่านรับเคส (API)
   - กฎคำสำคัญ
   - การปิดข้อมูลส่วนตัว
   - การตรวจคำตอบของ AI
   - สัญญาของ Core
   - งานเต็มรูปแบบที่วิ่งผ่าน Core
2. ระหว่างทางยังกวาดข้อมูลเปิดผ่านทุกชั้นอีก 4,680 ครั้ง
3. AI ที่ใช้ทดสอบเป็น AI จำลอง (mock) กับ "บริการ Typhoon ปลอม" ที่รันในเครื่องทดสอบเอง
   - ลองคำตอบแปลกของ AI 39 แบบกับตัวตรวจคำตอบ และอีก 15 แบบที่วิ่งผ่านทั้งระบบ
   - ไม่เสียเงิน และไม่ส่งอะไรออกไปข้างนอก
4. ผลแต่ละรายการถูกจดไว้ในไฟล์ผลอ้างอิง (baseline)
   - ถ้ามีการแก้โค้ดแล้วผลรายการไหนเปลี่ยน ช่องตรวจจะเป็นสีแดงและบอกว่ารายการไหนเปลี่ยน
   - แบบเดียวกับด่านตรวจผลรายเคส (eval gate) ที่มีอยู่แล้ว
5. แต่ละรายการบอกว่าถ้าไม่ผ่านร้ายแรงแค่ไหน:
   - **ปัญหาร้ายแรง (bug)** คือผิดคำสัญญาที่ระบบเขียนไว้
   - **จุดอ่อน (gap)** คือยังไม่พัง แต่ควรแก้
   - **ข้อสังเกต (info)** คือควรรู้ไว้ รวมถึงข้อจำกัดที่เอกสารเขียนไว้แล้ว

### ผลรอบแรก (7 พ.ย. 2026)

- เคสที่เขียนเอง 270 ข้อ: **ผ่าน 206** · ปัญหาร้ายแรง **8** · จุดอ่อน **45** · ข้อสังเกต **11**
- การกวาดข้อมูลเปิด 4,680 ครั้ง: **ไม่ผิดคำสัญญาเลยแม้แต่ครั้งเดียว**
- คำขอจาก CLINC150 และ BANKING77: กฎคำสำคัญตอบตรงกับป้ายที่ผู้พัฒนาจับคู่ไว้ **32/73**
  (ป้ายเป็นการจับคู่ของผู้พัฒนา ไม่ใช่ความแม่นยำจริง)
- ได้ผลตรงกันทุกรายการบน Python 3.10, 3.12 และ 3.13

**ปัญหาร้ายแรง 8 จุด อธิบายแบบง่าย** (รหัสในวงเล็บคือรายการในชุดทดสอบ)

1. **ตัวเลขยาวมาก ๆ ในคำขอ ทำให้ระบบตอบว่า "เซิร์ฟเวอร์พัง (500)"** แทนที่จะบอกว่า "ข้อมูลไม่ถูกต้อง (400)"
   - เช่น ตัวเลข 5,000 หลัก
   - ผู้ส่งไม่รู้ว่าตัวเองผิดตรงไหน และ Sentry ได้แจ้งเตือนหลอก
   - ต้นเหตุคือตัวอ่าน JSON ของ Core ปล่อยข้อผิดพลาดชนิดที่ไม่ได้สัญญาไว้ออกมา
   - รายการ: SYN-INT-036, SYN-INT-037 และ SYN-COR-040
2. **ข้อความที่มี "ตัวอักษรพัง" ก็ได้ 500 เหมือนกัน** ทั้งข้อความเคสและคำถามผู้ช่วยเรียน
   - ตัวอักษรพังคือครึ่งตัวของอีโมจิ (lone surrogate)
   - รายการ: SYN-INT-038 และ SYN-INT-039
3. **ถ้า AI ตอบมีตัวอักษรพังแบบเดียวกันในเหตุผล เคสทั้งเคสจะล้ม และไม่ถึงมือคนตรวจ** ข้อนี้ร้ายแรงที่สุด
   - ระบบตรวจคำตอบรับคำตอบนั้น แต่ Core เก็บลงฐานข้อมูลไม่ได้
   - ผิดคำสัญญาสำคัญที่ว่า "AI มีปัญหาเมื่อไร เคสยังไปต่อได้ด้วยกฎเดิม"
   - ผู้ช่วยแนะนำแหล่งเรียนก็ล้มแบบเดียวกัน
   - คนที่พิมพ์เคสอาจสั่ง AI ให้ตอบแบบนี้ได้ด้วย (คำสั่งแอบแฝง)
   - รายการ: SYN-AIR-040, SYN-E2E-029 และ SYN-E2E-044

**จุดอ่อนที่น่ารู้**

- **กฎคำสำคัญ**:
  - ไม่รู้จักภาษาไทยเลย
  - หลงกับคำที่ซ่อนอยู่ในคำอื่น เช่น "design in" มีคำว่า "sign in" อยู่ข้างใน และเมือง "Billings" มีคำว่า "billing"
  - ไม่เข้าใจคำปฏิเสธ เช่น "ล็อกอินได้ แต่จ่ายเงินไม่ผ่าน"
  - คำสั่งแอบแฝงภาษาไทยที่มีคำว่า billing ทำให้กฎส่งผิดคิว
  - ทั้งหมดนี้คือเหตุผลที่มี AI ให้ความเห็นที่สอง (second opinion) วัด AI กับเคสชุดนี้ได้ด้วยปุ่มในข้อถัดไป
- **การปิดข้อมูลส่วนตัว**: ยังมีข้อมูลที่ส่งถึง AI ได้ ได้แก่
  - เบอร์ที่เว้นวรรคสองช่อง คั่นด้วย / หรือคั่นด้วยตัวล่องหน
  - ชื่ออังกฤษที่พิมพ์ใหญ่หรือพิมพ์เล็กทั้งหมด
  - ชื่อ "McDonald" ที่ถูกปิดได้แค่ครึ่งเดียว
  - อีเมลโดเมนภาษาไทย (.ไทย)
- **ตัวอักษรที่มองไม่เห็น**:
  - ระบบรับเคสที่มีแต่ตัวล่องหน คือมองไม่เห็นอะไรเลย
  - ตัวกลับทิศ (bidi override) ในเคสหรือในเหตุผลของ AI อาจทำให้คนตรวจอ่านข้อความผิด

**ข่าวดี**
- ตัวอ่าน JSON ของ Core รับไฟล์ทดสอบทั้ง 318 ไฟล์โดยไม่พังเลย
  - มีแค่ 2 ไฟล์ที่ชื่อช่องซ้ำ ซึ่งระบบตั้งใจปฏิเสธอยู่แล้ว
- ข้อความแปลกทั้ง 515 แบบผ่านทุกชั้นโดยไม่ผิดคำสัญญา และไม่มีข้อความใดถูกรันเป็นคำสั่ง (shell)
- บริการ Typhoon ปลอมตอบแปลก 14 แบบ เคสยังถึงมือคนตรวจ 12 แบบ เช่น
  - ตอบว่างเปล่า หรือตอบเป็นบรรทัดแบบ Typhoon รอบแรก
  - บริการล่ม หรือได้หน้าเว็บแทนคำตอบ
  - AI แอบใส่ "อนุมัติ" มาเอง

  อีก 2 แบบคือคีย์ผิด (401) ซึ่งตั้งใจให้ล้มดัง ๆ ตามที่ออกแบบไว้ และแบบตัวอักษรพังในข้อ 3 ข้างบน
  (หลังแก้ถึงมือคนตรวจ 13 แบบ ดูหัวข้อถัดไป)

### ผลหลังแก้ 8 จุด (8 พ.ย. 2026, PR #42)

- เคสที่เขียนเอง 270 ข้อ: **ผ่าน 215** · ปัญหาร้ายแรง **0** · จุดอ่อน **44** · ข้อสังเกต **11**
- การกวาดข้อมูลเปิด 4,680 ครั้ง: ยังไม่ผิดคำสัญญาเลย และได้ผลเหมือนรอบแรกทุกครั้ง
- ได้ผลตรงกันทุกรายการบน Python 3.10, 3.12 และ 3.13
- แก้อย่างไร:
  1. ตัวเลขยาวมาก ๆ หรือตัวอักษรพังในคำขอ: ระบบตอบ "ข้อมูลไม่ถูกต้อง (400)" และไม่ส่งแจ้งเตือนหลอกไป Sentry
  2. ตัวอักษรพังในคำตอบของ AI: ระบบเปลี่ยนเป็นเครื่องหมาย � ก่อนเก็บ เคสจึงถึงมือคนตรวจพร้อมความเห็นของ AI
     - ผู้ช่วยแนะนำแหล่งเรียนก็ตอบได้ตามปกติ
     - บริการ Typhoon ปลอมตอบแปลก 14 แบบ ตอนนี้เคสถึงมือคนตรวจ 13 แบบ แบบที่เหลือคือคีย์ผิด (401) ที่ตั้งใจให้ล้มดัง ๆ
  3. ตัวอ่าน JSON ของ Core: อะไรที่อ่านไม่ได้ ตอบเป็นข้อผิดพลาดชนิดเดียวที่สัญญาไว้ (SpecError)
     - จุดนี้แก้ใน Core 1 ฟังก์ชัน พร้อมบันทึกข้อตัดสินใจ (ADR-025) และแยกเป็นชิ้นของตัวเอง
     - จุดอ่อน SYN-COR-041 หายไปด้วย เพราะเป็นต้นเหตุเดียวกัน
     - ถ้าคุณไม่อยากให้แตะ Core บอกผมได้ ผมจะเอาชิ้นนี้ออกก่อนรวม ข้อ 1–2 ยังใช้ได้เหมือนเดิม

### คุณต้องทำอะไร (owner test)

1. **ดูผลหลังแก้** (ขั้น 5.5)
   - เปิด PR #42 บน GitHub แล้วกดแท็บ Checks เลือก *Core logic tests* (3.12) แล้วกด Summary
   - เลื่อนหาหัวข้อ "ด่านความทนทาน (Robustness benchmark ขั้นที่ 1)"
   - ต้องเห็น "ผ่าน **215/270**", "ปัญหาร้ายแรง (bug) **0**" และบรรทัด "ด่านตรวจผลรายรายการ (gate): **ผ่าน**"
   - ผลรอบแรกยังดูได้ที่ PR #41 ("ปัญหาร้ายแรง (bug) 8")
2. **ลองกับ AI จริง (ไม่บังคับ และฟรี)**
   - แท็บ Actions เลือก *Shadow eval with Typhoon (manual)* แล้วกด Run workflow
   - ช่อง case_set เลือก `robustness_edge_v1` แล้วกด Run
   - รอประมาณ 3–5 นาที แล้วเปิดหน้าสรุป จะเห็นว่า AI จริงตอบเคสสุดโหด 116 เคสถูกกี่เคส เทียบกับกฎ
   - ผลนี้เป็นของ Typhoon รุ่นนั้นเท่านั้น
3. **บอกผมว่าจะรวม (merge) PR #42 ไหม และรับส่วนที่แก้ Core ด้วยไหม**
   - หลังรวม Render จะขึ้นเวอร์ชันใหม่ เพราะรอบนี้แก้โค้ดที่ระบบใช้จริง (แผนฟรี: เคสที่ค้างในคิวจะหาย)
   - งานถัดไปคือตัดสินใจเรื่องจุดอ่อน (gap) ที่เหลือ 44 จุด (ขั้น 5.5 ส่วนที่เหลือ)

### แหล่งเรียน (เรียงตามลำดับที่ควรอ่าน)

1. **CheckList** (Ribeiro และคณะ, ACL 2020) — https://arxiv.org/abs/2005.04118 — **อ่านก่อน**
   - ใช้ทำอะไร: วิธีคิดเคสทดสอบอย่างเป็นระบบ 3 แบบ
     - ทดสอบความสามารถขั้นต่ำ (MFT)
     - เปลี่ยนรูปประโยคแต่ความหมายเดิม ต้องได้คำตอบเดิม (INV)
     - เปลี่ยนความหมายแล้วคำตอบต้องเปลี่ยนตาม (DIR)
   - เคสที่เขียนเองทุกข้อติดป้าย 3 แบบนี้
2. **Parsing JSON is a Minefield** (Nicolas Seriot) — https://seriot.ch/projects/parsing_json.html
   - ใช้ทำอะไร: เข้าใจว่าทำไมไฟล์ JSON แปลก ๆ ทำให้โปรแกรมพัง และเป็นที่มาของไฟล์ทดสอบ 318 ไฟล์
   - อ่านถ้าอยากรู้ว่า bug ข้อ 1–3 เกิดได้อย่างไร
3. **CLINC150** (Larson และคณะ, EMNLP 2019) — https://aclanthology.org/D19-1131/
   - ใช้ทำอะไร: วิธีวัดว่าระบบรู้ไหมว่าคำขอ "อยู่นอกกรอบ" ตรงกับหลักปรัชญาข้อ 3 ของคุณ
   - ใช้ในขั้นที่ 2 และมีอยู่ในคลังแหล่งเรียนของผู้ช่วยเรียนแล้ว
4. **OWASP Top 10 for LLM Applications: LLM01 Prompt Injection** — https://genai.owasp.org/llmrisk/llm01-prompt-injection/
   - ใช้ทำอะไร: รู้จักการโจมตีด้วยคำสั่งแอบแฝง และวิธีป้องกันที่วงการแนะนำ
   - ใช้ในขั้นที่ 3

## Stage 1 — the robustness gate (built, roadmap 5.4, PR #41)

### What it checks

Each layer has promises that every item must keep, whatever it expects otherwise. They are checked on every
synthetic item and on every element of the open corpora (the sweeps).

| Layer | What runs | Promises checked on every input |
|---|---|---|
| `intake` | `ApiApp.handle` in memory: `POST /v1/jobs` with odd bodies, fields, encodings and headers | Bad input never gets a 5xx. Statuses stay in the documented set. An accepted job's input can be serialized by Core. The same idempotency key never makes a second job |
| `rules` | versioned Thai/English `keywords-v2` on the admitted (trimmed) text (E2, PR #64); `case_triage.v1` retains the original demo separately | A valid category with its queue. The same answer twice. For INV items, the same answer as the item it paraphrases |
| `masking` | `app.llm.redaction.mask` | No exception. Only known kinds. Masking twice changes nothing. Listed values must not reach the AI, and listed non-personal text must stay |
| `ai_reply` | `answer_text` (the Typhoon path) or the plain path, then `gateway.parse_answer` | Only `InvalidModelOutput` may be raised. An accepted answer has fixed choices, text of at most 200 characters without control characters, and can be stored by Core |
| `core` | `normalize_spec`, `decode`, `fingerprint` from `neuron_flow.model` | Only `SpecError` (or its `MessageSizeError`) may be raised. Fingerprints are stable |
| `e2e` | whole jobs in a real `Runtime` with child processes: v1, v2 with the mock AI, v2 and the study guide against a local fake of the Typhoon HTTP API | The job reaches `PENDING_HUMAN_REVIEW` (or `COMPLETED` for the study guide). The stored input equals the admitted input. A setup error (HTTP 401) fails loudly by design. The study guide gives at most 5 resources, all from the library. The BLNS shell canary `/tmp/blns.fail` never appears |

### The data

- **`tests/robustness/synthetic_v1.json`**: 270 hand-written items in Thai and English, written for this
  project.
  - Each item has a Thai and an English title, a CheckList type (MFT, INV or DIR), a capability tag (such as
    `negation`, `substring`, `homoglyph`, `bidi`, `pii_phone` or `json_numbers`), the input, what should
    happen, and a severity.
  - Severity says how serious a mismatch is: `bug` when a stated promise breaks, `gap` when it is worth
    fixing, `info` when it is worth knowing.
  - Items that the masking docs already list as not detected carry `known: documented_limitation`.
  - Every personal value is invented: public test card numbers, example.com addresses, made-up names and
    numbers.
  - Big inputs are stored as `$repeat` / `$concat` recipes, so the file stays readable.
- **`tests/robustness/open_extract_v1.json`**: excerpts of four open datasets, each pinned to an upstream
  commit with every file's SHA-256 (sources and licences in `tests/robustness/NOTICE.md`):
  - every string of the Big List of Naughty Strings (515, MIT);
  - every file of JSONTestSuite's `test_parsing/` (318 files: 95 must be accepted, 188 must be rejected,
    35 may go either way; MIT);
  - 39 CLINC150 requests (CC BY 3.0) and 34 BANKING77 requests (CC BY 4.0), re-labelled into the four triage
    categories. The selection rules and the label mapping are code in `build_open_extract.py`: requests
    that contain a rule keyword, the first two of each mapped intent and the first six out-of-scope
    requests.
- **`tests/robustness/triage_edge_golden_v1.json`**: the 116 rules items, written as a `neuron-flow-golden-v1`
  case file, so the existing scorecard can run them against a real model. *Shadow eval with Typhoon (manual)*
  and *Shadow eval with Claude (manual)* have a `case_set` choice for it. A unit test keeps the file in step
  with the two sets.

### How it runs

```bash
python -m tests.robustness.bench --summary summary.md --out robustness.json \
    --compare-with tests/baselines/robustness_v1.json   # everything, about 25 s; exit 3 on any change
python -m tests.robustness.bench --layers intake,core           # a subset
python -m tests.robustness.bench --write-baseline tests/baselines/robustness_v1.json
python -m tests.robustness.bench --export-golden tests/robustness/triage_edge_golden_v1.json
python -I tests/robustness/build_open_extract.py verify  # re-download the pinned sources, rebuild byte for byte
```

The runner and the CI gate:
- *Core logic tests* runs the whole benchmark on Python 3.10 and 3.12. It writes the Thai/English summary on
  the run page and fails when any item's outcome or any sweep's violations differ from
  `tests/baselines/robustness_v1.json`.
- The baseline records failures too. A fix turns the gate red until the same pull request regenerates the
  baseline, so every change of outcome is reviewed and explained. This is the same rule as the eval gates
  (CLAUDE.md §5).
- `tests/test_robustness_bench.py` checks the fast layers against the same baseline in the unit tests. It
  also checks the data's shape, the licence notice and the golden file.
- Everything is offline and uses the standard library: the mock AI, and a local fake server in the Typhoon
  wire format (`tests/fake_openai.py`). The fake server gets a deliberately fake key
  (`typhoon-test-robustness-benchmark`).
- Outcomes are the same on Python 3.10.20, 3.12.13 and 3.13.18. One item (input nested 5,000 levels deep) is
  observed by its HTTP status only, because Python before 3.12 refuses that depth with a different error code.

### Adding an item

1. Add it to `synthetic_v1.json` with a new id in its layer's range.
2. Give it a Thai and an English title, a CheckList type, a capability, the input, the expectation and the
   severity.
3. Write the expectation as what *should* happen, even when the system does not do it yet. The baseline
   records what does happen.
4. Regenerate the baseline and the golden file (the two commands above).
5. Say why in the pull request.

Open-dataset items change only through `build_open_extract.py` and its pinned sources.

### Limits of stage 1

- The mock AI and the fake server test this project's code, not any model. The AI's own judgement on these
  cases is measured only by the manual live runs.
- The labels of CLINC150 and BANKING77 requests are the developer's mapping into four categories. The rules'
  32/73 says where keyword rules break on text they were not written for. It is not an accuracy figure.
- The masking items probe patterns; they are not a privacy guarantee (rule 9).

## Stage 2 — open benchmarks (planned, roadmap 5.6)

**Goal:** measure the rules and the AI second opinion on the datasets that intent-detection work is usually
judged on. Measure it the same way every time and per language, with every rate as numerator/denominator.

| Dataset | What it adds | Licence | How it is used |
|---|---|---|---|
| CLINC150 (`data_full.json`: 4,500 in-scope test requests in 150 intents, 1,000 out-of-scope) | Out-of-scope detection, the "stay inside the frame" principle | CC BY 3.0 | Triage: the four categories through the mapping, which grows from `CLINC_MAP`. Study guide: every request is outside its 11 topics, so each one must be answered `out_of_scope` (the false in-scope rate) |
| BANKING77 (3,080 test requests, 77 fine-grained intents) | Fine-grained requests about money and access in one domain | CC BY 4.0 | Triage through `BANKING_MAP` (access, billing, other); the confusion between billing and other |
| MASSIVE 1.1, `th-TH` and `en-US` (2,974 parallel test utterances per locale) | Thai written by professional translators, sentence for sentence with English | CC BY 4.0 | Mostly assistant requests outside the triage domain, so most map to `other` (false alarms). The parallel pairs measure **cross-language consistency**: the same answer for the Thai and the English sentence with the same id |

**Tasks:**
1. A manual workflow, *Open benchmarks (manual)*, downloads the pinned files on GitHub:
   - CLINC150 and BANKING77 from the same commits as stage 1;
   - MASSIVE from its official release archive, checked against a SHA-256 written in the workflow.
2. It builds the case files at run time. They are never committed.
3. It draws a fixed, seeded sample stratified by intent: 300 requests per dataset and language, about
   5 minutes each at the 1 request per second pacing used for Typhoon's free tier.
4. It runs both scorecards (`--golden`) with Typhoon by default. The mock runs only as a pipeline check.
   The local open model (roadmap 5.8, ADR-026) can take the same sample as a second model: no rate limit and
   nothing sent out, but CPU-slow, so a smaller sample may be needed.
5. The run page shows:
   - accuracy and macro-F1 per category;
   - out-of-scope recall and the false in-scope rate;
   - EN↔TH agreement on MASSIVE pairs;
   - rules vs AI;
   - the rate of AI answers marked unavailable;
   - median and slowest latency.
6. A dated evidence note records each run.

**Done when:** the workflow runs end to end with the mock, the sampling is reproducible from its seed and the
sources' hashes, and the first Typhoon run is in an evidence note.

**Don't:**
- commit copies of the full datasets;
- present mapped labels as ground truth;
- compare these numbers with published leaderboard scores, because the label sets differ;
- send anything but these public sets to the provider.

## Stage 3 — attacks, privacy, load and live drift (planned, roadmap 5.7)

1. **Prompt injection.**
   - Data: `deepset/prompt-injections` (662 short prompts, Apache-2.0) placed inside case text and study
     messages, plus Thai versions that the developer writes.
   - Structural promises, 100% required: no decision, no queue chosen by the AI, no field outside the
     schema, no link outside the library.
   - Measured and reported, not a pass or fail: how often an injection changes the AI's category compared
     with the same case without it.
   - Reference: OWASP LLM01.
2. **Personal data.**
   - Data: a generator of invented Thai personal data. It makes names with every title, ID numbers with
     valid check digits, phones in many formats and addresses, inside realistic Thai and English cases.
   - It is run against the fake provider, and the request bodies are scanned for the planted values.
   - Measured: the leak rate per kind and per format, which turns stage 1's masking gaps into rates.
3. **Load and restarts.** The *Service container* workflow gets:
   - a burst of 200 submissions at once (expect 429s and 503 `queue_full`, never a 500);
   - a storm of identical requests (exactly one job);
   - a kill in the middle of a burst (no case lost or doubled after the restart).
   Traces give per-step latency under load.
4. **Live drift.** A weekly scheduled run of the stage-1 edge set and the 61-case set against Typhoon, compared
   with the week before, so a silent model change shows up. Turning on the schedule is the owner's choice:
   it uses the existing `TYPHOON_API_KEY` secret, and the data is synthetic. Running the pinned local model
   (5.8) on the same sets the same week tells the two causes apart: if Typhoon's numbers move and the local
   model's do not, the change is on Typhoon's side, not in our code.

**Done when:** each part runs in CI or by hand with its promises as gates, and the first run of each is in an
evidence note.

## Datasets considered and not used (yet)

| Dataset | Why not |
|---|---|
| ai4privacy `pii-masking-400k` and its relatives | Synthetic, but the licence allows academic, non-commercial use only. It forbids redistribution and derivative works without a written licence, so it cannot be committed or built on here. Stage 3 generates its own Thai personal data instead |
| `truevoice-intent` (Thai call-centre intents, about 16k) | Transcribed real calls, so real people's words. It needs the owner's decision D4 (rule 9), and its licence was not checked |
| Wisesight Sentiment and other social-media corpora | Real posts by real people (D4), and about sentiment rather than routing |
| Thai model benchmarks (SEA-HELM, Thai LLM Leaderboard, ThaiExam) | They compare models, not this system. They are useful when choosing a model, not as gates here |
| Sets that are only on Hugging Face (MASSIVE, deepset) | The development session cannot reach Hugging Face, so stages 2–3 fetch them inside GitHub Actions instead |

## Rules for the numbers

- Every rate keeps its numerator and denominator.
- Every run records the commit, the Python version, the data hashes and the model.
- Mock and fake-server results describe this project's code. A Typhoon result describes that Typhoon model,
  never Claude.
- Developer-written and developer-mapped labels are not independent ground truth. Failures are recorded as
  carefully as passes.
