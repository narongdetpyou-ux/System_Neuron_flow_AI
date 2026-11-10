# The first independent review: four findings and what was done (2026-11-10)

## สรุปสำหรับเจ้าของโปรเจกต์

ผู้ตรวจสอบอิสระอ่านโค้ดและเอกสารบน `main` ที่ commit `f38c926` (เน้นความเสี่ยงด้านข้อมูลและความปลอดภัย ไม่ได้ทดสอบระบบบน Render) แล้วพบ 4 ข้อ คุณสั่งให้แก้ทุกข้อ ผลคือ:

| ข้อ | ผู้ตรวจบอกว่า | ทำอะไรไปแล้ว | เหลืออะไร |
|---|---|---|---|
| 1 | อีเมลส่วนตัวยังอยู่ใน 51 commit ของประวัติสาธารณะ | ตรวจแล้วพบว่า **ยังเพิ่มขึ้น** เป็น 53 เพราะทุกครั้งที่กด Merge บน github.com ใช้อีเมลนั้น จึงเพิ่มช่องตรวจอีเมลใน commit ใหม่ และทดลองเขียนประวัติใหม่บนสำเนาในเครื่อง (ไม่ได้ส่งขึ้น GitHub) | คุณตั้งค่า 1 อย่างใน GitHub เพื่อหยุดของใหม่ และตัดสินใจเรื่องของเก่า (D8) |
| 2 | ด่านปิดข้อมูลส่วนตัวเชื่อแค่ "ชนิด" ของข้อความ ซึ่งโค้ดอื่นสร้างปลอมได้ | ตัวกลางเรียก AI ปิดข้อมูลซ้ำเองก่อนส่ง ถ้ายังเจอจะไม่ส่ง และสร้างข้อความ "ปิดแล้ว" ปลอมไม่ได้ ระหว่างทำเจอว่ากฎเดิมปิดซ้ำแล้วได้ผลต่างจากเดิม จึงแก้เป็นกฎรุ่น 2 | ไม่มี (กฎยังจับได้เฉพาะรูปแบบที่รู้จัก เหมือนเดิม) |
| 3 | ตอบ "รับแล้ว" ไม่ได้แปลว่าเคสจะอยู่ (แผนฟรีไม่มีดิสก์) | ระบบและหน้าเว็บบอกตรง ๆ ทุกครั้งที่บันทึก ไม่พูดว่า "ถาวร" บนที่เก็บชั่วคราว และบอกว่าเคสที่คุณส่งหายไปกี่รายการเมื่อระบบเริ่มใหม่ | ทำให้ไม่หายจริงต้องใช้แผนเสียเงินพร้อมดิสก์ (D1) |
| 4 | ไม่มีทางให้คนอนุมัติหรือปฏิเสธเคส | สร้างการตัดสินแล้ว (ขั้น 2.2, 2.4): ปุ่มอนุมัติ/ไม่อนุมัติพร้อมเหตุผล และรายการ "รอรีวิว" | รหัสผู้ตรวจรายคน (2.1) และงานต่อเนื่องหลังอนุมัติ (2.3) |

ทุกอย่างอยู่ใน pull request เดียว เพราะ session นี้ส่งงานได้ทาง branch เดียว แต่แยก commit ตามข้อ

## The review

- **Read on:** `main` @ `f38c926` (2026-11-10), code and docs, with a focus on data and security risks. The
  reviewer did not test the service on Render. This is not yet roadmap 7.3: there is no threat model, and the
  running service was not tested.
- **Answered on:** the branch `claude/hopeful-volta-a6wfa4`, in one pull request with one commit per finding
  (the session could push to one branch only). Tests: 392 on Python 3.13 in this session; CI runs them on 3.10 and 3.12.

## 1. A personal e-mail address in the public history (rated high)

**Checked.** One of the owner's personal addresses is in the author or committer field of 53 commits on
`main` (59 fields). The audit before the repository went public (roadmap 7.4, 2026-11-08) counted 51. The two
new ones are the merges of PR #50 and #60, made on github.com after the switch: GitHub writes the account's
address into a web merge unless the account keeps its address private. So the exposure was still growing.

**Built.**
- `.github/scripts/check_commit_emails.py`, run as the `commit-emails` job of *Secret scan*. It checks the
  author and committer of the new commits against an allow-list (`…@users.noreply.github.com`,
  `noreply@github.com`, `noreply@anthropic.com`). A pull request fails; a push only warns, because a red check
  on `main` would stop Render's deploy-after-checks. Both report the count for the whole history. Addresses
  are never printed, only the domain (`<hidden>@gmail.com`). On this branch it reports 0 new and 53 in the
  history; run on `4b05bf7..f38c926` it flags the merge of PR #60.
- `tests/test_commit_emails.py` (7 tests, on a git repository made in the test).

**Dry run of a rewrite (local only; nothing was pushed).** A mirror of this repository was rewritten with
`git fast-export | filter | git fast-import`, replacing every address outside the allow-list with a private
GitHub address:
- 117 commits on all the refs of this session's clone, before and after; 59 fields changed; 0 personal addresses
  left;
