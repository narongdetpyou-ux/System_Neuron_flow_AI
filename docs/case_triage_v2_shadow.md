# case_triage v2 — shadow mode (AI second opinion)

**Status:** on `main` since 2026-11-01 (PR #9). Implemented and tested with the offline mock AI. The
Claude and GitHub Models code paths are tested against a local fake API server. **No real model has run
yet**: Claude needs a paid `ANTHROPIC_API_KEY` (D2), and the free GitHub Models path (ADR-020, added
2026-11-06) waits for its first manual run. Synthetic data only. This is not a production
service, public API or human-review service. No Core (`neuron_flow/`) file was changed. Design principles:
[design_philosophy.md](design_philosophy.md).

## ภาพรวมการทำงาน (สรุปภาษาไทย)

1. มีเคสลูกค้าเข้ามา 1 เคส (รหัสเคส + ข้อความ)
2. **กฎเดิม** (คำสำคัญภาษาอังกฤษ) เสนอคิวที่ควรส่งไป ข้อเสนอนี้คือ "ข้อเสนอหลัก" เหมือนเดิม
3. พร้อมกันนั้น **AI** อ่านเคสเดียวกันแล้วเสนอหมวดของตัวเอง (ความเห็นที่สอง) ก่อนส่ง ระบบปิดข้อมูลส่วนตัวที่จับรูปแบบได้ (อีเมล เบอร์โทร เลขบัตร ตัวเลขยาว ชื่อที่มีคำนำหน้า) AI จึงเห็นแค่ป้ายแทน เช่น [PHONE] (ขั้น 7.1)
   - ถ้า AI ติดขัดชั่วคราว ระบบลองใหม่ 1 ครั้ง
   - ถ้ายังไม่ได้ หรือ AI ปฏิเสธที่จะตอบ ระบบเดินต่อโดยใช้ข้อเสนอของกฎ และแจ้งผู้รีวิวว่า "AI ใช้งานไม่ได้"
   - ถ้าตั้งค่าผิด (เช่น API key ผิด) ระบบหยุดเคสนั้นและแจ้งเตือนทาง Sentry/อีเมล
4. ระบบ **เทียบ** สองความเห็น ถ้าไม่ตรงกัน เคสถูกยกเป็น "ต้องดูก่อน" (priority elevated) พร้อมเหตุผล
5. ผู้รีวิวได้รับข้อเสนอที่ **รอคนตัดสินเสมอ** (PENDING_HUMAN_REVIEW) AI ไม่มีสิทธิ์ตัดสินหรือเปลี่ยนคิวเอง
6. ทุกคำตอบของ AI ถูกบันทึกว่ามาจากรุ่นไหน ใช้ prompt ฉบับไหน ถ้าเปลี่ยน prompt หรือรุ่น AI งานเก่าจะไม่ถูกรันซ้ำด้วยค่าใหม่โดยไม่รู้ตัว
7. **ด่านตรวจผลรายเคส (eval gate, ขั้น 5.2)** ทุกครั้งที่มีการส่งโค้ดขึ้น GitHub ระบบรันเคสทดสอบ 61 เคสด้วย AI จำลอง แล้วเทียบคำตอบของทุกเคสกับไฟล์ต้นแบบ (`tests/baselines/shadow_eval_mock.json`) ถ้ามีเคสไหนตอบต่างจากเดิม แม้แต่ช่องเดียว (หมวดของกฎ หมวดของ AI ความมั่นใจ การเห็นตรงกัน ความสำคัญ หรือเหตุผล) ช่องตรวจ *Core logic tests* จะเป็นสีแดง และหน้าผลรันจะบอกว่าเคสไหนเปลี่ยนอะไร ถ้าตั้งใจเปลี่ยน ต้องอัปเดตไฟล์ต้นแบบใน PR เดียวกันและเขียนเหตุผลไว้ ถ้าเปลี่ยน prompt หรือรุ่น AI ต้องแนบผลรันกับ AI จริงด้วย
8. **ใช้ AI จริงได้ฟรีผ่าน GitHub Models (ADR-020)** ไม่ต้องมีบัตรและไม่ต้องสร้างคีย์ ปุ่ม *Shadow eval with GitHub Models (manual)* ใน Actions ใช้สิทธิ์ของ GitHub เอง (`GITHUB_TOKEN` ที่อ่านรุ่น AI ได้อย่างเดียว) ส่งเคสสมมุติทั้ง 61 เคสให้รุ่นที่เลือก (ค่าเริ่มต้น `openai/gpt-4.1-mini`) ระดับฟรีจำกัดราว 15 ครั้งต่อนาทีและ 150 ครั้งต่อวัน ระบบจึงเว้นเคสละ 5 วินาที ผลที่ได้เป็นของรุ่นนั้น ไม่ใช่ของ Claude และหน้าผลจะเขียนบอกไว้ ถ้าระบบความปลอดภัยของผู้ให้บริการบล็อกข้อความเคสไหน (content filter) เคสนั้นนับเป็น "AI ไม่ตอบ" และไปถึงผู้รีวิวตามปกติ ไม่ทำให้งานล้ม

## How one case flows

```text
case ──► classify_rules (v1 keywords) ──┐
     └─► classify_llm   (AI)          ──┴─► compare ──► prepare ──► reviewer
```

1. `build_shadow_workflow` checks the case with the same input rules as v1. It freezes
   the AI settings (provider, model, prompt id and SHA-256) into the job.
2. Core runs `classify_rules` and `classify_llm` **in parallel**. They are independent
   branches, so a problem in the AI branch never stops the rules branch.
3. `classify_llm` masks personal data in the case text (`app/llm/redaction.py`), then sends the
   versioned prompt, with the masked text wrapped as a JSON string. The provider's structured output limits the answer to
   `{category, confidence, rationale}` with fixed choices. Our code checks the answer again.
4. `compare` lines the two up:
   - `agree`: normal priority.
   - `disagree`: **elevated** priority, with reason `rules_llm_disagree`.
   - `llm_unavailable`: normal priority, with reason `llm_unavailable`.
   - Extra reasons `llm_low_confidence` and `rules_no_keyword_match` add context.
5. `prepare` builds the reviewer's proposal. The **official suggestion is always the
   rules result**, and the AI's view is shown as `second_opinion`. The decision is always
   `PENDING_HUMAN_REVIEW`.
6. Core runs every step's validator before saving its output, checking three things:
   - **Schema:** the fields and types are right.
   - **Invariants:** the queue matches the category, and the provenance matches the frozen job settings.
   - **Policy:** there is no automatic decision, and review is always required.

## When something goes wrong

| Situation | What the system does | What the reviewer gets | Sentry |
|---|---|---|---|
| AI rate-limited, overloaded, server error, timeout, network (HTTP 408/429/5xx/529) | waits 2 s, tries once more | normal proposal | nothing |
| Still failing on the last attempt | AI part marked `unavailable: provider_unavailable` | rules suggestion + reason `llm_unavailable` | warning, grouped |
| AI answer off-contract (unknown value, broken JSON, cut off at `max_tokens`) | tries once more, then `unavailable: invalid_model_output` | same as above | warning |
| AI declines (`stop_reason: refusal`) | `unavailable: model_declined` at once (no pointless retry) | same as above | warning |
| Missing or rejected API key (401/403), unknown model (404), rejected request (400/413) | AI step **fails**; job `FAILED` | no proposal until fixed | error → email |
| Prompt file or model changed after a job was submitted | the old job refuses to run (`Agent version changed`) | — | exception |

Setup problems fail loudly on purpose. They hit every case the same way, and if
they were degraded quietly, a broken setup could go unnoticed.

## Safety rules built in

- **The AI never decides.** Every proposal is `PENDING_HUMAN_REVIEW`, and the validator rejects anything else.
- **The AI never picks the queue.** It returns a category only. The code maps the category to a queue, and the
  official suggestion stays with the rules.
- **Case text is untrusted.** It is sent as a JSON string, and the prompt says to ignore instructions inside it.
  Answers are limited to fixed choices, first by the API and then again by our code. The tests include
  injected instructions in English and Thai.
- **Personal data is masked before the AI sees the case** (roadmap 7.1). E-mail addresses, phone numbers,
  Thai ID numbers (check digit verified), card-like numbers (Luhn), other runs of 9+ digits, and names after
  a title or label (Mr/Ms/Dr, "my name is", `Name:`; นาย, นาง, นางสาว, น.ส., ด.ช., ด.ญ., นามสกุล, คุณ + an
  English name) become `[EMAIL]`, `[PHONE]`, `[THAI_ID]`, `[CARD]`, `[NUMBER]`, `[NAME]`. The gateway refuses
  text that did not go through `mask()`. The output's `masked` field counts each kind, never the values.
  Not detected: names without a title or label, Thai surnames after a given name, addresses, short numbers,
  mixed letter-and-digit identifiers. The keywords the rules and the AI need stay readable.
- **The API key is never stored.** It is read from `ANTHROPIC_API_KEY` (Claude) or `GITHUB_MODELS_TOKEN`
  (GitHub Models) at call time, never placed in the job, and the tests scan every stored file to confirm it
  is absent. Provider error messages are not copied
  (only the HTTP status and error type).
- **Every answer is traceable.** Each AI output records the provider, model, prompt id and prompt SHA-256.
  The served model and token usage are recorded too.
- **Current API rules are followed.** The Claude client uses structured output (`output_config.format`) and
  sends no `temperature`/`top_p`, because current Claude 5.5 models reject forced tool choice and sampling
  parameters. The GitHub Models client uses `response_format` with a strict `json_schema` built from the
  same answer schema, and sends no sampling parameters, tools or effort either.
- **A content-safety block is one declined case.** GitHub Models runs behind Azure AI content safety. An
  HTTP 400 `content_filter` reply (or `finish_reason: content_filter`, or a `refusal` message) becomes
  `unavailable: model_declined` at once, so the case still reaches review instead of failing the job.

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `NEURON_FLOW_LLM_PROVIDER` | `mock` | `mock` (offline keyword simulation), `anthropic` (Claude) or `github` (GitHub Models) |
| `NEURON_FLOW_LLM_MODEL` | `mock-keyword-1` / `claude-haiku-5-5` / `openai/gpt-4.1-mini` | model id; GitHub Models ids are `publisher/model` |
| `ANTHROPIC_API_KEY` | — | required for `anthropic`; checked before any job is submitted |
| `GITHUB_MODELS_TOKEN` | — | required for `github`; a token with the *Models: read* permission (in Actions, the workflow's `GITHUB_TOKEN` with `models: read`); checked before any job is submitted. A plain `GITHUB_TOKEN` is never picked up by itself |
| `NEURON_FLOW_LLM_MAX_TOKENS` | `2048` | answer budget (thinking tokens count too) |
| `NEURON_FLOW_LLM_TIMEOUT_S` | `30` | HTTP timeout; the step timeout is 15 s longer, so the agent can still report `unavailable` itself |
| `NEURON_FLOW_LLM_EFFORT` | not sent | optional `output_config.effort` for Claude models that support it; refused with `github` |
| `NEURON_FLOW_ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | Claude only; HTTPS only; no credentials in the URL |
| `NEURON_FLOW_GITHUB_MODELS_BASE_URL` | `https://models.github.ai/inference` | GitHub Models only (for example an organisation's `…/orgs/<org>/inference`); same URL rules |

## Measuring it: the scorecard

`python -m app.eval.triage_shadow_eval` runs every labelled case through the real
v2 workflow and reports each rate as numerator/denominator:

- **Rules correct / AI correct.** How often each picks the labelled category, split by language and tag.
- **Agreement.** How often the two agree.
- **Rule mistakes raised for review.** Of the cases the rules got wrong, how many were elevated.
  This shows whether the second opinion is useful.
- **Raises that were needed.** Of the elevated cases, how many really had a wrong rules suggestion.
  This shows whether reviewers get false alarms.
- **AI unavailable/failed, tokens, latency.** Running health and cost.
- **Cases both got wrong.** A list worth reading.

On GitHub, every push shows this table on the Actions run page, using the mock AI.

### The eval gate (roadmap 5.2)

Every push and pull request also checks each case's answer against a committed baseline:

```text
python -m app.eval.triage_shadow_eval --compare-with tests/baselines/shadow_eval_mock.json
```

- **What is compared, per case:** the case text (its SHA-256), the label, the job status, the rules'
  category, the AI's status, category, reason, confidence and attempts, the agreement, and the review
  priority and reasons. Timings and token counts are left out, because they change from run to run.
- **What else counts as a change:** a different case set (its SHA-256), prompt (id and SHA-256), or AI
  provider and model.
- **When something differs:** the command exits with 3, and the run page lists every difference as
  `<case id>: <field> <before> -> <after>`. The step runs even when the unit tests failed earlier in the
  job, so the list is always there. The unit test
  `test_the_committed_baseline_matches_a_fresh_mock_run` runs the same check, so `python -m unittest`
  catches it locally too.
- **Changing answers on purpose:** regenerate the baseline in the same pull request and say why in its
  description:

  ```text
  python -m app.eval.triage_shadow_eval --write-baseline tests/baselines/shadow_eval_mock.json
  ```

  The file has one case per line, so the pull request's diff shows exactly which cases changed. A prompt
  or model change also needs a live run by hand (*Actions → Shadow eval with Claude* or *with GitHub
  Models*), attached to the pull request.
- **Comparing two runs:** `--compare-with` also accepts a full report written with `--out`, for example to
  list where a live run differs from the mock. `compare_reports` (through
  `neuron_flow.evaluation.candidate_gate`) still compares the AI outcomes of two reports from Python.
- **Where the baseline lives:** in `tests/`, so a baseline-only change does not redeploy Render.

The mock AI's keyword list was written alongside the synthetic case set, so its
score is inflated by design. The mock run proves that the pipeline and the measurement work.
It does not show AI accuracy.

## Turning on a real model for free: GitHub Models (no key, no card)

1. Open **Actions → Shadow eval with GitHub Models (manual) → Run workflow**. Keep the model
   (`openai/gpt-4.1-mini`) and set `limit` to 5 for a first try. Nothing needs to be set up: the workflow
   grants its own `GITHUB_TOKEN` only `contents: read` and `models: read`.
2. The run first lists the model ids GitHub offers today, with their rate-limit tier, in a folded section
   of the run page, then sends one fixed synthetic sentence and shows the reply as it arrived (status, content
   type, rate-limit headers, first characters) and how the provider classified it
   (`.github/scripts/github_models_probe.py`; never the token, never a case). OpenAI retires `gpt-4.1-mini` on 2027-01-14; pick another low-tier id from that list
   then.
3. Cases start at least 5 seconds apart (`--min-interval-s 5`), because the free low tier allows about 15
   requests a minute and 150 a day per model. All 61 cases take about 6 minutes.
4. Read the scorecard on the run page, or download `shadow-eval-github-models.json`. When the AI gave no
   answer, a line under the table counts why (for example `unavailable: invalid_model_output 5`). The page says the
   numbers belong to that model, not to Claude. Many "unavailable" answers usually mean the daily limit
   was reached: run again the next day.

## Turning on real Claude (no local computer needed; needs D2)

1. Create an API key in the Claude Console.
2. On GitHub, add a repository secret: **Settings → Secrets and variables →
   Actions → New repository secret**, named `ANTHROPIC_API_KEY`.
3. Open **Actions → Shadow eval with Claude (manual) → Run workflow**. For a first try, set
   `limit` to 5. This workflow is available now.
4. Read the scorecard on the run page, or download `shadow-eval-claude.json`.

## Code map

| File | Role |
|---|---|
| `app/llm/config.py` | provider/model settings frozen into each job; never holds the key |
| `app/llm/prompt_library/triage_classify_v1.json` | the prompt and answer schema (one file, one SHA-256) |
| `app/llm/gateway.py` | asks the provider and checks the answer's shape |
| `app/llm/providers/anthropic.py` | Claude Messages API over the standard library |
| `app/llm/providers/github_models.py` | GitHub Models chat completions over the standard library (ADR-020) |
| `app/llm/providers/_http.py` | the shared HTTP opener that refuses every redirect |
| `.github/workflows/shadow-eval-github-models.yml` | the free live run; `.github/scripts/github_models_catalog.py` lists the model ids |
| `app/llm/providers/mock.py` | offline keyword simulation + failure scenarios for tests |
| `app/domains/case_triage/shadow_agents.py` | the AI, compare and prepare agents and their validators |
| `app/domains/case_triage/shadow_workflow.py` | trusted registry and the four-step DAG |
| `app/eval/triage_shadow_eval.py` + `app/eval/golden/` | scorecard and 61 labelled synthetic cases (EN + TH) |
| `tests/baselines/shadow_eval_mock.json` | every case's answer with the mock AI: the eval gate's baseline |
| `examples/case_triage_shadow_demo.py` | three cases explained step by step |

## Limits

- Synthetic cases labelled by the developer. These are not real customer data and not independent ground truth.
- Masking is pattern-based (see "Safety rules built in"). It lowers the risk; it does not make real
  personal data safe to send.
- No real model has run yet, so there are no accuracy, latency or cost claims for Claude or for any GitHub
  Models model. A GitHub Models result, once measured, describes that model only.
- GitHub's free tier is rate-limited and its data terms were not reviewed here; synthetic data only.
- Token counts cover answered calls only. No money estimate is made, because prices change.
- Shadow mode does not reduce reviewer work. It orders that work and explains it.
- Core's single-machine limits still apply. Agent child processes are not a security sandbox.
