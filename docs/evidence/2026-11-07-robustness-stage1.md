# First robustness benchmark run: open and synthetic edge cases (roadmap 5.4)

**Date:** 2026-11-07.

**Where:** a Claude Code cloud session, on the base commit `f115e0d` (`main`) plus this package's branch.
- Python 3.13.18 for the report below.
- The same run on 3.10.20 and 3.12.13 gave identical outcomes for every item and sweep (the gate passed on
  all three).
- *Core logic tests* repeated it on 3.10 and 3.12 in GitHub Actions for PR #41 (commit `8be76c7`), with the
  same outcomes and the gate passed: https://github.com/narongdetpyou-ux/System_Neuron_flow_AI/actions/runs/42396657165

**What ran:** `python -m tests.robustness.bench` (docs/benchmarking.md, stage 1).
- 270 synthetic items plus 73 open-dataset requests.
- 11 sweeps over 515 BLNS strings and 318 JSONTestSuite files.
- Offline: the mock AI and a local fake of the Typhoon HTTP API. No real model and no network.
- Full run 23.4 s; the fast layers alone 2.5 s.

**Data:**
- `synthetic_v1.json`, SHA-256 `df3b88fc…`.
- `open_extract_v1.json`, SHA-256 `510483c1…`, built from pinned upstream commits:
  - BLNS `db33ec7`;
  - JSONTestSuite `1ef36fa`;
  - CLINC150 `828f809`;
  - BANKING77 `57ec275`.
- `build_open_extract.py verify` downloaded every pinned file again from `raw.githubusercontent.com`, matched
  all SHA-256 values and rebuilt the extract byte for byte.

## สรุปสำหรับเจ้าของโปรเจกต์

- **เคสที่เขียนเอง 270 ข้อ ผ่าน 206** มีปัญหาร้ายแรง (bug) 8 จุด จุดอ่อน (gap) 45 จุด และข้อสังเกต (info) 11 จุด
- **กวาดข้อมูลเปิด 4,680 ครั้ง ไม่ผิดคำสัญญาเลย**
- **bug ทั้ง 8 จุดมาจากต้นเหตุ 2 อย่าง**
  1. ตัวเลขยาวเกิน 4,300 หลัก ทำให้ตัวอ่าน JSON ปล่อยข้อผิดพลาดที่ไม่ได้สัญญาไว้ ระบบจึงตอบ 500
  2. "ตัวอักษรพัง" (lone surrogate) ผ่านการตรวจเข้ามาได้ แต่เก็บลงฐานข้อมูลไม่ได้
     - ในคำขอ ระบบตอบ 500
     - ในคำตอบของ AI เคสทั้งเคสล้มและไม่ถึงคนตรวจ
- **ทั้งหมดแก้ได้นอก Core** อยู่ในขั้น 5.5
  - แก้คำ (8 พ.ย.): ข้อนี้ไม่ถูกทั้งหมด 7 จุดแก้นอก Core ได้ แต่ SYN-COR-040 ตรวจตัวอ่าน JSON ของ Core โดยตรง
    จึงต้องแก้ Core 1 ฟังก์ชัน (ADR-025) ดูหัวข้อ "Re-run after the fixes" ท้ายบันทึก
- **คำขอจาก CLINC150 และ BANKING77:** กฎคำสำคัญตรงกับป้ายที่ผู้พัฒนาจับคู่ไว้ 32/73
  - CLINC150 18/39
  - BANKING77 14/34
  - ป้ายเป็นการจับคู่ของผู้พัฒนา ไม่ใช่ความแม่นยำจริง

## Results by layer

Synthetic items. In the rules row, open requests are shown after the "+".

| Layer | Items | Passed | Bug | Gap | Info | Sweep checks | Sweep violations |
|---|---|---|---|---|---|---|---|
| intake | 60 | 52 | 4 | 3 | 1 | 1,984 | 0 |
| rules | 43 + 73 open | 16 + 32 open | 0 | 27 | 0 | 515 | 0 |
| masking | 50 | 32 | 0 | 10 | 8 (7 documented limitations) | 515 | 0 |
| ai_reply | 39 | 35 | 1 | 3 | 0 | 833 | 0 |
| core | 43 | 39 | 1 | 1 | 2 | 833 | 0 |
| e2e | 35 | 32 | 2 | 1 | 0 | – | – |
| **all synthetic** | **270** | **206** | **8** | **45** | **11** | **4,680** | **0** |

## Bugs (a stated promise breaks)

