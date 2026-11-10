# Effectiveness plan: make the measured results reach the person

**Status (2026-11-10):** a plan the owner asked for ("วางแผนปฏิบัติงานเพิ่มเติมเพื่อเพิ่มประสิทธิผลการทำงานของระบบ"), proposed in
PR #50. Nothing in it is built yet. It adds six work packages, E1 to E6, to [ROADMAP.md](ROADMAP.md), which stays the source of
truth for status. Every "now" figure below was measured and is in an evidence note, most of them in
[the baseline note of 2026-11-10](evidence/2026-11-10-effectiveness-baseline.md).

## สรุปสำหรับเจ้าของโปรเจกต์

**สรุปบรรทัดเดียว:** ระบบแข็งแรงแล้ว (ไม่มีข้อผิดพลาดค้างใน Sentry และคำมั่นที่โค้ดคุมไว้เป็นจริงทุกครั้งที่วัด)
สิ่งที่ถ่วงประสิทธิผลตอนนี้ไม่ใช่กำลังของเครื่องหรือจำนวนงาน แต่เป็นจุดอ่อน 5 จุดที่วัดได้ แผนนี้แก้ทีละจุด และวัดก่อนกับหลังทุกครั้ง

**"ประสิทธิผล" ในแผนนี้หมายถึงอะไร** คือ 5 อย่างที่วัดเป็นตัวเลขได้

1. ข้อเสนอแรกที่คนตรวจเห็นถูกต้อง
2. ป้าย "ต้องดูก่อน" ชี้เฉพาะเคสที่ควรดูก่อนจริง ๆ
3. คำตอบมาเร็ว แม้เป็นเคสแรกหลังระบบตื่น
4. หน้าเว็บจริงให้คำตอบที่ดีเท่ากับที่วัดได้ในห้องทดสอบ
5. รู้จากการใช้งานจริงว่าคำตอบตรงใจไหม

**ตอนนี้อยู่ตรงไหน (ตัวเลขที่วัดแล้ว)**

| สิ่งที่วัด | ตอนนี้ | งานที่จะขยับตัวเลขนี้ |
|---|---|---|
| กฎคำสำคัญ (ข้อเสนอหลัก) จัดหมวดถูก | 29 จาก 61 เคส ภาษาไทยถูกแค่ 7 จาก 26 เคสยาก 48 จาก 116 | E2 |
| เคสที่ถูกยกเป็น "ต้องดูก่อน" (เมื่อใช้ AI จริง) | 33 จาก 61 และ 64 จาก 116 คือเกินครึ่ง ป้ายจึงแทบไม่ช่วยจัดลำดับ | E2 |
| AI จริง (Typhoon) จัดหมวดถูก | 60 จาก 61 และ 104 จาก 116 ภาษาไทยถูกทุกข้อ (26 จาก 26 และ 13 จาก 13) | รักษาไว้ |
| จุดที่ AI จริงพลาด | ทั้ง 12 ข้อที่ AI พลาดในชุดเคสยาก เฉลยว่า "อื่น ๆ" แต่ AI จับใส่หมวดใกล้เคียง และ AI บอก "มั่นใจสูง" ทุกข้อ ทั้งข้อถูกและข้อผิด | E5 |
| เคสแรกหลังระบบตื่น | ราว 10 วินาที (วัดได้ 4 ครั้ง ช้าทั้ง 4 ครั้ง) เคสถัดไป 0.1–0.4 วินาที | E1 |
| ผู้ช่วยแนะนำแหล่งเรียนบนหน้าเว็บจริง หาหัวข้อถูก | 2 จาก 48 ข้อ เพราะหน้าเว็บยังใช้ AI จำลอง (Typhoon ได้ 46 จาก 48) | E3 |
| คำตอบของคนต่อคำถาม "เข้าใจถูกไหม" | ไม่ได้เก็บ | E4 |
| แหล่งเรียนภาษาไทยในคลัง | 1 จาก 17 แหล่ง | E6 |
| คำตัดสินของคนตรวจที่บันทึกไว้ | 0 เพราะยังกดอนุมัติไม่ได้ (ขั้น 2 ของแผนงานหลัก) | ขั้น 2 |

**งาน 6 ชิ้น เรียงตามลำดับที่แนะนำ**

