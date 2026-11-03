# Render operations: graceful stops, deploy filter, sleep and cold start

**Date:** 2026-11-03 (observations from 2026-11-01 and 2026-11-03). **Environment:** Render web service
`neuron-flow` (`srv-dbjkoie7bikc73foui1g`), free plan, Singapore, mock AI (`mock/mock-keyword-1`).
**Source:** Render's deploys, events and app logs, read through the Render connector. All data in the
service was synthetic.

## สรุปสำหรับเจ้าของโปรเจกต์

- **ระบบปิดตัวอย่างเรียบร้อยแล้ว** ทุกครั้งที่ Render หยุดระบบ (ตอนขึ้นเวอร์ชันใหม่หรือตอนพักเครื่อง) ระบบบันทึกว่า "กำลังหยุด" และตัวรันงานหยุดหลังทำเคสปัจจุบันเสร็จ ไม่มีข้อความ FATAL อีกแล้ว
- **แก้แค่เอกสารไม่ทำให้ Render ขึ้นเวอร์ชันใหม่** การรวม 3 ครั้งที่แก้แค่เอกสารหรือ CI (PR #19, #20, #24) ไม่มีการขึ้นเวอร์ชันใหม่เลย ส่วนการรวมที่แก้โค้ดขึ้นเวอร์ชันใหม่ทุกครั้ง เคสในคิวจึงไม่หายเพราะการแก้เอกสาร
- **แผนฟรีพักเครื่องหลังไม่มีคนใช้ราว 15 นาที** และเคสแรกหลังเครื่องตื่นใช้เวลาราว 9–10 วินาที เคสถัดไปเร็วกว่ามาก

## 1. Graceful stops (roadmap 0.1, fix in PR #16)

Before PR #16, process 1 (tini) ran as root. Root in Render's containers lacks `CAP_KILL`, so tini could
not pass SIGTERM on to the service and logged `[FATAL tini (1)] Unexpected error when forwarding signal:
'Operation not permitted'`; the service was killed instead of stopped.

| When (UTC) | Image | What stopped it | Logged |
|---|---|---|---|
| 2026-11-01 15:26:41 | before PR #16 | free-plan sleep | the FATAL line above, no `serve: stopping` |
| 2026-11-01 15:43:45 | `23ca7df` (PR #16) | free-plan sleep | `serve: stopping (signal 15)`, then `runner: stopping after the current job (signal 15)`; no FATAL |
| 2026-11-03 00:05:35 | `adcb4b1` (PR #21) | replaced by the PR #22 deploy | `serve: stopping (signal 15)`, `runner: stopping after the current job (signal 15)` |
| 2026-11-03 00:06:08 | `1a9c707` (PR #22) | replaced by the PR #23 deploy | `serve: stopping (signal 15)` |

A log search from 2026-11-03 00:04 to 00:22 UTC for `FATAL`, `Traceback`, `ERROR`, `error` and ` 500 `
returned nothing.

## 2. Docs-only merges do not deploy (roadmap 0.5, PR #15)

`render.yaml` sets `buildFilter.ignoredPaths` (`*.md`, `**/*.md`, `docs/**`, `tests/**`, `examples/**`,
`.github/**`, `.claude/**`). Render's deploy list for the service, compared with the merge commits on
`main`:

| Merge | Changed | Render deploy |
|---|---|---|
| #15 `1b94252` | `render.yaml`, CI, docs | deployed |
| #16 `23ca7df` | `Dockerfile`, `app/`, CI, tests, docs | deployed |
| #18 `5d9cde2` | `app/`, tests, docs | deployed |
| #19 `b684e7e` | docs only | **none** |
| #20 `1653009` | CI and docs only | **none** |
| #21 `adcb4b1` | `neuron_flow/`, tests, docs | deployed |
| #22 `1a9c707` | `app/`, tests, docs | deployed |
| #23 `54d32aa` | `app/`, tests, docs | deployed |
| #24 `0b03735` | tests and docs only | **none** |

The live deploy after these merges is `54d32aa` (PR #23), which contains all the code of PR #24's merge.
Render listed no `commit_ignored` events for the three skipped merges; the evidence is the absence of a
deploy for them.

## 3. Free-plan sleep and cold start (measured 2026-11-01)

- The service went to sleep 14 min 59 s after its last request, twice. Render's own `/healthz` checks,
  every few seconds, do not count as requests.
- The first job after a start took 9.8 s and 9.0 s (two starts). Later jobs took 0.1–0.4 s. In CI the same
  first job takes about 1 s.

## Limits

- One service, a few days, mock AI only. These are operational observations, not performance benchmarks.
- Times come from log timestamps, rounded as shown.
- The request-id lines (`req_…`) visible in the 2026-11-03 logs show PR #22 running on Render; they are not
  an owner test of the feature.
