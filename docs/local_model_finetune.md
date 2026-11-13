# The owner's fine-tuned Typhoon 4B in the local model lane (ADR-034)

**Status (2026-11-13):** built in PR #68. The lane, the pins, the end-to-end check and the comparison are tested
in CI against a stand-in model server, and against the publisher's 4B file on the GitHub runner. The owner's file
itself has not run here yet: it waits for the repository secret `NF_MODEL_URL` (see "สิ่งที่คุณต้องทำ").
Evidence: [2026-11-13-finetune-integration.md](evidence/2026-11-13-finetune-integration.md).

## ภาพรวมสำหรับเจ้าของโปรเจกต์

**สรุปหนึ่งบรรทัด:** โมเดลที่คุณปรับแต่งเอง ใช้ในระบบได้แล้วผ่านช่องทาง "โมเดลในเครื่อง" (local) เป็นความเห็นที่สองของการคัดแยกเคส
แบบเดิมทุกอย่าง (กฎยังเป็นคำแนะนำทางการ คนยังตัดสินทุกเคส) เหลือแค่ให้ GitHub ดาวน์โหลดไฟล์ได้

**ระบบทำงานอย่างไร (ทีละขั้น)**
1. คุณกด Run workflow ที่ *Local open model eval* แล้วเลือกรุ่น (ต้นฉบับ, ที่ปรับแต่งแล้ว หรือทั้งสองบนเครื่องเดียวกัน)
2. เครื่องทดสอบของ GitHub ดาวน์โหลดไฟล์ GGUF จากลิงก์ที่คุณเก็บไว้ใน secret แล้วตรวจขนาด (2,497,278,816 bytes)
   และลายนิ้วมือ SHA-256 (`323ea4bb91fe…18cc5c88`) ถ้าไม่ตรงแม้แต่ไบต์เดียว ระบบไม่ใช้ไฟล์นั้นเลย
3. เครื่องรันโมเดล (llama.cpp) เปิดไฟล์บนเครื่องนั้นเอง ฟังเฉพาะ 127.0.0.1 ข้อความเคสไม่ออกไปบริษัท AI ใด
4. ระบบวัดผลกับชุดเคสเดิมทั้ง 5 ชุด (409 เคส) แล้วเทียบกับ Typhoon 4B ต้นฉบับ (เครื่องเดียวกัน) และกับ Typhoon 30B
   ที่เคยวัดไว้เมื่อ 11 พ.ย. เป็นรายเคส
5. ระบบรันบริการจริงทั้งสาย (รับเคส → คิว → ตัวรันงาน → Core) กับโมเดลนี้ แล้วตรวจทุกคำมั่น: ทุกเคสรอคนตัดสิน, คนอนุมัติ/ไม่อนุมัติได้,
   กดซ้ำไม่เกิดงานซ้ำ, ใบรับของ Core ตรงกับไฟล์จริง, ถ้า AI ช้าหรือเครื่องรันโมเดลดับ เคสยังไปถึงคนพร้อมคำแนะนำของกฎ
6. ระบบบันทึกเวลาโหลดโมเดล เวลาคำตอบแรก ความเร็ว (token ต่อวินาที) และหน่วยความจำสูงสุด

**สิ่งที่ตรวจแล้วจริง กับสิ่งที่คุณรายงาน (ยังไม่ได้ตรวจในระบบนี้)**

| เรื่อง | สถานะ |
|---|---|
| ขนาดไฟล์และ SHA-256 ที่คุณให้ | ตรึงไว้ใน `.github/local_models.json` แล้ว ตรวจกับไฟล์จริงทุกครั้งที่ดาวน์โหลด (ยังไม่เคยดาวน์โหลด เพราะยังไม่มีลิงก์) |
| ผลใน Colab (Test 50/50, Hard 36/36, attention 37/38, 141 วินาทีต่อคำตอบ) | คุณรายงาน ระบบนี้ยังไม่ได้วัด ตัวเลขของระบบนี้จะมาจากรอบที่รันใน GitHub |
| ข้อมูลฝึก 232 ข้อ มีเคสจากชุดทดสอบของ repo หรือไม่ | ยังไม่รู้ ถ้าคุณให้ลิงก์ข้อมูลฝึก (secret `NF_TRAINING_URL`) ระบบจะนับให้ และแสดงคะแนนแบบไม่นับเคสเหล่านั้นด้วย |
| ระบบใช้โมเดลนี้ได้จริงทั้งสาย | ตรวจแล้วกับเครื่องรันโมเดลจำลอง (ทุก push) และกับไฟล์ Typhoon 4B ต้นฉบับบนเครื่องของ GitHub ไฟล์ของคุณรอลิงก์ |