| ลำดับ | งาน | ผมทำอะไร | คุณทำอะไร | คุณจะได้ลองอะไร |
|---|---|---|---|---|
| E1 | เคสแรกหลังระบบตื่นเร็วขึ้น | ให้เครื่องแปลโค้ดไว้ล่วงหน้าตอนสร้าง (bytecode) แทนการแปลใหม่ทุกครั้งที่เริ่ม แล้ววัดเวลาจริงบน Render | สั่งรวม (merge) | เปิดหน้าเว็บหลังทิ้งไว้ 20 นาที ส่งเคสตัวอย่าง แล้วดูว่าขึ้น "รอคนตรวจ" เร็วขึ้นจากเดิมราว 10 วินาทีไหม |
| E2 | กฎรุ่น 2 ที่อ่านภาษาไทยได้ | เพิ่มคำสำคัญภาษาไทย จับคำเป็นคำ (ไม่หลงกับคำที่ซ่อนในคำอื่น) และวัดกับชุดเคสใหม่ที่ไม่เคยใช้ปรับกฎ | ดูผลในหน้า Actions แล้วสั่งรวม | พิมพ์เคสภาษาไทย เช่น "ลืมรหัสผ่าน เข้าระบบไม่ได้" ข้อเสนอหลักต้องเป็น "เข้าระบบ / บัญชี" (เดิมเป็น "เรื่องอื่น ๆ") |
| E3 | ให้หน้าเว็บจริงใช้ AI จริง | เตรียมขั้นตอน ตรวจหลังเปิด และวัดความเร็วจาก Render | **ตัดสินใจ** แล้วเพิ่ม 2 แถวใน Render (ฟรี แต่ข้อความที่พิมพ์จะถูกส่งไป Typhoon จึงพิมพ์ได้เฉพาะข้อมูลสมมุติ) | พิมพ์ "อยากให้ระบบเป็นเหมือนบรรณารักษ์ที่รู้ใจ" แล้วได้แหล่งเรียนแทนคำว่า "อยู่นอกกรอบ" |
| E4 | เก็บคำตอบ "เข้าใจถูกไหม" | เพิ่มปุ่ม "ใช่ ตรง" กับ "ไม่ตรง" ใต้คำตอบ แล้วนับผลให้เห็น | สั่งรวม | กดปุ่ม แล้วเห็นตัวนับในแท็บ "ตั้งค่า" |
| E5 | ให้ AI แยก "อื่น ๆ" ได้ดีขึ้น และบอกความไม่แน่ใจที่ใช้ได้จริง | วัดกับข้อสอบกลางก่อน (ขั้น 5.6) แล้วปรับคำสั่ง (prompt) รุ่นใหม่ วัดก่อนและหลัง | อ่านคำขอก้ำกึ่งราว 20 ข้อ แล้วบอกว่าคุณจัดหมวดไหน (คุณเป็นคนกลางคนแรกที่ตรวจเฉลย) | ตารางเทียบก่อนและหลังในหน้า Actions |
| E6 | คลังแหล่งเรียนที่มีภาษาไทยมากขึ้น | เสนอแหล่งเรียนใหม่ทีละหัวข้อ และให้ GitHub ตรวจทุกลิงก์ | เปิดอ่านแหล่งที่ผมเสนอ แล้วบอกว่ารับหรือไม่รับ | ถามเป็นภาษาไทยแล้วได้แหล่งเรียนภาษาไทยมากกว่า 1 แหล่ง |

- **เริ่มได้ทันทีโดยไม่ต้องตัดสินใจอะไร:** E1 แล้ว E2
- **รอคุณตัดสินใจ:** E3 ทำได้ทุกเมื่อ ไม่ต้องรองานอื่น
- **หลัง E1–E2:** ผมแนะนำขั้น 2 ของแผนงานหลัก (ให้คนกดอนุมัติได้จริง) เพราะตอนนี้ทุกเคสจบที่ "รอคนตรวจ" แล้วไปต่อไม่ได้
  และคำตัดสินของคนคือเฉลยจากคนจริงชุดแรกของโปรเจกต์ คุณเป็นคนเลือกว่าขั้นไหนมาก่อน

**สิ่งที่ตั้งใจไม่ทำ และเหตุผล**