- every commit's tree is identical, in the same order (the files are byte for byte the same);
- every commit id changes, because the first commit of `main` is one of the 53.

**Left to the owner.** The setting that stops new ones (GitHub → Settings → Emails → keep my email addresses
private), and decision D8 about the 53 already public, with three options and their costs in roadmap 7.6. A
rewrite needs a force-push of `main`, which only the owner can allow, and GitHub keeps the pull-request refs
until GitHub Support removes them. No rewrite reaches copies made since 2026-11-08.

## 2. The masking gate could be bypassed by code (design weakness)

**Checked.** As the reviewer said: `structured_answer()` checked `isinstance(case_text, MaskedText)`, and
`MaskedText` was a plain dataclass anyone could build with raw text. Both agents that call the AI did call
`mask()` first, so no current path sent raw text; the risk was future code.

**Built (ADR-028).**
- `MaskedText` is sealed: only `mask()` can make one (a module-private token), it is read-only, and copying or
  pickling it is refused.
- The gateway accepts only a `MaskedText` made under the current rules, reads its text once, masks that text
  again (`redaction.leftover`) and raises `UnmaskedText` before any request when the rules would still change
  anything. The message names the kinds and counts, never the values.
- A static test allows the networked providers only through the gateway, and checks that the connection
  probe (`.github/scripts/llm_probe.py`) sends only its fixed sentence, which has nothing to mask.

**Found while building it.** The re-check relies on "masking masked text again changes nothing", which the
module promised. Random strings showed it did not hold in `redact-v1`:

| Strings masked twice | `redact-v1` | `redact-v2` |
|---|---|---|
| 300,000 random strings, generator 1 (seed 7) | 44 changed | 0 |
| 900,000 random strings, generator 2 (seeds 0–5) | 1,718 changed | 0 |
| 6,920 strings from the robustness sets | 0 changed | 0 |

The causes, each now a test in `tests/test_redaction.py`:
- `นางสาว` + a name was masked again as `นาง` + the "name" `สาว` (over-masking; nothing leaked);
- `คุณZsMr Yaa`: the second name was found only on a second pass, so `redact-v1` let `Yaa` through;
- `Mr Smith0812345678`: the phone number glued to the name was masked only on a second pass, so `redact-v1`
  let it through.

`redact-v2` runs the rules again until nothing changes (at most 8 rounds) and never takes `สาว` after `นาง` for
a name. The last two are real gaps of `redact-v1` on glued text, now closed. All 61 triage answers, all 67 study
answers and every robustness outcome are unchanged (the eval gates and the robustness gate pass against their
baselines). Jobs admitted under `redact-v1` and interrupted by the deploy fail as `configuration_changed`, by
design (rule 5); on the free plan the deploy empties the queue anyway.

## 3. A 202 does not mean the case will stay (risk of loss)

**Checked.** As the reviewer said: on Render's free plan the data folder is lost on every sleep, restart and
deploy. ADR-002's "202 after the commit" protects against a crashed process, not a replaced container. The
page warned in its settings and welcome text, but the confirm card, the case view and the Flow panel said
"บันทึกถาวร" (saved permanently) on the free plan too.

**Built (ADR-029).**
- `retention` in `/v1/status`, in every new job's reply and in every decision's reply: whether storage survives a
  restart, what wipes it, and the queue database's `store_id` and start time (a random id written once).
- The page says "บันทึกถาวร" only when storage is persistent; it warns on the confirm card and on every waiting
  case; it keeps the ids (never the text) of the jobs it sent with the store id, and when the store id changes
  it says how many are gone.
- Checked in a headless browser on a local service with temporary storage: two cases sent, the data folder
  wiped and the service restarted; the page said the 2 cases were gone.

**Left.** Only a disk keeps cases (D1, the `0.5c-512mb` plan and a 1 GB disk, about $7.25 a month at Nov 2026
prices). No free durable store fits ADR-003 and the P2 list.

## 4. No way for a person to close a case (incomplete)

**Checked.** As the reviewer said: triage ended at `REVIEW_REQUIRED` with no decision route or button.

**Built (roadmap 2.2 and 2.4, ADR-027).** A review ledger in the queue database (schema 2, with a tested
upgrade), `GET /v1/reviews`, `GET /v1/reviews/{review_id}` and `POST /v1/reviews/{review_id}/decisions`, and on
the page a decision card on every waiting case and a "รอรีวิว" list, elevated first. Verified by
`tests/test_service_reviews.py` (28 tests): a decision applies once per version; 16 identical clicks make one
decision; 16 different decisions at once let one win; a failure injected mid-transaction leaves the decision,
the review and the job unchanged; no key or a wrong key is denied; the reason never reaches events or logs.
Checked in a headless browser on desktop and phone widths.

**Left.** Built before per-person tokens (2.1), so the reviewer recorded is the holder of the shared key, the
owner (D3's default). The linked follow-up job with a Core receipt after an approval (2.3) is not built. On the
free plan decisions vanish with the queue (point 3).

## Not claimed

- No security review in the sense of roadmap 7.3, no test against the running service on Render, and no change
  measured on Render: the deploy happens after the merge.
- The masking is still pattern-based; it misses names without a title, addresses and more (rule 9).