**สิ่งที่คุณต้องทำ (เลือกทางเดียว)**

ทางที่ 1, คลิกน้อยที่สุด (ไฟล์อยู่ที่ Google Drive เหมือนเดิม):
1. เปิด drive.google.com → คลิกขวาที่ไฟล์ `nf_typhoon4b_v01_q4_k_m.gguf` → แชร์ (Share)
2. "การเข้าถึงทั่วไป" (General access) เลือก **ทุกคนที่มีลิงก์** (Anyone with the link) สิทธิ์ **ผู้มีสิทธิ์อ่าน** (Viewer) → คัดลอกลิงก์
3. เปิด GitHub → repo นี้ → Settings → Secrets and variables → Actions → **New repository secret**
4. Name: `NF_MODEL_URL` · Secret: วางลิงก์ → Add secret

ข้อควรรู้: ใครได้ลิงก์ไปก็ดาวน์โหลดไฟล์ได้ (นี่คือการตัดสินใจของคุณ) แต่ลิงก์อยู่ใน secret เท่านั้น ไม่ถูกเขียนลง repo หรือ log
และระบบไม่เก็บไฟล์ในแคชหรือ artifact ของ repo สาธารณะนี้

ทางที่ 2, ไฟล์เป็นส่วนตัวจริง (Hugging Face แบบ private):
1. สร้าง model repo แบบ **Private** ที่ huggingface.co แล้วอัปโหลดไฟล์ GGUF
2. สร้าง Access Token แบบ fine-grained ที่อ่านได้เฉพาะ repo นั้น
3. ใส่ secret 2 ตัว: `NF_MODEL_URL` = `https://huggingface.co/<ชื่อคุณ>/<ชื่อ repo>/resolve/main/nf_typhoon4b_v01_q4_k_m.gguf`
   และ `NF_MODEL_TOKEN` = token นั้น (ระบบส่ง token ให้ huggingface.co เท่านั้น ไม่ส่งต่อไปที่อื่น)

ถ้าอยากให้ตรวจว่าข้อมูลฝึกซ้ำกับชุดทดสอบไหม (ไม่บังคับ): ทำแบบเดียวกันกับไฟล์ข้อมูลฝึก (เช่น `train.jsonl`) แล้วเก็บลิงก์ใน
secret `NF_TRAINING_URL` ระบบแสดงแค่จำนวนและรหัสเคสของ repo ไม่แสดงเนื้อหาข้อมูลฝึก

**วิธีทดสอบ (owner test)**
1. เปิด GitHub → Actions → *Local open model eval* → Run workflow
2. model เลือก `both` (ต้นฉบับกับที่ปรับแต่งแล้ว บนเครื่องเดียวกัน) · triage_sets `all` · e2e `full` → Run
3. รอราว 1.5–2 ชั่วโมง (คิดด้วย CPU) แล้วเปิดหน้า Summary ต้องเห็น:
   - "ไฟล์โมเดล" ของรุ่น `nf-typhoon4b-v01-q4_k_m:323ea4bb91fe` บอก "ตรวจขนาดและ SHA-256 แล้ว ตรงกับที่ตรึงไว้" และ "ไม่เก็บ" ในแคช
   - "ทดสอบปลายทาง" ขึ้น **ผ่านทุกข้อ** ของทั้งสองรุ่น
   - "เวลาและหน่วยความจำ" ของทั้งสองรุ่น
   - "เทียบโมเดลบนชุดเคสเดียวกัน" ทั้ง 5 ชุด พร้อมรายเคสที่ดีขึ้นและแย่ลง