- **ไม่เพิ่มเครื่องหรือตัวรันงาน:** 7 วันที่ผ่านมาระบบจริงมี 3 งาน และงานที่ไม่ใช่เคสแรกใช้ 0.1–0.4 วินาที ระบบรับงานทันอยู่แล้ว
- **ยังไม่ให้ความเห็นของ AI เป็นข้อเสนอหลัก:** ในชุดทดสอบ AI ถูกบ่อยกว่ากฎมาก แต่ข้อตกลงเดิม (ADR-010) คือต้องเทียบกับคำตัดสินของคนก่อน
  (ขั้น 2.8) แล้วคุณเป็นคนตัดสิน (D6) E2 ทำให้ข้อเสนอหลักดีขึ้นโดยไม่เปลี่ยนบทบาทของใคร
- **ไม่ตั้งเป้าตัวเลขล่วงหน้า:** ทุกงานวัดก่อนและหลัง แล้วคุณเป็นคนบอกว่าพอหรือยัง

**แหล่งเรียน (จากคลังที่ตรวจแล้ว เรียงตามลำดับที่ควรอ่าน)**

1. **Building effective agents** (Anthropic) — https://www.anthropic.com/research/building-effective-agents — **อ่านก่อน**
   - ใช้ทำอะไร: หลักคิดว่าให้เริ่มจากแบบที่ง่ายที่สุด และเพิ่มความซับซ้อนเมื่อผลวัดบอกว่าจำเป็น ซึ่งเป็นวิธีของแผนนี้
   - ระดับกลาง ภาษาอังกฤษ อ่านส่วนที่แยกงานลำดับตายตัว (workflow) กับผู้ช่วยที่ตัดสินใจเอง (agent) ก่อน
2. **CLINC150** (Larson และคณะ) — https://aclanthology.org/D19-1131/
   - ใช้ทำอะไร: วิธีวัดว่าระบบรู้ไหมว่าคำขอ "อยู่นอกกรอบ" ซึ่งเป็นจุดที่ AI ของเราพลาดทั้ง 12 ข้อ (E5)
   - ระดับลึก ภาษาอังกฤษ อ่านเฉพาะส่วนที่อธิบายวิธีวัดเรื่องนอกกรอบ ตัวเลขผลทดลองข้ามไปก่อนได้
3. **System Design Roadmap** (roadmap.sh) — https://roadmap.sh/system-design
   - ใช้ทำอะไร: แผนที่หัวข้อการออกแบบระบบ ใช้ทำความเข้าใจเรื่องความเร็วและการเริ่มทำงานของเครื่อง (E1)
   - ระดับกลาง ภาษาอังกฤษ เริ่มจากหลักพื้นฐาน ยังไม่ต้องลงรายละเอียดเทคโนโลยี

## What "effective" means here

A case or a question is handled effectively when the person gets a right, useful answer quickly, nothing is
lost on the way, and there is a record that shows it. The project already measures robustness (what never
breaks) and model quality on synthetic sets. This plan follows the numbers a person meets when using it.

| # | Measure | Now (measured) | Where it is recorded | Moved by |
|---|---|---|---|---|
| M1 | The official suggestion (rules) is correct | 29/61, Thai 7/26; edge set 48/116, Thai 3/13 | mock scorecard on every CI run; [baseline](evidence/2026-11-10-effectiveness-baseline.md) | E2 |
| M2 | Share of cases raised for review first, with a real model | 33/61 and 64/116 (Typhoon) | [2026-11-06](evidence/2026-11-06-first-live-typhoon.md), baseline | E2 |
| M3 | Rule mistakes that are raised, with a real model | 32/32 and 60/68 (Typhoon); 30/32 and 26/68 with the mock, as on the online page | same | E3, E5 |
| M4 | Cases wrong for both rules and AI, so nothing raises them | 0/61 and 8/116 (Typhoon) | same | E5 |
| M5 | The AI at the edge of `other` | 17/29 right on `other`, 87/87 on the three categories (Typhoon, edge set); `high` confidence on 116/116 | baseline | E5 |
| M6 | First job after a start | 9.0 to 10.5 s in 4 of 4 observations; later jobs 0.1 to 0.4 s | [2026-11-03](evidence/2026-11-03-render-operations.md), baseline (Honeycomb) | E1 |
| M7 | Study topic found on the online page | 2/48 (the page runs the mock); 46/48 with Typhoon | mock scorecard in CI; 2026-11-06 | E3 |
| M8 | Out-of-scope study requests caught, with a real model | 16/19, precision 16/17 (Typhoon) | 2026-11-06 | E5 |
| M9 | People's answers to "เข้าใจถูกไหม" | not recorded | – | E4 |
| M10 | Thai resources in the study library | 1 of 17 | `resources_v1.json` | E6 |
| M11 | Review decisions recorded | 0: a case ends at `REVIEW_REQUIRED` and nothing else can happen | – | Phase 2 |

