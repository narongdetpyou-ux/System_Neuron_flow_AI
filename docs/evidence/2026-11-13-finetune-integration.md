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
  การทดสอบปลายทางกับบริการจริงทั้งสาย ผ่าน 197 จาก 197 ข้อ กับเครื่องรันโมเดลจำลอง (ทั้งในเครื่องนี้และบน GitHub) และชุดทดสอบทั้งหมด 535 ข้อ
  ผ่านบน Python 3.10 และ 3.12
- **ทดสอบกับโมเดลจริงแล้ว (ไฟล์ต้นฉบับ 4B บนเครื่องของ GitHub):** ไฟล์ตรงกับที่ตรึงไว้, การทดสอบปลายทางผ่าน 70 จาก 70 ข้อ
  รวมกรณี AI ตอบไม่ทันเวลาและเครื่องรันโมเดลดับ (เคสยังไปถึงคนพร้อมคำแนะนำของกฎ), คำตอบแรกหลังโหลด 36.5 วินาที, คำตอบถัดไปราว 8–10 วินาที,
  หน่วยความจำสูงสุด 8.8 GB ไฟล์ของคุณจะได้ตัวเลขชุดเดียวกันเมื่อมีลิงก์
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
| Full test suite, Python 3.10.20 and 3.12, also with `GITHUB_ACTIONS=true` | 535 tests pass (26 new) |
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
| *Service container*, *Tracing check*, *Secret scan* (both jobs) | unchanged checks on the new files | passed |

The local lane's smoke run with the publisher's 4B file on the runner is in section 5.

## 5. The local lane with a real model file (the publisher's 4B)

PR #68's smoke run, [43421904358](https://github.com/narongdetpyou-ux/System_Neuron_flow_AI/actions/runs/43421904358)
(commit `27a51d9`; the reports name the PR's merge commit `42c7c79f4e16`): the publisher's file only, 5 triage cases,
5 study requests, the quick end-to-end check. A standard `ubuntu-latest` runner: Intel Xeon 6973P-C, 4 cores,
15,982 MB. llama.cpp `b12198` from the cache. The step that runs the model passed; the job failed in the comparison
step (below).

| Step | Result | Time |
|---|---|---|
| Download and check the file | 2,497,276,128 bytes, SHA-256 `b3653029…e511`, the pin in `.github/local_models.json`; a fresh download (the new cache key) | 25 s |
| Start `llama-server` until `/health` answers | | 4.01 s |
| First answer after loading (nothing cached), through the gateway | answered | 36,519.8 ms |
| Connection check | HTTP 200, a valid JSON answer (`upload`, `none`, `high`); 809 prompt tokens of which 808 cached, 44 generated | 8.1 s |
| Triage scorecard, first 5 development cases | jobs 5/5, AI answered 5/5, AI right 5/5 (rules 5/5); AI latency p50 8,464.0 ms, p95 8,939.8 ms; tokens 4,048 in, 205 out | 42.6 s |
| Study guide scorecard, first 5 requests | topic right 5/5, 0 of 10 links outside the library | 356.4 s |
| End-to-end check, `quick` (4 cases) | **70/70 checks**: service 39, decide 13, failures 18. 4/4 waited for a person, 4/4 answers inside the schema, 4/4 categories as labelled (rules 2/4: `AS-EN-TRP-01` and `AS-TH-PII-01` were raised as disagreements). The server served the alias and had the pinned file open, re-hashed to the pin; chat template SHA-256 `cc145ac59732` (208 characters). With the real server, a 0.2 s client timeout and an unreachable server each ended `provider_unavailable` after 2 attempts, and the case still waited for a person with the rules' suggestion. Submit to review: median 10.43 s, longest 11.71 s; AI latency median 10,165.4 ms | 51.7 s |
| The server's own figures for the run | peak memory of its process (VmHWM) 8,795 MB; prompt 24.1 and generation 5.1 tokens a second; 5,551 prompt and 1,296 generated tokens in all | |
| Comparison | **failed the job**: the 5-case report was rightly refused as not comparable with Typhoon 30B's 61-case run, but the script's exit status 1 failed the step; fixed in the next commit (exit 0 for a report that says "not comparable", 1 only without any report), with a test | 0 s |

What these figures say about speed, on this machine with these settings (one run):
- An answer of this length (about 41 to 45 generated tokens) at about 5 generated tokens a second takes about 8 to
  10 s, which is the measured case latency: once the long system prompt is cached (808 of 809 tokens in the
  connection check), writing the answer is most of the time.
- The first answer after loading also reads the whole prompt (about 800 tokens) at about 24 tokens a second; that is
  the 36.5 s. The owner's 140.93 s was one cold answer on a Colab CPU, a different machine and setup, so this run
  neither confirms nor explains that figure; the fine-tune's own run will give its cold and warm figures here.
- The peak memory (8.8 GB) is far more than the 2.5 GB file: it includes the context cache for 16,384 tokens over
  2 slots and llama.cpp's buffers; this run does not break it down. A machine for the page (D7) needs room for it, or
  smaller settings, measured again.

### An earlier run of the same file and prompt, for reference

The owner ran the previous version of *Local open model eval* on `main` on 2026-11-12
([43261009269](https://github.com/narongdetpyou-ux/System_Neuron_flow_AI/actions/runs/43261009269), `45f27f4`),
triage only, `robustness_edge_v1`: the same file (`b36530292268`), prompt `triage_classify_v2` (`ad9f35e52ff5`),
rules `keywords-v2:50f64599…` and signals `signals-v2:cc8a9051…`. From its job log: jobs 116/116, AI answered 116/116,
AI right 98/116 (Thai 12/13, English 86/103), rules 105/116, agreement 103/116, raised 23/116, rule mistakes raised
3/11, AI flags 13/116, tokens 94,215 in and 4,925 out, AI latency p50 4,058.7 ms and p95 4,852.0 ms. That runner
answered about twice as fast as this PR's (8,464.0 ms p50 on 5 development cases), which is why the lane compares
latencies only between files run on the same runner (`model: both`). The full run of this branch
([43423749547](https://github.com/narongdetpyou-ux/System_Neuron_flow_AI/actions/runs/43423749547)) repeats the edge
set with the same file and settings, so its per-case answers can be compared with this one.

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