**ถ้าอยากย้อนกลับ (rollback)**
- ไม่มีอะไรในบริการออนไลน์เปลี่ยน หน้าเว็บยังใช้ AI จำลอง (mock) เหมือนเดิม การรวม PR นี้จึงไม่ทำให้ Render ขึ้นเวอร์ชันใหม่
- เลิกใช้ไฟล์ของคุณ: ลบ secret `NF_MODEL_URL` (และ `NF_MODEL_TOKEN`) ใน GitHub แล้วปิดการแชร์ลิงก์ใน Google Drive
- รอบวัดผลจะกลับไปใช้ไฟล์ต้นฉบับได้ทันทีด้วยการเลือก model `typhoon2.5-qwen3-4b-q4_k_m` (ค่าเริ่มต้น)

**ข้อจำกัดที่ต้องรู้**
- ทุกชุดเป็นข้อมูลสมมุติ เฉลยเขียนโดยผู้พัฒนา และแต่ละรอบรันครั้งเดียว จึงเป็นการวัดครั้งแรก ไม่ใช่ความแม่นยำใน production
- ระบบส่ง prompt `triage_classify_v2` ของระบบเองให้โมเดล ถ้าตอนฝึกคุณใช้ prompt คนละแบบ ผลอาจต่างจากใน Colab (การวัดจะบอกเอง)
- โมเดลนี้ฝึกมาเพื่อคัดแยกเคสเท่านั้น ระบบไม่อ้างว่ามันใช้กับงานอื่นได้ (เช่น ผู้ช่วยแนะนำแหล่งเรียน)
- เครื่องของ GitHub ใช้วัดผลได้ แต่ใช้เป็นสมองของหน้าเว็บไม่ได้ (เงื่อนไขของ GitHub) การใช้กับหน้าเว็บต้องมีเครื่องเสียเงิน (D7)

## Provenance

| Item | Value | Where it comes from |
|---|---|---|
| Base model | `typhoon-ai/typhoon2.5-qwen3-4b`, revision `ce0a7416fe82d4404b2b4a253ce3ac095ab1252c` | the owner |
| Method | QLoRA, 232 training and 54 validation examples, 2 epochs, final losses 0.1698 / 0.1669 | the owner (Google Colab) |
| Adapter | SHA-256 `6d172e4ac9b177c78059f8318f38671b7ae1694d78da697e0b907a627bacd8ff` | the owner |
| Merged and quantized file | `nf_typhoon4b_v01_q4_k_m.gguf`, Q4_K_M, 2,497,278,816 bytes | the owner |
| File SHA-256 | `323ea4bb91fea1b6aa2e03fe845ca247f8c48de1e9e4d8da1841d48f18cc5c88` | the owner; pinned in `.github/local_models.json` and checked on every download |
| Model id the system records | `nf-typhoon4b-v01-q4_k_m:323ea4bb91fe` | `<name>:<first 12 hex digits>` (ADR-026), computed by `fetch_model.py` from the pin |
| Owner's Colab results | test 50/50, hard 36/36, attention 37/38 over both, one GGUF smoke answer in 140.93 s on CPU | the owner; **not measured here** |
| The publisher's 4B for comparison | `typhoon2.5-qwen3-4b-q4_k_m.gguf`, 2,497,276,128 bytes, SHA-256 `b3653029…e511`, Hugging Face commit `386874d0…` | pinned since PR #46 (ADR-026) |

The two files differ by 2,688 bytes, consistent with the same architecture and quantization with other metadata;
that is an observation about sizes, not a check of the contents. A hash proves the bytes, not who made them or how
(ADR-008).

## How the file reaches the runner

`python .github/scripts/fetch_model.py --profile .github/local_models.json --model nf-typhoon4b-v01-q4_k_m --dest <folder>`

- Source `link`: the https link in `NF_MODEL_URL`, with an optional bearer token in `NF_MODEL_TOKEN`.
- A Google Drive share link (`/file/d/<id>/view`, `open?id=`, `uc?id=`) becomes
  `https://drive.usercontent.google.com/download?id=<id>&export=download&confirm=t`. When Drive answers with its
  "can't scan this file for viruses" page instead, the page's `download-form` is followed once (to a Drive host only).
  A sign-in page or a quota page stops the run with what to do.
- The token is added with `add_unredirected_header`: it reaches the link's own host only, never a redirect target or
  Drive's form address. Every redirect must stay on https.