A package that moves a number updates this table and writes the new figure in an evidence note. All sets are
synthetic or open-dataset text with the developer's labels, so these are measurements of this system on
these sets, not accuracy.

## What the baseline says

1. **The weak part of triage is the official suggestion, not the second opinion.** The rules are right on
   29/61 and 48/116; Typhoon on 60/61 and 104/116. The rules know 10 English keywords and no Thai.
2. **Because the rules are wrong so often, "elevated" marks more than half of all cases** (33/61, 64/116).
   The flag is correct almost every time (32/33, 60/64), but a flag on every second case orders little.
3. **The online page gets much less than the measurements show**, because it runs the mock: it finds the
   study topic for 2/48 requests (Typhoon 46/48), and on the hard triage set it would raise 26 of the rules'
   68 mistakes (Typhoon 60).
4. **The first case after a start takes about 10 s**, and on the free plan the service sleeps after 15 idle
   minutes, so a visit after a pause begins with a start: both triage cases of the last 7 days did. The
   time goes into starting worker processes.
5. **Nothing a person does after reading an answer is recorded:** no review decision (Phase 2) and no answer
   to "เข้าใจถูกไหม". The project therefore has no number from real use.
6. **Capacity is not a limit.** The online service ran 3 jobs in the last 7 days, a warm job takes 0.1 to
   0.4 s, the queue wait is about 0.4 s, and Sentry lists no unresolved issue.

## The work packages

Each package is one pull request unless it says otherwise, and follows the definition of done in CLAUDE.md §5.

### E1 First case after a start: seconds, not ten

- **Goal:** the first case after the service wakes is answered in a few seconds.
- **Why (M6):** 4 of 4 first jobs took 9.0 to 10.5 s. The spans put it in the first two steps, which is where
  Core starts its worker processes. The image has no bytecode cache for `app/` and `neuron_flow/`
  (`PYTHONDONTWRITEBYTECODE=1`, no compile step, a code folder the service cannot write to), so every new
  Python process compiles what it imports. In a cloud session a fresh process importing the Runner's modules
  took a median of 116 ms with a full cache and 434 ms with none. A worker start on Render (4.2 to 5.8 s by
  this reading) is also within a factor of about 2 of Core's 10 s start limit; a worker that misses the
  limit fails its step, and the rules step has one attempt.
