# E1: a bytecode cache in the service image, before and after

**Date:** 2026-11-10. **Where:** GitHub Actions, the *Service container* workflow on the branch of PR #60,
one run before the change and one after; and a Claude Code cloud session for the local timings (Python
3.12.3). **What:** package E1 of the [effectiveness plan](../effectiveness_plan.md): the first case after a
start took 9.0 to 10.5 s on Render in 4 of 4 observations
([baseline](2026-11-10-effectiveness-baseline.md)). **Data:** two synthetic cases
(`examples/service_smoke_test.py`), the mock AI. **On Render** (added 2026-11-16): the first job after a
free-plan sleep, read from Honeycomb, is in the last section.

## สรุปสำหรับเจ้าของโปรเจกต์

- **สาเหตุที่คาดไว้ ยืนยันได้แล้วบนภาพจริงของบริการ:** ภาพที่ Render ใช้ไม่มีไฟล์ที่แปลไว้ล่วงหน้า (bytecode cache) เลย
  โมดูลที่ตัวรันงานต้องโหลด 141 ตัว มีไฟล์ที่แปลไว้ 0 ตัว รวมถึงส่วนที่มากับ Python เอง โปรแกรมทุกตัวที่เริ่มใหม่จึงต้องแปลโค้ดเองทุกครั้ง
- **สิ่งที่แก้:** ให้แปลโค้ดทั้งหมดครั้งเดียวตอนสร้างภาพ (ใน `Dockerfile`) ตอนนี้มีครบ 141 จาก 141 โมดูล
  และ GitHub จะไม่ให้ผ่านถ้าวันหนึ่งไฟล์ที่แปลไว้หายไปหรือไม่ตรงกับต้นฉบับ
- **ผลที่วัดได้บนเครื่องของ GitHub (ยังไม่ใช่ Render):**
  - เมื่อจำกัดกำลังเครื่องเหลือ 0.1 CPU เพื่อเลียนแบบเครื่องฟรีของ Render เคสแรกหลังบริการเริ่มทำงานใช้ **14.4 วินาที ก่อนแก้
    และ 3.1 วินาที หลังแก้**
  - ที่ความเร็วเต็มของเครื่อง GitHub: 1.0 วินาที ก่อนแก้ และ 0.3 วินาที หลังแก้
  - โปรแกรมใหม่ 1 ตัวเริ่มได้เร็วขึ้นราว 4 เท่า (ที่ 0.1 CPU: จาก 5.5 วินาที เหลือ 1.4 วินาที)
- **ราคาที่จ่าย:** ภาพของบริการใหญ่ขึ้นจาก 45.8 เป็น 54.2 MB และการสร้างภาพนานขึ้นราว 3 วินาที
- **วัดบน Render จริงแล้ว (16 พ.ย.):** เคสที่คุณส่งหลังระบบตื่นจากการพักเครื่อง เป็นเคสแรกของรอบนั้น
  ช่วงทำงาน (`run`) ใช้ **3.2 วินาที** จากเดิม 9.0 ถึง 10.5 วินาที แม้ตอนนี้เคสมี 5 ขั้นแทน 4 ขั้น วัดได้ 1 ครั้ง
  ตัวเลขละเอียดอยู่ท้ายบันทึกนี้ ส่วนเคสแรกหลังอัปเดตเวอร์ชันยังไม่มีให้วัด เพราะหลังอัปเดตทุกครั้งไม่มีใครส่งเคสก่อนระบบพักเครื่อง

## 1. What the image had (before)