- A server that announces a different size is stopped before the download; one that sends more than the pinned
  size is stopped as it happens; a transfer that ends early is retried (3 attempts). Only a file with the pinned size
  and SHA-256 is kept; nothing else is left on disk.
- No message carries the link or the token; in Actions the values derived from it (the Drive file id, the direct
  address) are masked as well. The secrets are read only by the download steps and only on runs started by hand.
- `"cache": false` is required for a `link` source: this repository is public, and other workflow runs can restore
  its Actions cache, so the file goes to `$RUNNER_TEMP/private-models` (outside every cached folder), is downloaded
  afresh on each run, and is never uploaded (the artifact holds `lane/*.json` only).

## What a run does

*Actions → Local open model eval → Run workflow*, inputs `model` (the publisher's file, the fine-tune, or `both`),
`triage_sets` (`all` = synthetic 61, edge 116, held-out 40, hard 128, attention held-out 64), `limit`,
`study_guide`, `e2e` (`full`, `quick`, `none`). For each model, `.github/scripts/local_model_lane.py`:

1. starts `llama-server` with the lane's fixed settings (`SERVER_FLAGS`): `--ctx-size 16384 --parallel 2
   --reasoning off --temp 0 --repeat-penalty 1.05 --seed 42 --no-webui --no-slots --metrics`, on 127.0.0.1, with the
   model id as `--alias`; times the load until `/health` answers;
2. times the first answer after loading (nothing cached), through the real gateway with one fixed sentence, then
   runs the connection check;
3. runs `app.eval.triage_shadow_eval` on each chosen set (prompt `triage_classify_v2`, the same answer-format
   words and grammar as every local run), one report each;
4. runs the end-to-end check (below);
5. reads the server's peak and current memory (`VmHWM`, `VmRSS`), its prompt and generation speeds (`/metrics`),
   and the file and chat template it has open (`/props`), then stops it.

With `both`, the two files run one after the other on the same runner, so their latencies are comparable. Then
`tests/local_model_compare.py` compares the fine-tune with the base file case by case, and both with Typhoon 30B's
saved run of 2026-11-11 (`docs/evidence/2026-11-11-attention-raw/typhoon-v2-*.json`: same prompt, rules and signals;
a different machine, so its latency is not comparable). A set is compared only when the case file, the number of
cases, the prompt, the rules and the signals are the same.

## The end-to-end check

`tests/local_model_e2e.py` starts `python -m app.serve` (the API and its supervised Runner, unchanged) on 127.0.0.1
with a fresh data folder, a throwaway access key and `NEURON_FLOW_LLM_PROVIDER=local`, and gives it an environment
without any secret. Phases:

| Phase | What it checks |
|---|---|
| `service` | `/v1/status` reports `local`, the model id, not simulated; the model server serves that id, has the pinned file open (re-hashed) and carries a chat template; 12 fixed synthetic cases (four categories, Thai and English, an injection, rules mistakes, each attention kind, a phone number) each reach `REVIEW_REQUIRED`; the proposal keeps the shadow-mode contract (rules official, the AI's answer inside the schema or `unavailable` with a known reason, review reasons and priority consistent with the disagreement, signals and flag); provenance (provider, model, prompt and its SHA-256, masking version); tokens, latency and the served model; all five steps succeeded; Core's receipt recomputed from the report file (SHA-256 and size) and the report's provenance; events complete and free of case text; a repeated submission returns the same job; the phone number was masked before the AI call |
| `decide` | the inbox lists every case, raised ones first; an approval as proposed, an approval with another category and a rejection apply once each, with the job's state following; the same click again changes nothing; a stale version gets 409; each approval's `case_triage.v2.apply` job completes with the exact decision and its own verified receipt |
| `failures` | a client timeout of 0.2 s (shorter than any answer) and a model server that does not answer: the AI step is tried twice, then `unavailable` / `provider_unavailable`, and the case still waits for a person with the rules' suggestion |
| `faults` | only with the stand-in (`tests/fake_llama_server.py`, `--fake-control`): prose instead of JSON, a value outside the schema, an extra key, a cut-off answer (`invalid_model_output` after 2 attempts), a content filter or refusal (`model_declined` at once), HTTP 500 (`provider_unavailable`), and one HTTP 503 followed by an answer (answered on attempt 2) |

It never fails on a wrong category or attention value (accuracy is the scorecards' job); it fails when a promise
breaks (`decide` is part of the `service` phase). *Core logic tests* runs every phase against the stand-in on every
push; the lane runs all but `faults` against the real file.

## Training data overlap

A fine-tune scored on cases it was trained on looks better than it is. `tests/training_overlap.py` reads training
data (JSON Lines, JSON, or plain text; also JSON objects written inside prompt strings) and reports, per set, the
cases found exactly or nearly (80% of the case's character 5-grams in one training text). It prints only this
repository's case ids, the counts, the data's size and SHA-256. With `--ids-out`, the comparison repeats its figures
without those cases (`--training-cases`). In the workflow it runs when the secret `NF_TRAINING_URL` is set.

## Running the server yourself (developers)

On a machine with the file (checked first; the owner does not need to do this):

```bash
python .github/scripts/fetch_model.py --profile .github/local_models.json --model nf-typhoon4b-v01-q4_k_m --dest ~/models
```

```bash
llama-server -m ~/models/nf_typhoon4b_v01_q4_k_m.gguf --alias nf-typhoon4b-v01-q4_k_m:323ea4bb91fe --host 127.0.0.1 --port 8080 --ctx-size 16384 --parallel 2 --reasoning off --temp 0 --repeat-penalty 1.05 --seed 42 --no-webui --no-slots --metrics
```

```bash
NEURON_FLOW_LLM_PROVIDER=local NEURON_FLOW_LLM_MODEL=nf-typhoon4b-v01-q4_k_m:323ea4bb91fe NEURON_FLOW_LLM_TIMEOUT_S=300 NEURON_FLOW_ACCESS_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(24))") python -m app.serve
```

```bash
python -m tests.local_model_e2e --llm-base-url http://127.0.0.1:8080/v1 --model-id nf-typhoon4b-v01-q4_k_m:323ea4bb91fe --model-file ~/models/nf_typhoon4b_v01_q4_k_m.gguf --model-sha256 323ea4bb91fea1b6aa2e03fe845ca247f8c48de1e9e4d8da1841d48f18cc5c88
```

Use llama.cpp at the lane's pinned commit (`b12198`, `f477f795cb07`) for results that compare with the lane's.

## Rollback

- Nothing in `app/` or Core changed, and the live page still uses the mock AI: there is nothing to roll back online.
- The lane's default model is the publisher's file; choosing it again is the rollback inside the lane.
- To withdraw the file: delete `NF_MODEL_URL` (and `NF_MODEL_TOKEN`, `NF_TRAINING_URL`) under Settings → Secrets and
  variables → Actions, and stop sharing the link where the file is kept.
- A service that runs the fine-tune locally goes back by setting `NEURON_FLOW_LLM_MODEL` to
  `typhoon2.5-qwen3-4b-q4_k_m:b36530292268` and restarting `llama-server` with that file. The model id is part of the
  agent version (ADR-026), so a job interrupted under one file fails as `configuration_changed` under the other
  (ADR-015) instead of finishing silently; finished jobs keep the provenance they were run with.
- A new version of the fine-tune is a new entry in `.github/local_models.json` with a new name (for example
  `nf-typhoon4b-v02-q4_k_m`), its own size and SHA-256, and a new run; an entry is never edited to point at other bytes.

## Limits

- Synthetic sets with developer labels, one run per model per set: a first measurement of these files with these
  settings, not accuracy, and never Typhoon 30B's or Claude's.
- The system sends its own prompt (`triage_classify_v2`) and answer-format words. If the fine-tune was trained with
  other wording, its results here can differ from the owner's Colab results; the run measures what the system would
  actually get.
- Without the training data, overlap with these sets cannot be ruled out. The owner's "hard test" counts (36 cases;
  37 of 38 attention cases over two sets) do not match any set here, but this repository is public, so its sets may
  have been used in training.
- The fine-tune is for case triage only; the study guide's scorecard runs only when asked and claims nothing.
- CPU only on a 4-core runner. The owner's 140.93 s on Colab and the runner's figures are different machines and
  settings; the lane reports the load time, the first (cold) answer, the warm answers and the token speeds separately.
- GitHub's hosted runners may be used to build and test, not to serve the page: an open model behind the page needs
  a paid machine (D7).
