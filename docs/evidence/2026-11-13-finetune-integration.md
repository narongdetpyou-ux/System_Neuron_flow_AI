# Integrating the owner's fine-tuned Typhoon 4B into the local lane (ADR-034, roadmap 5.11)

**Date:** 2026-11-13. **Branch:** `claude/cool-einstein-w8k5v1`, PR #68 (first commit `27a51d9`). **Where:** this
cloud session (4 CPUs, 15 GB) and GitHub Actions. **Data:** synthetic only. **The owner's file:** not run yet (see 2).

## สรุปสำหรับเจ้าของโปรเจกต์

- **สร้างเสร็จและทดสอบแล้ว:** ระบบใช้โมเดลที่คุณปรับแต่งเองผ่านช่องทางโมเดลในเครื่องได้ โดยไม่แตะโค้ดบริการ (`app/`) และไม่แตะ Core
  กฎยังเป็นคำแนะนำทางการ และทุกเคสยังรอคนตัดสิน
- **ไฟล์ของคุณยังไม่ได้รันในระบบนี้:** Google Drive ที่เชื่อมกับ session นี้มองไม่เห็นโฟลเดอร์ `NeuronFlowAI/Typhoon4B_FineTuned_v01`
  (ไฟล์ล่าสุดที่เห็นคือวันที่ 8 พ.ย.) และเครือข่ายของ session นี้ต่อ Hugging Face หรือที่ดาวน์โหลดของ Google Drive ไม่ได้
  รอบแรกของไฟล์คุณจึงรอ secret `NF_MODEL_URL` ([วิธีใส่](../local_model_finetune.md))
- **ที่ตรวจแล้วจริง:** ตัวดาวน์โหลดที่ตรวจขนาดและ SHA-256 (22 ข้อทดสอบ รวมลิงก์ Google Drive, token ที่ไม่ส่งต่อ, ไฟล์ผิดขนาด, ลิงก์ไม่หลุด log),
  การทดสอบปลายทางกับบริการจริงทั้งสาย ผ่าน 197 จาก 197 ข้อ กับเครื่องรันโมเดลจำลอง (ทั้งในเครื่องนี้และบน GitHub) และชุดทดสอบทั้งหมด 534 ข้อ
  ผ่านบน Python 3.10 และ 3.12
- **ตัวเลขของ Colab ที่คุณรายงาน** (50/50, 36/36, 37/38, 141 วินาที) ยังเป็นของคุณ ระบบนี้ยังไม่ได้วัด

## 1. What the owner supplied (reported, not verified here)

| Item | Value |
|---|---|
| Base model and revision | `typhoon-ai/typhoon2.5-qwen3-4b` @ `ce0a7416fe82d4404b2b4a253ce3ac095ab1252c` |
| Training | QLoRA, 232 training and 54 validation examples, 2 epochs, final training loss 0.1698, validation loss 0.1669 |
| Before conversion | test 50: category 50/50; hard test 36: category 36/36; attention cases flagged 37/38 over both, with at least one security case missed |
| Adapter SHA-256 | `6d172e4ac9b177c78059f8318f38671b7ae1694d78da697e0b907a627bacd8ff` |
| GGUF | `nf_typhoon4b_v01_q4_k_m.gguf`, Q4_K_M, 2,497,278,816 bytes, SHA-256 `323ea4bb91fea1b6aa2e03fe845ca247f8c48de1e9e4d8da1841d48f18cc5c88` |
| Model id | `nf-typhoon4b-v01-q4_k_m:323ea4bb91fe` (matches `<name>:<first 12 hex digits>`, ADR-026) |
| GGUF smoke test | `GGUF_SMOKE_PASSED`: llama-server started, HTTP 200, schema passed, `upload` / `none` right, 1/1, CPU on localhost, 140.93 s |
| Location | the owner's Google Drive, `MyDrive/NeuronFlowAI/Typhoon4B_FineTuned_v01/`, with a `conversion_receipt.json` |

The pins in `.github/local_models.json` were copied from the owner's message by a program reading the session's own
transcript (the first value typed by hand was wrong and was caught before any commit; the test
`PinFileTests.test_the_committed_pins_are_the_owners_reported_values` now holds the exact values).

## 2. Access to the file