Run [42819040092](https://github.com/narongdetpyou-ux/System_Neuron_flow_AI/actions/runs/42819040092), commit
`4d9c420`: the `Dockerfile` as on `main`, with only the report added
(`.github/scripts/check_image_bytecode.py`, run inside the image as the service user).

- No cache file for any of the 60 `.py` files under `app/` and `neuron_flow/`.
- A fresh process that imports `app.services.runner` loads 141 modules from source files: 38 of `app`, 4 of
  `neuron_flow` and 99 of the standard library. **None had a usable cache file.** This settles what the
  baseline could not check: the base image `python:3.12-slim` (Python 3.12.16 on that day) carries no cache
  for the standard library either.
- The service cannot repair this while it runs: `PYTHONDONTWRITEBYTECODE=1` is set, and the service user
  cannot write into the code folders. So the launcher, the Runner and every worker process compiled every
  module they imported, at every start.

## 2. The change

- `Dockerfile`: two `python -m compileall -f --invalidation-mode unchecked-hash` steps. The first, after
  `pip install`, covers the standard library and the installed packages; the second, after the last `COPY`,
  covers `neuron_flow/` and `app/`. `PYTHONDONTWRITEBYTECODE=1` stays, so the running service still writes
  nothing into its code folders.
- `unchecked-hash` (PEP 552): the cache file holds a hash of its source and Python uses it without reading
  the source again. It does not depend on file times, which a build tool or a copy can change. Its risk is
  a cache of older source being run as it is; the check below compares every cache file with its source.
- *Service container* now fails when a `.py` file under `app/` or `neuron_flow/` has no cache file or one
  whose stored hash is not its source's, or when a module the Runner imports has no usable cache. It
  reports the times below and does not gate on them. A later commit of the PR extends the same check to
  the installed packages: `sentry-sdk` is imported only when `SENTRY_DSN` is set, as on Render, so it is
  not among the 141 modules counted here.
- In this session the three invalidation modes started equally fast (median of 15 fresh processes: 152 ms
  by file time, 148 ms checked hash, 151 ms unchecked hash, 533 ms with no cache), so the mode was chosen
  for what it depends on, not for speed.

## 3. Before and after, in CI

Run [42819620612](https://github.com/narongdetpyou-ux/System_Neuron_flow_AI/actions/runs/42819620612), commit
`fa916b2`, is the run after the change. Each figure is from one run on a GitHub-hosted runner; the two runs
were on different runner machines.

| Measure | Before (`4d9c420`) | After (`fa916b2`) |
|---|---|---|
| `.py` files under `app/` and `neuron_flow/` with an exact cache | 0 of 60 | 60 of 60 |
| Modules the Runner imports with a usable cache | 0 of 141 | 141 of 141 |
| A fresh process importing the Runner's modules, 10 runs (min / median / max) | 471 / 476 / 499 ms | 115 / 120 / 136 ms |
| The interpreter alone, 10 runs | 15 / 16 / 16 ms | 10 / 10 / 11 ms |
| The same import held to 0.1 CPU, 5 runs | 5,495 / 5,501 / 6,303 ms | 1,396 / 1,399 / 1,502 ms |
| The interpreter alone at 0.1 CPU, 5 runs | 108 / 198 / 199 ms | 101 / 102 / 194 ms |
| First case after a start, at the runner's full speed (run time) | 0.989 s | 0.256 s |
| First case after a start, the container held to 0.1 CPU (run time) | 14.423 s | 3.135 s |
| Image size (`docker image inspect`, as the runner reports it) | 45,769,125 bytes | 54,180,344 bytes |
| *Build the image* step | 9 s | 12 s |

- "Run time" is the status figures' time from the Runner's first claim to the outcome (roadmap 5.3). All
  four first cases ended `REVIEW_REQUIRED`.
- `--cpus 0.1` is Docker's limit on GitHub's machine: a tenth of one processor, the share Render lists for
  its free instances (this session cannot open render.com to read it again). It imitates the size of the
  free instance, not its processor, disk or neighbours.
- With that limit the fresh-process import took 5.5 s before the change. The baseline's reading of the
  Render spans put a worker start at 4.2 to 5.8 s. The two agree, which supports the missing cache as the
  cause on Render; it does not prove it.
- Before the change the first case at 0.1 CPU ran for 14.4 s and Core's limit for one worker start is 10 s:
  a worker start there (about 5.5 s by the import time) was within a factor of 2 of failing the step.
  After the change it is about 1.4 s.

## 4. In the cloud session

`python -m app.serve` started three times with `PYTHONDONTWRITEBYTECODE=1` and `PYTHONPYCACHEPREFIX` set
to an empty folder, then three times with it set to a folder holding a full `unchecked-hash` cache; one
case per start (`examples/service_smoke_test.py --first-case-only`).

| Bytecode cache | First case after a start (run time, 3 starts) |
|---|---|
| None | 1.088 s, 1.096 s, 1.251 s |
| Full | 0.283 s, 0.296 s, 0.328 s |

## What this shows, and what it does not

- **Shows:** the image had no bytecode cache at all, and now has one for everything the Runner imports;
  the check that keeps it there is in CI.
- **Shows:** on the same code, the first case after a start was about 4 times faster with the cache in
  every setting measured here: 0.989 to 0.256 s at the runner's full speed, 14.423 to 3.135 s at 0.1 CPU,
  and about 1.1 to 0.3 s in the session.
- **Did not show the time on Render** when it was written. The 9.0 to 10.5 s there was measured on Render's
  machines with tracing on; nothing above was. The figure for Render, from the `run` span of the first job
  after a free-plan sleep (task 4 of E1), is in the last section.
- **Does not show a distribution.** One run before and one after, on shared runners.

## Limits

- The 0.1 CPU container is an imitation, as said above.
- The image size is the number Docker reports on the runner, not what Render stores or transfers.
- The session's Python is Ubuntu's 3.12.3, which ships its own cache; `PYTHONPYCACHEPREFIX` moved every
  lookup to the test folder so that "none" means none.
- The Render service was not touched: this branch is not deployed.

## On Render after the merge (2026-11-16)

| Start on Render | `run` span of the first job | Source |
|---|---|---|
| Before E1 (4 observations) | 9.0 to 10.5 s | [baseline](2026-11-10-effectiveness-baseline.md) |
| Right after a deploy that carries E1 (2026-11-16, PR #72) | **2,865 ms** (one observation) | Honeycomb, trace `d5c389ed450137969f0280ce5497a89a`; [the owner's test of 2.1](2026-11-16-personal-tokens-live.md) |
| After one free-plan sleep (2026-11-16) | **3,158 ms** (one observation) | Honeycomb, trace `c032092743134c895e53b59b0dc35e65` |

**The case.** The owner sent one synthetic case on the live page at 06:19:56 UTC, for the owner tests of 2.4, H3
and this note. It was the first job of the Runner process (`service.instance.id` `1573e02c…`, whose first span it
is) on a service the free plan had put to sleep: the dataset holds no span at all in the 7 days before the API
process's first span, at 06:19:27 UTC. The service ran `0.4.1+45f27f4659e3`, the merge of PR #67, which carries
E1's cache. Mock AI.

| Span | Before E1 (baseline: 2 first jobs; 3 jobs for the first two rows) | 2026-11-16, first job after a sleep |
|---|---|---|
| `POST /v1/jobs` (202) | median 12.8 ms, slowest 13.8 ms | 86.5 ms |
| `queue wait` | median 401 ms, slowest 423 ms | 354 ms |
| `job case_triage.v2` | 9,904 and 10,498 ms | 3,512 ms |
| ... `run` (first claim to outcome) | 9,480 and 10,097 ms | **3,158 ms** |
| ... `step classify_rules` | 9,393 and 10,012 ms | 2,699 ms |
| ... `step classify_llm` | 4,218 and 4,402 ms | 1,197 ms |
| ... `step screen` | no such step then | 393 ms |
| ... `step compare`, `step prepare` | at most 14 ms | 12 ms each |

- The job ended `REVIEW_REQUIRED` after one claim; the page showed "ใช้เวลา 3.2 วินาที".
- The workflow has had a fifth step since PR #67 (`screen`, ADR-032), so this job did more than the baseline's
  and still ran in about a third of the time. The step whose span covers the worker starts, `classify_rules`,
  went from 9.4–10.0 s to 2.7 s.
- The imitation in CI was close: 3.135 s with the container held to 0.1 CPU (section 3), on the four-step
  workflow of that day.
- The next job of the same Runner process, the handed-off `case_triage.v2.apply` after the owner's approval,
  ran in 42 ms: a warm job, like the baseline's later jobs (0.1 to 0.4 s).
- `POST /v1/jobs` took 86.5 ms, against 12.8 to 13.8 ms in the baseline. One observation, the API process's
  first case after a start; not investigated.
- **Right after a deploy** (added the same day): the owner's first case after the deploy of PR #72 (07:22 UTC) was
  the first job of the new Runner process, five minutes later and without a sleep between: `run` 2,865 ms
  (`classify_rules` 2,492 ms, `classify_llm` 1,115 ms, `screen` 281 ms, `compare` and `prepare` 14 ms each),
  `queue wait` 417 ms, `POST /v1/jobs` 13.0 ms. The same five-step workflow, so the two Render figures after E1
  are 2.9 s and 3.2 s.
- **Limits:** one observation of each start, synthetic cases with the mock AI, on Render's free instance as it was
  that minute. Task 5 of E1 (starting the workers ahead) was planned only if the first case still feels slow to the
  owner.