- **Tasks:**
  1. In the *Service container* job, show what the image has today: whether cache files exist for a sample
     of standard-library, `app` and `neuron_flow` modules, and how long `import app.services.runner` takes in
     a fresh process. This settles the one fact the baseline could not check (the base image's standard
     library).
  2. In the `Dockerfile`, compile `neuron_flow/` and `app/` at build time, and the standard library if it has
     no cache (`python -m compileall` with an invalidation mode that does not depend on file times). Keep
     `PYTHONDONTWRITEBYTECODE=1`: the service must not write into its code folder. Record the image size
     before and after.
  3. The container check fails when a module of `app/` or `neuron_flow/` has no cache file in the image. It
     reports the first job's time after the container starts; it does not gate on a time.
  4. After the merge, read the first job's `run` span in Honeycomb after the deploy and after one sleep,
     and write both next to the 9.0 to 10.5 s in an evidence note.
  5. Only if the owner still finds the first case slow: start the workers when the Runner starts instead of
     at the first case. Write up the two ways first: a warm-up job through Core (no Core change, one extra
     job record per start), or a small Core method that starts workers ahead (a Core change, so an ADR and
     the owner's yes first; rule 1).
- **Done when:** the evidence note has the times before and after from Render, and the check is in CI.
- **Owner test (ไทย):**
  1. หลังสั่งรวมและ Render ขึ้นเวอร์ชันใหม่ ทิ้งหน้าเว็บไว้ 20 นาทีให้ระบบพักเครื่อง
  2. เปิดหน้าเว็บใหม่ รอจนใช้งานได้ ส่งเคสตัวอย่าง 1 เคส แล้วกด "ยืนยันและส่ง"
  3. นับเวลาจนขึ้น "รอคนตรวจ" เดิมใช้ราว 10 วินาที เวลาจริงหลังแก้ผมจะอ่านจาก Honeycomb แล้วจดไว้ให้
- **Don't:** change Core without an ADR; promise a time before it is measured on Render; add a dependency.

### E2 Rules v2: an official suggestion that reads Thai

- **Goal:** the suggestion a reviewer sees first is right far more often, in Thai and in English, and
  "elevated" marks the cases that need a first look.
- **Why (M1, M2):** rules correct 29/61 (Thai 7/26) and 48/116 (Thai 3/13). A longer list with Thai words,
  the mock's, scores 74/116 on the edge set, which that list had not seen. The rules are also all a reviewer
  gets when the AI is unavailable (ADR-012). This package is also the decision for the 27 rules gaps of
  roadmap 5.5.
- **Design:**
  - Keywords become versioned data (a JSON file next to the rules, one SHA-256), as prompts are. The output's
    `rule_version` names the list and its hash, and the rules agent gets a new version, so a job frozen
    under the old rules fails as `configuration_changed` (ADR-015).
  - Text is normalised for matching only (Unicode NFKC, lower case, zero-width and soft-hyphen characters
    removed); the stored case text does not change. English keywords match whole words, so "design in" is
    not "sign in" and the city "Billings" is not "billing". Thai keywords match inside the text, because
    Thai is written without spaces.
  - Still rules: deterministic, fixed precedence, no AI and no new dependency. What a list cannot do stays
    a documented limit and is measured (negation, the meaning of a sentence).
  - Decide and write down whether the `case_triage.v1` workflow keeps `keywords-v1` as the original
    demonstration or moves too.
- **Measured honestly:**
  1. Before the rules change, add a held-out set in its own commit: about 40 new cases, half of them Thai,
     written from the category definitions and not from any keyword list. It is never used to tune.
  2. Develop rules v2 on the 61-case set and the robustness gaps.
  3. Report rules v1 against v2 on three sets, each named for what it is: the 61 cases (development, so
     inflated), the 116 edge cases (partly development), the held-out set (the honest one). For each: rules
     correct, and with Typhoon as the second opinion the share raised, rule mistakes raised and cases wrong
     for both.
  4. Regenerate `tests/baselines/shadow_eval_mock.json` and `tests/baselines/robustness_v1.json`, and say
     which items changed and why.
- **Done when:**
  - the three-set table is in an evidence note, with one Typhoon run of each set;
  - no case that rules v1 got right is wrong with v2, unless it is listed with the reason;
  - tests cover normalisation, whole-word matching, Thai, precedence and determinism;
  - each of the 27 rules gaps is marked fixed or kept as a known limit.
- **Owner test (ไทย):**
  1. เปิด PR กดแท็บ Checks เลือก *Core logic tests* (3.12) แล้วกด Summary บรรทัด "กฎเดิมจัดหมวดถูก" ต้องสูงกว่า 29/61
     และตาราง "แยกตามภาษา" แถวภาษาไทยต้องสูงกว่า 7/26
  2. หลังสั่งรวม เปิดหน้าเว็บ พิมพ์เคส "ลืมรหัสผ่าน เข้าระบบไม่ได้" แล้วกดยืนยัน ข้อเสนอหลักต้องเป็น "เข้าระบบ / บัญชี" (เดิมเป็น "เรื่องอื่น ๆ")
- **Don't:** tune on the held-out set; change a label in the same pull request; let the rules or the AI
  decide anything; call the result accuracy.

### E3 A real model behind the online page (the owner's decision; roadmap 0.4 and D7)

- **Goal:** what the owner tries on the page is what the measurements describe.
- **Why (M3, M7):** the page runs the mock. Study topics: 2/48 with the mock, 46/48 with Typhoon. Hard triage
  cases: the mock raises 26 of the rules' 68 mistakes, Typhoon 60.
- **The options:**

  | Option | Cost | What leaves the service | Status |
  |---|---|---|---|
  | Stay on the mock | none | nothing | today |
  | Typhoon through its API | free within rate limits | everything typed on the page goes to SCB 10X, which collects usage data, so synthetic text only | steps ready (roadmap 0.4) |
  | The local open model on a paid machine | a monthly price, checked at the time | nothing | owner decision D7 |
  | Claude | paid per use | everything typed goes to Anthropic | owner decision D2 |

- **Tasks when the owner chooses Typhoon:**
  1. The owner adds `NEURON_FLOW_LLM_PROVIDER=typhoon` and `TYPHOON_API_KEY` as two new rows in Render's
     Environment tab, and leaves `NEURON_FLOW_ACCESS_KEY` alone (CLAUDE.md §7).
  2. Check `/v1/status`, the Render log and Sentry. Check that the page says, while a real provider is on,
     that only synthetic text may be typed; add the sentence first if it is missing.
  3. Submit the page's examples and read the AI call's span in Honeycomb. This is the first latency of a real
     model measured from Render; write it in an evidence note.
- **Done when:** the owner test passes and the note exists.
- **Owner test (ไทย):**
  1. เพิ่ม 2 แถวใน Render ตามขั้นตอนในแท็บ "ตั้งค่า" ของหน้าเว็บ (หัวข้อ "AI ที่ใช้อยู่") แล้วรอระบบเริ่มใหม่
  2. มุมซ้ายล่างของหน้าเว็บต้องไม่ขึ้นว่า "AI จำลอง" แล้ว
  3. กด "อยากเรียน" พิมพ์ "อยากให้ระบบเป็นเหมือนบรรณารักษ์ที่รู้ใจ" ต้องได้แหล่งเรียนไม่เกิน 5 แหล่ง แทนคำว่า "อยู่นอกกรอบ"
- **Don't:** type real personal data on the page; put a key in `render.yaml`, a file or a chat; present
  what the page answers as Claude's.

### E4 Record the answer to "เข้าใจถูกไหม"

- **Goal:** the first number that comes from use, not from a test set.
- **Why (M9):** every study answer asks "did I understand you?" (67/67 on the scorecard), and the page offers
  only "แก้คำถาม". The answer is the cheapest honest signal there is, and today it is thrown away. At the
  last 7 days' rate of 3 jobs it will be a small number; it is still the only one of its kind.
- **Design (an ADR first, because it adds a write after a job has ended):**
  - Two buttons under the restatement, "ใช่ ตรง" and "ไม่ตรง".
  - `POST /v1/jobs/{job_id}/feedback` with `{"understood": "yes"}` or `"no"`, only for a finished job of an
    informational workflow (ADR-018). It is stored as a queue event; a repeat replaces the earlier answer.
  - No free text, so no personal data and no case text can arrive this way (rule 9).
  - `/v1/status` and the settings tab count yes, no and unanswered over the newest 100 study jobs.
  - The trace gets one allow-listed attribute, so the count survives the free plan's restarts.
  - The study scorecard is unchanged: this is a number from use, kept apart from test-set numbers.
- **Done when:** tests cover the access key, a job in the wrong state (409), a repeat, a body with any other
  field (400), the counts and the trace allow-list.
- **Owner test (ไทย):**
  1. กด "อยากเรียน" ถามคำถามตัวอย่าง แล้วกด "ใช่ ตรง" หรือ "ไม่ตรง" ใต้ประโยค "เข้าใจถูกไหม"
  2. เปิดแท็บ "ตั้งค่า" ต้องเห็นตัวนับ "เข้าใจถูก … จาก …"
- **Don't:** use it as a triage label (a reviewer's decision belongs to roadmap 2.2); collect free text.