| Tried | Result |
|---|---|
| The session's Google Drive connector: search by name, folder, recent files | no folder or file named `NeuronFlowAI`, `Typhoon4B_FineTuned`, `nf_typhoon4b`, `gguf` or `conversion_receipt`; nothing created or modified after 2026-11-09 is visible to that account |
| This session's network: `huggingface.co`, `drive.usercontent.google.com` | refused by the session's proxy (the same as on 2026-11-08 for Hugging Face) |
| GitHub release assets | not used: 2 GiB limit per file (the file is 2.33 GiB) and a public repository's releases are public |

So the file reaches the lane through a link the owner keeps in a repository secret (`NF_MODEL_URL`; ADR-034, D10),
and the runner downloads it, checks the pinned size and SHA-256, and never caches or uploads it.

## 3. Verified in this session

| Check | Result |
|---|---|
| Full test suite, Python 3.10.20 and 3.12, also with `GITHUB_ACTIONS=true` | 534 tests pass (25 new) |
| `tests/test_fetch_model.py` | 22 tests: the pins are the owner's values; a Drive share link (4 forms) becomes the direct download; Drive's "can't scan" form is followed once without the token; quota and sign-in pages say what to do; a token reaches the first host only (not a redirect on the same host, not another server); a redirect off https is refused; wrong bytes, a shorter file, an announced other size, too many bytes and a cut transfer (retried 3 times) leave nothing on disk; no printed line, summary or output carries the link or the token (in Actions, only `::add-mask::` lines do); a missing secret names `NF_MODEL_URL`; a private Hugging Face repository gets the token while its file store does not |
| `python -m tests.local_model_e2e --phases service,failures,faults --fake-control` against `tests/fake_llama_server.py` | 197/197 checks in 27.5 s: service 101, decide 13, failures 18, faults 65 |
| … the failure paths, each case still `REVIEW_REQUIRED` with the rules' suggestion | timeout and unreachable server: `unavailable` / `provider_unavailable` after 2 attempts; prose instead of JSON, a value outside the schema, an extra key, a cut-off answer: `invalid_model_output` after 2; content filter and refusal: `model_declined` after 1; HTTP 500: `provider_unavailable` after 2; one HTTP 503: answered on attempt 2 |
| `.github/scripts/local_model_lane.py` with the stand-in (`--fake-loading-s`, `--fake-delay-s`) | load time waited out the 503s, first answer timed, connection check, scorecard, end-to-end check, peak RSS and token speeds recorded, exit 0; a server that does not start is reported |
| `tests/local_model_compare.py` on a saved Typhoon report | figures, case-by-case differences, a set with another prompt or case count refused as not comparable, figures without training cases |
| `tests/training_overlap.py` | a hard-set case inside a JSON-escaped chat prompt found exactly; a lightly edited development case found as near; the report shows no training text |
| gitleaks on the changed files | no leaks |

## 4. Verified on GitHub Actions (PR #68)

| Run | What | Result |
|---|---|---|
| *Core logic tests* [43421904522](https://github.com/narongdetpyou-ux/System_Neuron_flow_AI/actions/runs/43421904522), Python 3.10 | the new step: the end-to-end check against the stand-in, every phase | 197/197 checks in 26 s on the runner; the unit-test step failed on one test of mine (`::add-mask::` lines in captured output when `GITHUB_ACTIONS=true`), fixed in the next commit with a test for that case |

The local lane's smoke run with the publisher's 4B file on the runner is recorded in section 5.

## 5. The local lane with a real model file (the publisher's 4B)

Pending: the smoke run of this PR ([43421904358](https://github.com/narongdetpyou-ux/System_Neuron_flow_AI/actions/runs/43421904358))
was still running when this note was first written.

## 6. Not done yet

1. The owner's file: add `NF_MODEL_URL`, then *Local open model eval* with `model: both`, `triage_sets: all`,
   `e2e: full` (roadmap 5.11, "Done when").
2. Training-data overlap: unknown until `NF_TRAINING_URL` is set or the owner says where the 232 examples came from.
3. The owner's `conversion_receipt.json` was not seen (the connector does not show it); its values above are from the
   owner's message.

## 7. Limits

- Synthetic data and developer labels; the stand-in server proves the plumbing and the error paths, not a model.
- The pins are the owner's reported values: a download that matches them proves the bytes are the ones the owner
  described, not how they were made (ADR-008).
- GitHub's runners measure; they do not serve the page (ADR-026, D7).
