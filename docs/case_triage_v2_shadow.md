# case_triage v2 — shadow mode (AI second opinion)

**Status:** on `main` since 2026-11-01 (PR #9). Implemented and tested with the offline mock AI. The
Claude code path is tested against a local fake API server. It has **not yet been run against the real
Claude API**, because that needs an `ANTHROPIC_API_KEY`. Synthetic data only. This is not a production
service, public API or human-review service. No Core (`neuron_flow/`) file was changed. Design principles:
[design_philosophy.md](design_philosophy.md).

## ภาพรวมการทำงาน (สรุปภาษาไทย)

1. มีเคสลูกค้าเข้ามา 1 เคส (รหัสเคส + ข้อความ)
2. **กฎเดิม** (คำสำคัญภาษาอังกฤษ) เสนอคิวที่ควรส่งไป ข้อเสนอนี้คือ "ข้อเสนอหลัก" เหมือนเดิม
3. พร้อมกันนั้น **AI** อ่านเคสเดียวกันแล้วเสนอหมวดของตัวเอง (ความเห็นที่สอง)
   - ถ้า AI ติดขัดชั่วคราว ระบบลองใหม่ 1 ครั้ง
   - ถ้ายังไม่ได้ หรือ AI ปฏิเสธที่จะตอบ ระบบเดินต่อโดยใช้ข้อเสนอของกฎ และแจ้งผู้รีวิวว่า "AI ใช้งานไม่ได้"
   - ถ้าตั้งค่าผิด (เช่น API key ผิด) ระบบหยุดเคสนั้นและแจ้งเตือนทาง Sentry/อีเมล
4. ระบบ **เทียบ** สองความเห็น ถ้าไม่ตรงกัน เคสถูกยกเป็น "ต้องดูก่อน" (priority elevated) พร้อมเหตุผล
5. ผู้รีวิวได้รับข้อเสนอที่ **รอคนตัดสินเสมอ** (PENDING_HUMAN_REVIEW) AI ไม่มีสิทธิ์ตัดสินหรือเปลี่ยนคิวเอง
6. ทุกคำตอบของ AI ถูกบันทึกว่ามาจากรุ่นไหน ใช้ prompt ฉบับไหน ถ้าเปลี่ยน prompt หรือรุ่น AI งานเก่าจะไม่ถูกรันซ้ำด้วยค่าใหม่โดยไม่รู้ตัว

## How one case flows

```text
case ──► classify_rules (v1 keywords) ──┐
     └─► classify_llm   (AI)          ──┴─► compare ──► prepare ──► reviewer
```

1. `build_shadow_workflow` checks the case with the same input rules as v1. It freezes
   the AI settings (provider, model, prompt id and SHA-256) into the job.
2. Core runs `classify_rules` and `classify_llm` **in parallel**. They are independent
   branches, so a problem in the AI branch never stops the rules branch.
3. `classify_llm` sends the versioned prompt, with the case text wrapped as a JSON
   string. The provider's structured output limits the answer to
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
- **The API key is never stored.** It is read from `ANTHROPIC_API_KEY` at call time, never placed in the job,
  and the tests scan every stored file to confirm it is absent. Provider error messages are not copied
  (only the HTTP status and error type).
- **Every answer is traceable.** Each AI output records the provider, model, prompt id and prompt SHA-256.
  The served model and token usage are recorded too.
- **Current API rules are followed.** The client uses structured output (`output_config.format`) and sends no
  `temperature`/`top_p`, because current Claude 5.5 models reject forced tool choice and sampling
  parameters.

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `NEURON_FLOW_LLM_PROVIDER` | `mock` | `mock` (offline keyword simulation) or `anthropic` (Claude) |
| `NEURON_FLOW_LLM_MODEL` | `mock-keyword-1` / `claude-haiku-5-5` | model id |
| `ANTHROPIC_API_KEY` | — | required for `anthropic`; checked before any job is submitted |
| `NEURON_FLOW_LLM_MAX_TOKENS` | `2048` | answer budget (thinking tokens count too) |
| `NEURON_FLOW_LLM_TIMEOUT_S` | `30` | HTTP timeout; the step timeout is 15 s longer, so the agent can still report `unavailable` itself |
| `NEURON_FLOW_LLM_EFFORT` | not sent | optional `output_config.effort` for models that support it |
| `NEURON_FLOW_ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | HTTPS only; no credentials in the URL |

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
`--compare-with old_report.json` flags **any** change in the AI's per-case answers
(through `neuron_flow.evaluation.candidate_gate`). Run it before switching prompt or model.

The mock AI's keyword list was written alongside the synthetic case set, so its
score is inflated by design. The mock run proves that the pipeline and the measurement work.
It does not show AI accuracy.

## Turning on real Claude (no local computer needed)

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
| `app/llm/providers/mock.py` | offline keyword simulation + failure scenarios for tests |
| `app/domains/case_triage/shadow_agents.py` | the AI, compare and prepare agents and their validators |
| `app/domains/case_triage/shadow_workflow.py` | trusted registry and the four-step DAG |
| `app/eval/triage_shadow_eval.py` + `app/eval/golden/` | scorecard and 61 labelled synthetic cases (EN + TH) |
| `examples/case_triage_shadow_demo.py` | three cases explained step by step |

## Limits

- Synthetic cases labelled by the developer. These are not real customer data and not independent ground truth.
- The real Claude path has not been run live yet, so there are no accuracy, latency or cost claims for Claude.
- Token counts cover answered calls only. No money estimate is made, because prices change.
- Shadow mode does not reduce reviewer work. It orders that work and explains it.
- Core's single-machine limits still apply. Agent child processes are not a security sandbox.
