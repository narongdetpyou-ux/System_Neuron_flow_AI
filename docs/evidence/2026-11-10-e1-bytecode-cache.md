# E1: a bytecode cache in the service image, before and after

**Date:** 2026-11-10. **Where:** GitHub Actions, the *Service container* workflow on the branch of PR #60,
one run before the change and one after; and a Claude Code cloud session for the local timings (Python
3.12.3). **What:** package E1 of the [effectiveness plan](../effectiveness_plan.md): the first case after a
start took 9.0 to 10.5 s on Render in 4 of 4 observations
([baseline](2026-11-10-effectiveness-baseline.md)). **Data:** two synthetic cases
(`examples/service_smoke_test.py`), the mock AI. **Not in this note yet:** a measurement on Render. That
needs the merge and a deploy, and is the last task of E1.

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
- **ที่ยังไม่รู้:** เวลาจริงบน Render ตัวเลขข้างบนวัดอย่างละ 1 รอบบนเครื่องของ GitHub
  หลังรวม (merge) ผมจะอ่านเวลาเคสแรกจาก Honeycomb แล้วจดต่อท้ายบันทึกนี้ เทียบกับ 9.0 ถึง 10.5 วินาทีเดิม

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
- **Does not show the time on Render.** The 9.0 to 10.5 s there was measured on Render's machines with
  tracing on; nothing here was. The figure for Render comes after the merge, from the `run` span of the
  first job after the deploy and after one sleep (task 4 of E1), and is added below.
- **Does not show a distribution.** One run before and one after, on shared runners.

## Limits

- The 0.1 CPU container is an imitation, as said above.
- The image size is the number Docker reports on the runner, not what Render stores or transfers.
- The session's Python is Ubuntu's 3.12.3, which ships its own cache; `PYTHONPYCACHEPREFIX` moved every
  lookup to the test folder so that "none" means none.
- The Render service was not touched: this branch is not deployed.

## After the merge (to be filled in)

| Start on Render | `run` span of the first job | Source |
|---|---|---|
| Before E1 (4 observations) | 9.0 to 10.5 s | [baseline](2026-11-10-effectiveness-baseline.md) |
| After the deploy of E1 | not measured yet | Honeycomb |
| After one free-plan sleep | not measured yet | Honeycomb |