| Item | What happens | Root cause |
|---|---|---|
| SYN-INT-036, SYN-INT-037 | A request with a 5,000-digit integer (in an extra field, or as the summary) gets **500** `internal_error`, and the exception goes to Sentry, instead of 400 | `neuron_flow.model.decode` lets Python's int-digit limit `ValueError` through, which is not a `SpecError` (SYN-COR-040); `_submit` catches only `SpecError` |
| SYN-COR-040 | `decode()` of JSON with a 5,000-digit integer raises `ValueError`, not `SpecError` | as above; Core's contract says invalid JSON input is a `SpecError` |
| SYN-INT-038, SYN-INT-039 | A summary or a study message holding a lone surrogate (`\ud800`) gets **500** | `admit()` computes the request fingerprint outside the `SpecError` → `AdmissionError` conversion, and `encode()` refuses the surrogate |
| SYN-AIR-040 | A model reply whose rationale holds an escaped lone surrogate is **accepted** by `parse_answer` | the text fields are cleaned of control characters but not of surrogates, so the answer cannot be stored |
| SYN-E2E-029 | The same reply through the real Typhoon client path makes the **whole case fail** (`classify_llm` FAILED with `SpecError`, `prepare` blocked), with no retry, so the case never reaches a reviewer | Core cannot store the step's output; this breaks ADR-012 (an AI problem degrades to "rules only") |
| SYN-E2E-044 | The study guide fails the same way when the restatement holds a lone surrogate | the same gateway |

A model can be asked to write that escape by the case text itself, so SYN-E2E-029 is also an injection path:
one case can make itself fail instead of reaching review.

## Gaps and notes

- **Intake (3 gaps):**
  - 10 zero-width spaces are accepted as a case (SYN-INT-044), and so are 10 Thai combining marks with no
    consonant (SYN-INT-045), because the length is counted in code points.
  - A bidi override (U+202E) is stored as it is (SYN-INT-046), so the reviewer may read reversed text.
  - Note: the same visible text in NFC and NFD with the same idempotency key is a 409 conflict (SYN-INT-055).
- **Rules (27 gaps):**
  - No Thai at all (9 items).
  - Spelling variants and look-alikes: full-width letters, a zero-width space or soft hyphen inside a
    keyword, a Cyrillic "о", a Turkish "İ", "log in", "log-in", "sign-in", "up-load", "pasword" (10).
  - Words hidden in other words: "design in", "assign invoice" (2).
  - Negation (2).
  - "charged twice", "refund" and "logged in" without a keyword (3).
  - A Thai injection that contains the word "billing" sends the case to billing (SYN-RUL-040).
  - Open requests show the same pattern:
    - the city "Billings", salary "payment" and credit-score questions go to billing;
    - "sign out of my bank login" goes to access, and "upload the pictures to the correct album" to upload;
    - "passcode", "PIN", "locked", "declined", "refund", "charged" and "bill due" requests are missed.
- **Masking (10 gaps, 8 notes):**
  - Not masked: a phone with double spaces, with zero-width spaces or with slashes; an English name in all
    capitals or all lower case; "O'Neil"; an e-mail at a Thai domain (`.ไทย`); "somchai at example dot com";
    "my name is somchai".
  - "Mr McDonald" becomes "Mr [NAME]Donald".
  - Notes: a phone spelled out in Thai words, and 7 items the module's docs already list as not detected.
- **AI replies (3 gaps):**
  - A rationale with a bidi override is accepted as it is (SYN-AIR-041; through the whole system:
    SYN-E2E-030).
  - A rationale of zero-width spaces only, or an empty one, is accepted (SYN-AIR-042, SYN-AIR-043). The study
    guide already refuses empty text fields.
- **Core (1 gap, 2 notes):**
  - `decode()` of a Python `str` holding a lone surrogate raises `UnicodeEncodeError` (SYN-COR-041).
  - Notes: `1e400` decodes to infinity, which `encode()` later refuses (SYN-COR-045). NFC and NFD forms of the
    same text have different fingerprints (SYN-COR-051).

## Sweeps (all 0 violations)

- **BLNS as a case summary:** 384 of 515 accepted, 131 refused, no 5xx.
- **BLNS as a study message:** 456 accepted, 59 refused.
- **JSONTestSuite as the body, as `input` and as the summary:** every file got 400 or 413, never 5xx.
- **JSONTestSuite through Core's `decode()`:** only `SpecError` was ever raised.
  - 93 of 95 must-accept files were accepted. The other 2 are the duplicated-key files, which Core rejects
    on purpose.
  - 188 of 188 must-reject files were rejected.
  - Of the 35 either-way files, 26 were accepted. 16 of those hold values Core cannot store (lone surrogates,
    numbers that overflow to infinity), the class of input behind the bugs above.
- **BLNS as an AI rationale:** 499 accepted clean, 3 accepted with an empty rationale and 13 with invisible or
  direction characters left in.
- **Other sweeps:** the rules, masking (7 masked, idempotent) and fingerprints (stable) never broke a promise,
  and the shell canary `/tmp/blns.fail` never appeared.

