# Our own model, learning in measured rounds (track T1–T6)

**Status:** a plan, written on 2026-11-22 because the owner asked for "AI ของเราเอง" that learns as the system is
developed, instead of using other companies' AI, and then said to write the plan. T2 (a synthetic training set
and its overlap check) is built ([section 10](#10-t2-as-built-2026-11-22)); nothing is trained, and no model file was
touched. The decision is [ADR-037](architecture.md#8-architecture-decisions-adrs) (in force since the owner started T2).
The status of each package is in the roadmap's table ([ROADMAP.md](ROADMAP.md#own-model-track-t1t6)). Merged as
PR #80 the same day. Then the owner chose the base and round 0: the publisher's Typhoon 2.5 Qwen3 4B that the local
lane already tests on GitHub, because the owner's fine-tuned file on Drive was too troublesome to share. That file is
set aside, and nothing is done with it.

## สรุปสำหรับเจ้าของโปรเจกต์

**แนวคิดของคุณ:** แทนที่จะยืมสมองของบริษัทอื่น (Typhoon หรือ Claude ผ่าน API) เรามี AI ของเราเอง
ที่เก่งขึ้นเรื่อย ๆ จากงานจริงของระบบ ยิ่งใช้และพัฒนาระบบนาน AI ก็ยิ่งเข้าใจงานของเรา

**วิธีที่แผนนี้เลือก:** เอาโมเดลเปิด (open-weight model) ที่มีอยู่แล้วมาสอนงานของเรา (fine-tuning) เป็นรอบ ๆ
ไม่สร้างใหม่จากศูนย์ เพราะต้องใช้เงินและเครื่องมหาศาล และไม่ปล่อยให้ AI เรียนเองตลอดเวลา

**หนึ่งรอบของการเรียน**
1. **เก็บเฉลย** ตอนนี้ใช้เคสสมมติที่เขียนไว้สำหรับฝึกโดยเฉพาะ วันหลังใช้หมวดที่คนตัดสิน (หลังขั้น 2.9 ที่ให้คนเลือกหมวดก่อนเห็นข้อเสนอ)
2. **คุณอนุมัติชุดฝึก** ระบบตรวจว่าชุดฝึกไม่ซ้ำกับข้อสอบชุดใดเลย แล้วล็อกชุดฝึกด้วยรหัสตรวจสอบ (SHA-256)
3. **ฝึก** บนเครื่องที่มีการ์ดจอ (GPU) เช่น Google Colab ที่คุณเคยใช้ ได้โมเดลรุ่นใหม่ 1 ไฟล์พร้อมใบบันทึกการฝึก
4. **สอบก่อนใช้** ช่องวัดโมเดลที่รันเอง (ขั้น 5.8) สอบรุ่นใหม่ด้วยข้อสอบทุกชุดที่มี แล้วเทียบกับรุ่นปัจจุบัน ตามเกณฑ์ที่เขียนไว้ก่อนสอบ
5. **คุณตัดสินใจว่าจะเปลี่ยนรุ่นไหม** ระบบไม่เปลี่ยนเอง ถ้าเปลี่ยนแล้วไม่ดี ก็ถอยกลับรุ่นเดิมได้
6. **เฝ้าดูผล** ตาราง "กฎกับ AI เทียบกับคำตัดสินของคน" (ขั้น 2.8) แยกนับตามรุ่นของ AI อยู่แล้ว จึงบอกได้ว่ารุ่นใหม่ดีขึ้นจริงไหม แล้ววนกลับไปข้อ 1

**ทำไมไม่ให้ AI เรียนเองตลอดเวลา:** ระบบตรึงรุ่น AI ไว้กับทุกงาน ถ้า AI เปลี่ยนตัวเองทุกนาที เราจะไม่รู้ว่าข้อเสนอไหนมาจากรุ่นไหน
และถ้ามันเรียนจากข้อมูลผิด หรือมีคนจงใจป้อนข้อมูลเสีย มันจะแย่ลงเงียบ ๆ โดยไม่มีใครเห็น

**ทำได้เลยโดยไม่ต้องจ่ายเงินหรือใช้ข้อมูลจริง**
- T2 ชุดฝึกสมมติ พร้อมด่านตรวจว่าไม่ซ้ำกับข้อสอบ
- T3 สูตรการฝึกที่ทำซ้ำได้ (เขียนสูตรไว้ แต่ยังไม่ฝึก)
- T4 ด่านสอบรุ่นใหม่ (ใช้ช่องวัดเดิมของ GitHub ซึ่งฟรี)

**รอคุณตัดสินใจ**
- D10 จะฝึกที่ไหน: Colab ฟรีหรือเสียเงิน, เช่าการ์ดจอเป็นชั่วโมง หรือเครื่องของคุณเอง
- เมื่อฝึกรอบแรกเสร็จ (T5) ไฟล์รุ่นใหม่ต้องไปอยู่ที่ที่ GitHub ดาวน์โหลดเองได้ เช่น Hugging Face แบบส่วนตัวหรือสาธารณะ ผมจะถามอีกครั้งตอนนั้น

**ตัดสินใจแล้ว (22 พ.ย.):** ใช้โมเดล 4B ตัวเดิมที่ GitHub ทดสอบอยู่ (Typhoon 2.5 Qwen3 4B ของผู้พัฒนา) เป็นจุดตั้งต้นและ "รอบ 0"
GitHub ดาวน์โหลดไฟล์นี้เองจาก Hugging Face และตรวจรหัส SHA-256 ทุกครั้ง จึงไม่ต้องใช้ลิงก์หรือไฟล์ใน Drive
ส่วนโมเดลที่คุณฝึกเองใน Drive ผมพักไว้ ไม่แตะ
- เรื่องอื่นที่มีอยู่แล้ว: 2.9 (ให้คนเลือกหมวดก่อนเห็นข้อเสนอ), D1 (ดิสก์ถาวร เพื่อสะสมเฉลย), D3 (ผู้ตรวจจริง), D4 (ข้อมูลจริง), D7 (เครื่องเสียเงินสำหรับใช้โมเดลบนหน้าเว็บ), D6 (บทบาทของ AI)

**สิ่งที่แผนนี้จะไม่ทำ:** ไม่ให้ AI เรียนเองขณะทำงาน ไม่เปลี่ยนรุ่นเอง ไม่เอาข้อสอบไปฝึก ไม่ใช้ข้อมูลจริงก่อน D4
ไม่ให้ AI ตัดสินแทนคน และไม่ใช้ไฟล์โมเดลใน Drive ของคุณ

**ข้อจำกัดที่ต้องรู้:** โมเดลพื้นฐานยังเป็นของบริษัทอื่น (Typhoon 2.5 ของ SCB 10X ซึ่งต่อยอดจาก Qwen3) แต่เป็นแบบเปิด:
เราถือไฟล์เอง รันบนเครื่องที่เราคุม และไม่ส่งข้อความไปบริษัท AI ใด ฝึกด้วยข้อมูลน้อยอาจจำข้อสอบแทนที่จะเข้าใจ
และข้อมูลสมมติไม่เหมือนงานจริง ผลสอบที่ผ่านจึงยังไม่ใช่ความแม่นยำในงานจริง

**แหล่งเรียน** (จากคลังแหล่งเรียนที่ตรวจลิงก์ทุกสัปดาห์)

| ลำดับ | แหล่ง | ใช้ทำอะไร |
|---|---|---|
| 1 | AI Engineer Roadmap https://roadmap.sh/ai-engineer | แผนที่หัวข้อ เห็นว่าการฝึกโมเดลเอง (fine-tuning) อยู่ตรงไหนเทียบกับเรื่องอื่น (อังกฤษ ระดับเริ่มต้น) |
| 2 | Thai MOOC https://thaimooc.ac.th/ | คอร์สภาษาไทยฟรี พื้นฐาน AI และการเรียนรู้ของเครื่อง (machine learning) |
| 3 | CLINC150 (Larson et al., 2019) https://aclanthology.org/D19-1131/ | วิธีวัดว่าระบบแยกคำขอถูกไหมและจับเรื่องนอกกรอบได้ไหม คือหัวใจของขั้น "สอบก่อนใช้" (ระดับลึก) |

ควรเรียนตามลำดับ 1 → 2 → 3 คลังยังไม่มีแหล่งที่สอนการฝึกโมเดลโดยตรง แหล่งใหม่ต้องตรวจลิงก์ก่อนเพิ่ม
และตอนนี้คุณพักงานของผู้ช่วยแนะนำแหล่งเรียนไว้ จึงยังไม่เพิ่ม

## 1. What "our own model" means here

- **Fine-tuning, not pretraining.** Training a language model from nothing takes data and compute far beyond this
  project. We take an open-weight base and teach it our task. The base, chosen by the owner on 2026-11-22, is the
  file the local lane already serves: Typhoon 2.5 Qwen3 4B (SCB 10X, Apache-2.0; ADR-026), Q4_K_M, pinned by
  repository, revision and SHA-256 in `.github/workflows/local-model-eval.yml` (`MODEL_REPO`, `MODEL_REVISION`,
  `MODEL_SHA256`). Training starts from the publisher's un-quantized weights of the same model, pinned in T3. We
  hold the file, run it on a machine we control and send nothing to an AI company. The base is still someone else's work, so its licence is checked again for each
  new base before it is served.
- **One narrow job first:** the triage second opinion, a category and the attention flag, both fixed choices. It
  uses the same prompt contract (`triage_classify_v2`), the same gateway checks, masking and answer format as
  every other provider. Not free text, and not the study guide (paused by the owner).
- **The same role.** It stays the AI second opinion in shadow mode (ADR-010). The rules stay the official
  suggestion and a person decides every case (rule 4). A bigger role is owner decision D6, after 2.8's evidence.

## 2. One round of the learning loop

1. **Collect.** Synthetic training cases written for training (T2). Later, people's labels (T6): the category a
   person recorded, only from blind labels (2.9). Today a person sees the rules' suggestion first, and approving as
   proposed keeps it, so training on those labels would teach the model to copy the rules.
2. **Curate.** A training set is one versioned file with a manifest (its SHA-256, size, counts per category and
   language). The overlap check (T2) must pass: no item may equal or nearly equal an item of any exam set. The
   owner approves the set by its hash before any training. Text is masked (`redact-v2` or later) like every AI call.
3. **Train** (T3, D10). QLoRA on a pinned base revision with a pinned recipe (hyperparameters, seed, library
   versions). The output is an adapter, a merged model and a GGUF file built with the lane's pinned llama.cpp
   commit, plus a training receipt that names every input and output by SHA-256.
4. **Exam** (T4). The candidate runs on the local lane (5.8) against every exam set and is compared with the
   current model, by criteria written before the run (section 5). One run with greedy decoding, repeated once to
   confirm it gives the same answers.
5. **The owner decides.** Switching is a new agent version (rule 5): the model id names the file,
   `<name>:<first 12 hex digits of its SHA-256>` (ADR-026). Jobs caught mid-way fail as `configuration_changed`,
   by design. Rolling back means pinning the previous file again.
6. **Watch.** The reviewer-label scorecard (2.8) already groups people's decisions by the AI agent's version, and
   2.10 adds reviewer time. That is the live signal for the next round, never a trigger by itself.

**Never online learning.** The model never changes while it serves:
- every job freezes its agent version, and a model that changes itself could not be measured, traced or rolled back;
- labels can be wrong or planted (data poisoning), and a model that learns from its own answers repeats its own
  mistakes. A round goes through a person twice: the owner approves the training set and decides the switch.

## 3. Data rules

- **Exams are never training data.** Never in any training set: the 61 development cases, the 40 held-out cases,
  the 116 robustness edges, the 128 hard auto-send cases, the 64 held-out attention cases, the open-benchmark sets
  and BIPIA's attacks. The sealed half of the open data is never read for training at all, the same rule as for the
  attention signals (rule 5). This includes cases rewritten from them.
- **The overlap check** (T2, standard library, in CI) normalizes text before comparing (for example letter case and
  spacing; T2 fixes the exact steps). It fails on any exact match. It also fails on any near match: a high share of shared character n-grams, with the
  threshold fixed in its first version and reported with every result.
- **Synthetic first.** T2's training set is written for training only: Thai and English, the four categories,
  the four attention kinds and `none`, injection attempts labelled by what the case is really about, and hard
  negatives. The developer labels it; the owner reads a sample. Its size is chosen in T2 and recorded.
- **People's labels later** (T6): only from decisions made with the owner's key or a reviewer's token (ADR-034).
  Only blind labels (2.9) count. A rejection without a category is left out. An AI answer is never a label.
- **Real data last.** Only after D4, 7.1–7.3 and written consent (7.5), masked before it is stored for training.
  Deleting a case from a training set does not remove it from a model already trained on it. That is one more
  reason real data waits for consent and masking.

## 4. Where and how training runs

- **It needs a GPU.** GitHub's hosted runners are CPU only. The lane uses them only to measure (ADR-026), and this
  plan keeps it that way: no training and no serving there.
- **Owner decision D10:** Google Colab (the owner trained v01 there; the free tier has session limits, paid tiers
  cost money), a GPU rented by the hour, or the owner's own computer with a GPU. Accounts and money are the owner's.
- **The recipe lives in the repository** (T3) under `training/`, which the image never copies and Render's build
  filter ignores (T3 adds both, with a test). It takes the base model id, revision and SHA-256, the training set and
  its SHA-256, the hyperparameters and a seed. It writes `training_receipt.json`: every hash, the library versions,
  the GPU and the time taken.
- **Training libraries stay out of the app.** PyTorch, Transformers, PEFT and the like are installed only where
  training runs, never in the `Dockerfile`, `pyproject.toml` or the session hook (rule 8, ADR-037).
- **Hashes are copied by program**, never by hand: a hand-typed pin was wrong once.

## 5. The exam before use

- **Where:** the local lane (5.8), on a GitHub runner. Round 0 is the lane's own pinned file, fetched from Hugging
  Face as today. A trained candidate (T5) must be put where the runner can fetch it and check its size and SHA-256.
  Hugging Face, which `fetch_model.py` already reads, is the natural place. Whether that repository is private (a
  read-only token as a repository secret) or public is the owner's choice at T5.
- **Sets:** all of section 3's exam sets, with the sealed half counted only.
- **Compared with:** round 0, the publisher's 4B unchanged, and Typhoon's saved answers (2026-11-11), set by set,
  as counts (n/N). Its full run of 2026-11-08 used that day's prompt and answer checks; today's agent version
  differs (`triage_classify_v2`, `answer-checks-v3`), so round 0 is run again on `main` before the first comparison
  (T4).
- **Criteria, proposed now and confirmed by the owner before the first run (T4):**
  - no more off-format or unavailable answers than the current local model;
  - AI correct on the held-out and hard sets: not lower than the current local model's;
  - the rules' mistakes raised for review (the shadow mode's main job): not fewer;
  - attention: no fewer `needs_person` cases raised on the hard and held-out attention sets, nor BIPIA attacks
    flagged; needless raises reported;
  - median latency per case on the runner: at most 1.5 times the current local model's;
  - the overlap check passed for that round's training set.
- **What a pass means:** better on developer-labelled synthetic sets, not accuracy in real use. With 40 held-out
  cases even 40/40 has a 95% Wilson interval of 91–100%, so a small gain can be noise. A failed round is recorded
  as plainly as a passed one.

## 6. Serving it behind the page

- The live page needs a machine with room for the model (owner decision D7, roadmap 5.8 step 4). Measured so far:
  a Q4_K_M file of this 4B model is about 2.5 GB (the owner's set-aside fine-tune: 2,497,278,816 bytes); the
  publisher's 4B used at most 8.8 GB of memory and took about 8 to
  10 s a case after loading on a GitHub runner (run 43421904358). Render's free plan has 512 MB.
- Then the model server goes into the service's container (one machine, ADR-003) through `render.yaml`, with
  `NEURON_FLOW_LLM_PROVIDER=local` and the file's model id. Latency is measured again on that machine.

## 7. The packages

| Package | What | Needs |
|---|---|---|
| **T1** | This plan and ADR-037 | ✅ merged (PR #80) |
| **T2** | Synthetic training set v1 with its manifest, and the overlap check against every exam set in CI | ✅ built on 2026-11-22 (section 10); the owner reads a sample |
| **T3** | The training recipe and receipt format in `training/`, kept out of the image and Render's build, with a test | ✅ built on 2026-11-22 (section 11); D10 to run it |
| **T4** | The exam gate: round 0 run again on `main`; the local lane takes a candidate file (Hugging Face repository, revision, size, SHA-256), runs every set and writes the comparison against the criteria | ✅ built on 2026-11-22 (section 12); round 0's first full run waits for the owner's click |
| **T5** | Round 1: train on T2's set, run the exam, write an evidence note; the owner decides | T2–T4, D10; where the trained file is put |
| **T6** | Rounds from people's decisions: the owner exports blind labels (masked) as a training set; the cadence is the owner's choice | 2.9, D1, D3; real cases also D4, 7.1–7.3, 7.5 |

Serving behind the page is not a T package: it is D7 and 5.8 step 4. As with a phase, a package starts when the
owner says so.

## 8. Don't

- Let the model learn while it serves, or switch versions by itself.
- Train on an exam set, on anything rewritten from one, on the sealed half or on the AI's own answers.
- Use real data before D4.
- Put training libraries in the image, the app or the session hook.
- Train or serve on GitHub's hosted runners; they measure.
- Present our model's numbers as Typhoon's API or Claude's, or the owner's Colab results as measured here.
- Let it decide anything (rule 4) or change its role without D6.
- Fetch, share or run the owner's fine-tuned file on Drive: the owner set it aside on 2026-11-22.

## 9. Honest limits

- A few hundred synthetic cases can teach the model the sets' wording rather than the task. The held-out exams
  catch some of this, not all.
- Fine-tuning a small model can cost it abilities it had (forgetting), which is one reason the exam covers more
  than the trained task: the robustness edges, the injections and out-of-scope requests.
- "Learning along with the system" is slow on purpose. Each round needs a training run, an exam on CPU (the first
  full local run of both scorecards took about 66 minutes, 55 of them the study guide) and an owner decision.
- The base model is made by others, and its licence is theirs to set.

## 10. T2 as built (2026-11-22)

The owner said "เริ่ม T2 ต่อเลย" (start T2 now) after merging the base-model choice.

- **The set:** `training/data/triage_train_v1.json`, 240 synthetic cases written for training only by the developer
  (an AI coding agent): 120 Thai and 120 English, 60 per category, and per language 84 ordinary cases, 10 security,
  10 instruction (steering text), 8 distress and 8 legal or privacy. Each case carries the answer the prompt
  `triage_classify_v2` should give: category, attention, confidence and a one-sentence rationale in the case's
  language. It includes hard negatives (a payment word in an upload case, "not about payment"), mixed requests,
  vague texts with `low` confidence, and personal details only as the masking placeholders (`[PHONE]`, `[EMAIL]`,
  `[NUMBER]`, `[NAME]`). Labels are the developer's, not independent ground truth.
- **The manifest:** `training/data/triage_train_v1.manifest.json` pins the file's SHA-256, its size and its counts.
  The owner approves the set by merging the pull request that adds it; a changed file fails until its manifest is
  written again (`--write-manifest`), which is visible in review.
- **The check:** `python -m training.check_set` (standard library and the app's contracts only), the rule
  `overlap-v1` of section 3: every record (fields, labels, the case's language, the workflow's own admission check,
  nothing left to mask, an answer the gateway accepts unchanged), unique ids and texts, the manifest, and no exact or
  near match with any exam set. `tests/test_training_set.py` runs it in CI against every exam set committed here
  (and fails if a new exam set is not in its list); the *Training set check* workflow also builds the open-benchmark
  sets and the sealed half and checks against them (the sealed half as counts only).
- **First run:** the first draft collided with exam texts in 7 of 240 cases (1 exact and 3 near in the development
  set, 3 near in the hard auto-send set). All 7 were rewritten as different requests with the same labels, without
  reading the exam texts. The set then passed against every committed exam set and, in this session, against the four
  open-benchmark sets and the sealed half (0 exact, 0 near). The highest similarity left is 0.585 (Jaccard, held-out
  set), under the 0.6 threshold.
- **Not done:** no training (T3, D10) and no exam of a trained model (T4, T5). Whether 240 cases are enough is
  something only round 1 can show.

## 11. T3 as built (2026-11-22)

The owner said "เริ่มทำ T3 ได้เลย" after dropping the idea of changing Core ("ปัดเรื่องแก้ Core ทิ้ง"). The owner had
worried that Core might make the model go wrong; Core never touches a model's answers, and the real risk is a model
trained on text that differs from what it is served, so T3 includes a guard for exactly that.

- **The recipe:** `training/recipe_v1.json` (`triage_qlora_v1`) pins the approved training set by SHA-256, the base
  model `typhoon-ai/typhoon2.5-qwen3-4b` by revision (copied by program from the record of the owner's earlier
  fine-tune of the same base), QLoRA in 4 bits (r 16, alpha 32, dropout 0.05, all attention and MLP projections),
  3 epochs at 2e-4 with a cosine schedule, seed 20261122, loss on the answer only, 10% of the cases held out by their
  id's SHA-256 to watch the loss (20 of 240), the export (merged, then GGUF Q4_K_M with the local lane's llama.cpp
  tag and commit) and how it must be served (thinking off, temperature 0, repeat penalty 1.05, seed 42, context
  16384). These are starting values, not tuned or measured; a changed value is a new recipe version.
- **Train/serve sameness:** `training/render.py` builds every example with the service's own request builder
  (`build_request_body` for the `local` provider: the prompt file, its answer-format words and `user_message` on the
  masked text), and the answer as JSON in the schema's order. `tests/test_training_recipe.py` compares all 240
  examples with a fresh serving request byte for byte, refuses a hand-written system or user message, and checks the
  recipe against the local lane's flags and llama.cpp pins. On the GPU, the script stops if the model's chat template
  (thinking off) does not keep each prompt as an exact prefix of the full conversation.
- **The receipt:** `training/receipt.py` defines `training_receipt.json` (recipe, set and rendered examples by
  SHA-256, the base model files' SHA-256, library versions, the GPU, the losses, the adapter and the GGUF with its
  model id) and the serving contract (prompt SHA-256, answer format, masking rules, answer checks). `validate` checks
  a receipt; `serving_mismatches` finds a model trained for another prompt or other checks, for T4 to refuse.
- **The script:** `training/train_qlora.py` checks, renders, trains, merges, exports and writes the receipt, also when
  a run fails. Its libraries (`training/requirements-train.txt`: transformers 4.51.3, peft 0.15.2, bitsandbytes
  0.45.5, accelerate 1.6.0; PyTorch from the GPU environment) are imported only inside its functions, so
  `python -m training.train_qlora --dry-run` runs anywhere; the *Training set check* workflow runs it and shows the plan.
  Nothing in `app/` or `neuron_flow/` imports `training/`, and the libraries are never in the image (tests).
- **Not done or not known yet:** no run on a GPU (D10). The pinned library versions and the chat-template prefix
  check are first exercised there; a version that must change is a new recipe version. Whether the starting values
  give a better model than round 0 is T4's and T5's question.

## 12. T4 as built (2026-11-22)

The owner said "เริ่ม T4 ต่อเลย" after merging T3.

- **The exam:** `training/exam.py` and the *Own model exam* workflow (`.github/workflows/own-model-exam.yml`,
  `.github/scripts/run_exam.sh`). Every model is examined on six sets: the 61 development cases, the 40 held-out
  cases, the 128 hard auto-send cases, the 64 held-out attention cases, the 116 robustness edges and BIPIA's 75
  attacks (built at run time from the pinned files), 484 cases in all, with the local provider through the real
  service code. The workflow uses the local lane's llama.cpp build and round 0 file (a test keeps them equal), the
  recipe's serving flags (thinking off, temperature 0, repeat penalty 1.05, seed 42, context 16384) and the client's
  longest wait, 300 s, as the lane (A3 of the advice on Core).
- **The probe (A2):** before each model's exam, 8 clear development cases (each category once in each language)
  must come back well formed with the right category, or the exam stops. The same probe is for our model's start
  behind the page, when D7 comes; it is not wired into the service before then, because nothing would use it.
- **Round 0 and a candidate on one runner:** with no candidate the workflow examines round 0 alone. With a candidate
  (a public Hugging Face file pinned by commit and SHA-256), it examines round 0 and then the candidate on the same
  machine, so their answer times can be compared, and runs criteria v1. Each case's answers are printed as
  `EXAM-CASE` lines (ids and labels, never case text) and each set's figures as `EXAM-METRICS` lines in the job log,
  which this session can read back to record round 0's baseline.
- **Criteria v1** (`exam-criteria-v1`, section 5's proposal, now code): no more missing or off-format answers; at
  least as many correct categories on the held-out and the hard set; at least as many of the rules' mistakes raised
  (triage sets); at least as many `needs_person` cases raised (hard and attention sets) and BIPIA attacks raised; a
  median answer time at most 1.5 times round 0's; and, with the candidate's receipt, a valid receipt trained for
  today's prompt, answer format, masking and checks on the approved set. Needless raises are reported, not gated.
- **Checked here:** 18 tests (each criterion shown to fail on a changed report, the probe, the digest, the command line
  and the workflow's pins), and the whole script run locally against a stand-in model server that answers like the
  offline mock (round 0 and a candidate, then the comparison). The real model runs on GitHub: pull requests that
  change the exam get a smoke run of 3 cases per set.
- **Not done yet:** round 0's full run on `main` (about 484 cases at roughly 8 to 10 s each on a CPU runner: over an
  hour), which the owner starts with *Run workflow*; then its figures go into an evidence note. A private candidate
  repository (a token) is T5's question.