### E5 The edge of "other", and a confidence that means something

- **Goal:** fewer needless raises and fewer cases that are wrong for both, and a warning signal that works.
- **Why (M4, M5, M8):** all 12 of Typhoon's mistakes on the edge set are requests labelled `other` that it
  put into a near category, and it said `high` confidence for all 116 answers. The study guide caught 16/19
  out-of-scope requests; two were pulled in by one word. The local model said `high` for 67/67 topic answers.
- **Tasks:**
  1. Roadmap 5.6 first. Its open sample measures the same edge on text nobody in this project wrote.
  2. The owner as the first independent labeller: about 20 borderline requests, the 12 above among them,
     shown without any answer. The owner picks a category for each. The note records how often the owner
     and the developer's label agree. Labels change only by this route, in their own commit.
  3. New prompt versions for triage and for topic detection: say when `other` or out of scope is the right
     answer, with examples that are in no test set. Replace the self-reported confidence with something
     that can be checked; candidates are a second-choice field, or two calls compared. Choose by measurement.
  4. Every prompt change is a new agent version, measured before and after on every set with Typhoon and
     with the local open model (roadmap 5.8).
- **Done when:** the before and after table is in an evidence note, with needless raises and cases wrong for
  both.
- **Owner test (ไทย):**
  1. อ่านคำขอก้ำกึ่งราว 20 ข้อที่ผมส่งให้ แล้วบอกว่าแต่ละข้อคุณจัดเป็นหมวดไหน (ใช้เวลาราว 10 นาที)
  2. หลังผมปรับคำสั่ง (prompt) เปิดหน้า Actions ของรอบวัด ต้องเห็นตารางเทียบก่อนและหลัง