## Exclusions and limits

- No real model was called. The AI's own judgement on these cases needs the manual live run
  (*Shadow eval with Typhoon*, `case_set: robustness_edge_v1`), which this session cannot reach.
- Open-dataset labels are the developer's mapping (tests/robustness/NOTICE.md), so 32/73 is not an accuracy
  figure.
- The synthetic items and their expectations are the developer's. No independent reviewer checked them.

## Re-run after the fixes (2026-11-08, roadmap 5.5, PR #42)

**Where:** a Claude Code cloud session, on `main` @ `26128e4` plus the branch `claude/fix-robustness-bugs`.
- Python 3.13.18 for the figures below.
- The same run on 3.10.20 and 3.12.13 gave identical outcomes for every item and sweep, and the gate passed on
  all three.
- Full run 25.6 s.

**Data:**
- `synthetic_v1.json` is now SHA-256 `e0fcba2d…`, because one expectation changed (SYN-AIR-040, below).
- `open_extract_v1.json` is unchanged (`510483c1…`).

### สรุปสำหรับเจ้าของโปรเจกต์

- **เคสที่เขียนเอง 270 ข้อ ผ่าน 215** (เดิม 206) ปัญหาร้ายแรง (bug) **0** (เดิม 8) จุดอ่อน (gap) 44 (เดิม 45)
  ข้อสังเกต (info) 11 เท่าเดิม
- **กวาดข้อมูลเปิด 4,680 ครั้ง ยังไม่ผิดคำสัญญาเลย** และได้ผลเหมือนรอบแรกทุกครั้ง
- **เคสที่ AI ตอบมีตัวอักษรพัง ถึงมือคนตรวจแล้ว** พร้อมความเห็นของ AI (ตัวอักษรพังกลายเป็นเครื่องหมาย �)
- **แก้คำพูดในบันทึกรอบแรก:** รอบแรกเขียนว่า "ทั้งหมดแก้ได้นอก Core" ซึ่งไม่ถูกทั้งหมด
  - 7 จุดแก้นอก Core
  - SYN-COR-040 ตรวจตัวอ่าน JSON ของ Core โดยตรง จึงผ่านได้ก็ต่อเมื่อแก้ Core (1 ฟังก์ชัน, ADR-025)

### What changed, item by item

Exactly 9 items changed in `tests/baselines/robustness_v1.json`: the 8 bugs and one gap.

| Item | Stage 1 | Now | Fix |
|---|---|---|---|
| SYN-INT-036, SYN-INT-037 | 500 `internal_error` | 400 `invalid_json` | `routes._submit` treats every `ValueError` from `decode()` as the client's input |
| SYN-INT-038, SYN-INT-039 | 500 `internal_error` | 400 `invalid_input` | `admit()` turns a `SpecError` from the request fingerprint into 400 |
| SYN-AIR-040 | accepted, with the lone surrogate kept | accepted, with the surrogate replaced by U+FFFD (`bad � text`) | `parse_answer` cleans lone surrogates out of free-text fields |
| SYN-E2E-029 | job `FAILED` at `classify_llm` (`SpecError`), never reviewed | `SUCCEEDED`, `PENDING_HUMAN_REVIEW`, second opinion `ok` | the same cleaning |
| SYN-E2E-044 | study guide job `FAILED` at `detect_topic` | `SUCCEEDED`: a guide of 2 steps, every link from the library | the same cleaning |
| SYN-COR-040 | `ValueError` escaped `decode()` | `SpecError` | ADR-025 |
| SYN-COR-041 (gap) | `UnicodeEncodeError` escaped `decode()` | `SpecError` | ADR-025 |

- No other item changed, and every sweep gave the same result as in stage 1.
- In the fake-Typhoon items (SYN-E2E-020 to SYN-E2E-033) the case now reaches review in 13 of 14. The one left
  is the rejected key (401, SYN-E2E-031), which fails loudly by design.

**One expectation changed, on purpose.** SYN-AIR-040 used to expect the answer to be refused (`invalid`), which
would have sent the case on as "rules only". The fix cleans the one character instead, because the rest of the
answer is valid and still passes every check; refusing would cost the case the AI's second opinion. The new
expectation is stricter about the text: the item fails unless the rationale is exactly `bad � text`, so
keeping the surrogate, or refusing the answer, both fail it.

**Without the Core commit:** the app fixes do not depend on ADR-025. Their unit tests pass with Core at 0.4.0, and
only SYN-COR-040 and SYN-COR-041 would fail again. If the owner does not want a Core change, that commit is dropped
and the baseline regenerated.

**Limits:** as in stage 1. No real model was called, and the items and their expectations are the developer's.
