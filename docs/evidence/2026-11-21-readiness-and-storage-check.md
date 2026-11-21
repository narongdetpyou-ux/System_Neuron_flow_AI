# Readiness and the storage check (roadmap 1.7): what was measured

## สรุปสำหรับเจ้าของโปรเจกต์

รายงานคุณภาพ 19 พ.ย. หน้า 4 พบ 2 จุด ทั้งสองแก้แล้วในขั้น 1.7 และวัดผลด้วยการรันระบบจริง (ใช้ AI จำลอง):

| เรื่อง | ก่อนแก้ (ที่ `main` @ `3a4b97f`) | หลังแก้ |
|---|---|---|
| ตั้งโฟลเดอร์ข้อมูลไว้ แต่ไม่ได้ต่อดิสก์ | ระบบเรียกว่า "ถาวร" | ระบบเรียกว่า "ชั่วคราว" พร้อมเหตุผล (`root_filesystem`) |
| ดิสก์ที่ต่อแยกจริง (volume ใน GitHub) | "ถาวร" | "ถาวร" (`confirmed`) ดูผลรันใน GitHub ข้างล่าง |
| เลือก Typhoon แต่ไม่ใส่คีย์ | `/healthz` ตอบ 200 และไม่มีอะไรบอกว่าเคสค้าง | `/healthz` ยังตอบ 200 (Render ไม่รีสตาร์ท) แต่ `/readyz` ตอบ 503 `blocked_config` และแจ้ง Sentry 1 ครั้ง |
| แก้ค่าแล้วเริ่มใหม่บนดิสก์เดิม | — | เคสที่รออยู่ถูกทำจนถึง "รอคนตรวจ" และ `/readyz` ตอบ 200 |

บน Render แผนฟรีตอนนี้ไม่มีอะไรเปลี่ยน นอกจากมีหน้า `/readyz` เพิ่ม ยังไม่เคยเห็นดิสก์จริงของ Render (ต้องรอ D1) จึงต้องดูแท็บ "ตั้งค่า"
หลังเปิดดิสก์ครั้งแรกว่าบอก "ถาวร"

## What was built

Roadmap 1.7, ADR-036 (one pull request, on the branch `claude/awesome-maxwell-hefztq`):
- `app.settings.check_storage` reads `/proc/self/mountinfo` at start and takes the longest mount point that holds the
  data folder; persistent only when that mount is not `/` and not `overlay`, `aufs`, `tmpfs`, `ramfs` or `devtmpfs`.
- `GET /readyz` (no key): 200 `idle` or `running`, otherwise 503 with `blocked_config`, `starting`, `not_alive` or
  `queue_unavailable`; only heartbeats written since this API process started count. `/healthz` is unchanged.
- A Runner blocked by its AI settings sends one Sentry event per start (`runner_blocked`, the error's class only).

## In this session (a cloud machine, Python 3.13, mock AI)

The machine is a virtual machine, not a container: its root filesystem is `ext4` on its own disk, and `/dev/shm` is a
`tmpfs`. Each scenario ran once, with `python -m app.serve` and `examples/service_smoke_test.py` on 127.0.0.1.

The report's own reproduction, again, at this branch (Typhoon chosen, `TYPHOON_API_KEY` not set, so nothing was sent
to Typhoon; `NEURON_FLOW_DATA_DIR` a scratch folder on the root disk):

```text
healthz: 200 {'ok': True, 'access_key': 'configured'}
readyz: 503 {'ok': False, 'state': 'blocked_config'}
runner: {'state': 'blocked_config', 'alive': True}
storage: {'kind': 'configured', 'persistent': False, 'check': 'root_filesystem', 'filesystem': 'ext4'}
retention: {'persistent': False, 'lost_on': ['sleep', 'restart', 'deploy']}
```

At `main` @ `3a4b97f` the same setup gave `storage: {'kind': 'configured', 'persistent': True}` and `retention:
{'persistent': True, 'lost_on': []}` ([the report's response](2026-11-19-quality-report-response.md#page-4-data-after-a-restart-and-the-runners-status)),
and there was no `/readyz`.

| Scenario | Result |
|---|---|
| Full smoke run (cases, duplicates, decisions, handoff, tokens, scorecard) on a folder of the root disk, `--expect-storage root_filesystem` | all checks passed; `/readyz` 200 `idle` before the first case |
| A folder on `/dev/shm`, `--storage-check temporary_filesystem` | `temporary_filesystem` (`tmpfs`); a new case's `retention.lost_on` is the free plan's list |
| Typhoon without a key, `--blocked` | `/healthz` 200, `/readyz` 503 `blocked_config`, the case admitted (202) and still `QUEUED` 3 s later |
| The same folder with the mock, `--after-fix` | `/readyz` 200 and the case `REVIEW_REQUIRED` |

In every run the access key never appeared in the service log. The folder on the root disk of a machine that is not a
container reads as `root_filesystem`: the check prefers calling real persistent storage temporary to the reverse.

## In CI (*Service container*)

The first run of the pull request's commit `bc83802` (push run 44878906932, job 136769646427, GitHub's
`ubuntu-latest`, Docker with its default storage driver), one run each, read from the job's log:

| Container | What the start found | The smoke test |
|---|---|---|
| `nf`, a named volume at `/var/data` (the main run) | `confirmed`, `ext4`, before and after `docker restart` | all checks passed, `/readyz` 200 `idle` |
| `nf-volume`, a fresh named volume | `confirmed`, `ext4` | a new case's retention persistent, `lost_on` empty |
| `nf-plain`, `NEURON_FLOW_DATA_DIR=/var/data` with no volume | `root_filesystem`, `overlay` | not persistent, `lost_on` the free plan's list |
| `nf-tmpfs`, `--tmpfs /var/data` | `temporary_filesystem`, `tmpfs` | not persistent |
| `nf-blocked`, a volume, Typhoon chosen and no key | (`confirmed`) | `/healthz` 200, `/readyz` 503 `blocked_config`, the case admitted and still `QUEUED`; the log says why; the key not in the log |
| `nf-fixed`, the same volume with the mock | (`confirmed`) | `/readyz` 200 `idle`, the waiting case `REVIEW_REQUIRED` |

The first-case timing container, started without a data folder, logged `storage=local_default, not_configured`.
A named volume on GitHub's runner is a bind of the host's `ext4` disk; Render's disk is a different thing, see the
first limit below.

## Limits

- No Render disk has been seen (D1). Render's disks are expected to appear as a mount of their own; the first deploy
  with one must show "ถาวร" in the settings tab, and the evidence for that is the owner's look at the page.
- The Sentry event is checked with a stub SDK only: CI has no DSN for the container runs, and this session sent nothing
  to Sentry.
- `/readyz` says whether the Runner can take work. It does not call the AI provider: a Runner whose AI calls fail at
  run time is still ready, and those cases go to review on the rules alone, as before (ADR-012).
- A blocked Runner never opens Core's workspace, so it holds no workspace lock. A second launcher on the same data
  folder could therefore start a working Runner beside it, and the two would share the queue's one heartbeat row. One
  container runs one launcher (ADR-014), so this needs a second service on the same disk; it was seen once in this
  session, when a test helper left a local service running, and the runs above were repeated after stopping it.