- **Don't:** quote a test item in a prompt; change a label to make a model right; set a target before 5.6's
  first run.

### E6 A study library that serves Thai readers

- **Goal:** a Thai question gets Thai resources, and every topic has a place for a beginner to start.
- **Why (M10):** an answer can only be as useful as the library. It has 17 resources, 1 of them in Thai;
  `plain_language` has only a standard whose full text is paid, and `recommender_systems` only an advanced
  report (roadmap 3.1). The guide puts the person's language first, and for Thai there is one resource.
- **Tasks:**
  1. Add a measure to the study scorecard first: of the requests in Thai that got a plan, how many got at
     least one Thai resource. Record today's value before changing the library.
  2. For each topic, propose candidates: one for beginners, and one in Thai where one exists. The session
     cannot open most sites, so the owner opens and reads each candidate, and *Study library link check*
     opens every link on the pull request.
  3. A changed library is a new library tag and so new agent versions (ADR-019). Regenerate
     `tests/baselines/study_guide_eval_mock.json` and say why.
- **Done when:** every topic has a beginner resource; the Thai count and the new measure are recorded
  before and after.
- **Owner test (ไทย):**
  1. เปิดลิงก์แหล่งเรียนที่ผมเสนอทีละแหล่ง แล้วบอกว่ารับหรือไม่รับ
  2. หลังสั่งรวม กด "อยากเรียน" ถามเป็นภาษาไทย แล้วดูว่าได้แหล่งเรียนภาษาไทยมากขึ้น
- **Don't:** add a link that nobody opened; guess a link; show more than 5 resources.

## Order, and how it fits the roadmap

| When | What | Needs |
|---|---|---|
| Any time | E3 | the owner's decision; no code |
| First | E1 | – |
| Second | E2 | – |
| Then | Phase 2 of the roadmap (2.1 to 2.4), or Phase 4, as the owner chooses | D1 for real use of Phase 2 |
| With either phase | E4 | an ADR |
| After roadmap 5.6 | E5 | 5.6; about 10 minutes of the owner's time |
| When the owner has time to read candidates | E6 | the owner reads each candidate |

- E1 and E2 change code the service runs, so each merge redeploys Render and the free plan's queue is wiped.
- **Phase 2 is the largest step for effectiveness that is already on the roadmap** (M11). Until a reviewer
  can decide, a case cannot finish, and there are no labels from a person. E2 makes those reviews lighter;
  2.8 then measures the rules and the AI against reviewers' labels, which is what D6 needs.

## Not in this plan, and why

- **More workers, another machine, Postgres.** Capacity is not the limit (point 6 above; rule 10).
- **Making the AI's answer the official suggestion.** On these sets Typhoon is right far more often than the
  rules, but ADR-010 keeps the rules official until measurements against people's labels justify more (2.8),
  and then the owner decides (D6).
- **Targets.** The first measured run of each package comes first; then the owner says what is enough.
- **Tuning anything on a test set.** A change that fits the test items measures nothing.
