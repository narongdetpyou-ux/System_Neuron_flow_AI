# Personal access tokens on the live page: the owner's test (roadmap 2.1)

**Date:** 2026-11-16. **Where:** Render's free plan, service `0.4.1+fb6546ddd831` (the merge of PR #72), mock AI,
read from Honeycomb (environment `test`, dataset `neuron-flow`). **What:** the owner test of roadmap 2.1 (ADR-034),
which the owner carried out and reported done. **Data:** synthetic cases typed by the owner.

## สรุปสำหรับเจ้าของโปรเจกต์

- **ผ่าน:** หลังระบบอัปเดต (14:22 น.) คุณสร้างรหัสผู้ตรวจ 1 รหัส ส่งเคส 3 เคส ตัดสิน 3 ครั้ง (2 ครั้งส่งต่องานบันทึกผลและเสร็จทั้งคู่)
  แล้วเพิกถอนรหัส คำขอแรกที่ใช้รหัสนั้นหลังเพิกถอนถูกปฏิเสธทันที (401) หน้าเว็บของผู้ตรวจจึงกลับไปหน้าใส่รหัส
- **ไม่มีคำขอที่ถูกปฏิเสธเพราะบทบาทไม่มีสิทธิ์ (403) เลย และไม่มีข้อผิดพลาดฝั่งระบบ (500):** หน้าเว็บซ่อนสิ่งที่บทบาททำไม่ได้ไว้ก่อนแล้ว
- **สิ่งที่ Honeycomb บอกไม่ได้:** ใครเป็นคนกดตัดสิน (เส้นทางงานไม่เก็บบทบาทหรือรหัสของผู้เรียก) และเคสไหนถูกยกให้ดูก่อน
  ส่วนนี้มาจากที่คุณเห็นบนหน้าเว็บ
- **ผลพลอยได้ (งาน E1):** เคสแรกหลังอัปเดตเวอร์ชันใช้เวลาทำงาน 2.9 วินาที (เดิม 9.0–10.5 วินาที) วัดได้ 1 ครั้ง

## Timeline (UTC; the page in Thai time is UTC+7)

The new version served its first request at 07:22:24. Spans of the new version only; every row is one span.

| Time | Span | Status | What it shows |
|---|---|---|---|
| 07:22:24 | `GET /v1/me` | 200 | the owner's page loaded and asked who it is |
| 07:22:53 | `GET /v1/tokens` | 200 | the owner opened "จัดการผู้ใช้" |
| 07:23:28 | `POST /v1/tokens` | 201 | one token issued |
| 07:24:23, 07:24:40 | `GET /v1/me` | 200 | a second page signed in (the private window) |
| 07:27:31 | `POST /v1/jobs` | 202 | case 1; `REVIEW_REQUIRED` after one claim, `run` 2,865 ms |
| 07:27:54 | `POST /v1/reviews/{review_id}/decisions` | 201 | decision 1; one `case_triage.v2.apply` job, `COMPLETED` in 37 ms |
| 07:29:06 | `POST /v1/jobs` | 202 | case 2; `REVIEW_REQUIRED`, `run` 298 ms |
| 07:29:18 | `POST /v1/reviews/{review_id}/decisions` | 201 | decision 2; one apply job, `COMPLETED` in 76 ms |
| 07:31:07 | `POST /v1/jobs` | 202 | case 3; `REVIEW_REQUIRED`, `run` 658 ms |
| 07:32:01 | `POST /v1/reviews/{review_id}/decisions` | 201 | decision 3; no apply job (what a rejection does) |
| 07:33:24 | `POST /v1/tokens/{token_id}/revoke` | 200 | the token revoked |
| 07:33:49 | `GET /v1/status` | 401 | the first request after the revocation that carried the token, refused |

- On the new version: 401 once (above), 403 never, 5xx never. Every `/v1` request in the window: 148 status reads,
  145 job lists, 21 inbox reads, 15 job and 15 event reads, 9 `/v1/me`, 4 token lists, and the writes above.
- The 25 seconds between the revocation and the 401 are the reviewer's page waiting while its window was in the
  background: the page does not poll while hidden and checks again when it is shown. The revocation itself held for
  the first request that carried the token.
- Before the new version was up, the old one (`45f27f4`) answered a `GET /v1/jobs/{job_id}` with 404 at 07:19:46:
  the page asked for the morning's case after the free plan had emptied the queue (ADR-029), as expected.

## What this shows, and what it does not

- **Shows:** on Render, a token was issued once, three cases ran and waited for a person, two approvals handed on and
  their apply jobs completed, the revocation applied at once, and no request was refused for its role.
- **Does not show who decided.** Spans carry the route, the status and the request id, never the caller's role or
  token (by design: no token reaches a trace). Which decision the reviewer's token made, and that the security case
  carried the "ด่วน" tag, rest on the owner's report that the test was done as written. Decision 3 handed nothing on, which is
  what a rejection does; the spans cannot tell a rejection from a refused handoff, and the page would have shown a
  red "ส่งต่อไม่ได้" box for the latter.
- **E1, right after a deploy:** case 1 was the first job of the new Runner process (its first span), five minutes
  after the deploy, without a sleep in between: `run` 2,865 ms (`classify_rules` 2,492 ms, `classify_llm` 1,115 ms,
  `screen` 281 ms, `compare` and `prepare` 14 ms each), `queue wait` 417 ms, `POST /v1/jobs` 13.0 ms. Recorded in the
  [E1 note](2026-11-10-e1-bytecode-cache.md).
- One owner, one session, synthetic text; on the free plan the tokens and the decisions are gone at the next sleep.
