# System Neuron Flow AI

A small, inspectable workflow runtime that coordinates **trusted agents**, including AI agents. It talks in
plain language on the outside and does deep, checked work inside. It runs on a single machine and uses only
the Python standard library; `sentry-sdk` is an optional extra.

> ภาษาไทย: ระบบที่คุยด้วยภาษาธรรมดา แต่ภายในทำงานลึกและตรวจสอบได้ ดู [หลักปรัชญาการออกแบบ](docs/design_philosophy.md)

## For visitors

- **Status:** an early prototype kept by one person. It runs on synthetic data only and is not ready for real
  users; see [Scope and limits](#scope-and-limits). The online demo answers `/v1` requests only with an access
  key that is not published.
- **How it is built:** the code and docs are written with AI coding agents (Claude Code and Codex) under the
  owner's direction. Changes go through pull requests with automated tests and an automated review, and the
  owner decides what is merged. Numbers in the docs are measured, and the docs say when a result comes from
  the mock AI or from one live model.
- **History:** the git history is kept in full, including the earlier application this project was extracted
  from ([Origin](#origin)).
- **Questions and bugs:** open an issue. **Security problems:** report them privately, as
  [SECURITY.md](SECURITY.md) describes.
- **License:** [GPL-3.0-only](LICENSE).

## Design philosophy

Set by the project owner, and the compass for every feature ([full text](docs/design_philosophy.md)):

1. **Plain language outside, deep work inside.** Everyday words and metaphors in; structured, checked work inside.
2. **Understand, then elaborate on request.** Summary first, details when asked.
3. **Stay inside the frame.** The frame is versioned data; "out of scope" is an honest answer.
4. **AI proposes, code verifies, people decide what matters.**
5. **No perfectionism.** Small measured steps, honest uncertainty.
6. **Equitable support without being asked.** When someone starts talking about technology, the first
   response offers study resources, explains what each one is for, and says which topics to study first.

## What it does today

The working example is support-case triage in **shadow mode** (case_triage v2):

1. A case comes in, for example "I cannot upload an attachment" (English or Thai).
2. Versioned Thai/English keyword rules (`keywords-v2`) suggest a queue in shadow mode. This stays the **official** suggestion; `case_triage.v1` retains the original English-only demonstration.
3. At the same time an AI model gives a **second opinion**. If the AI is briefly unavailable, it is retried
   once; if it is still unavailable, the case continues on the rules alone. A setup problem (for example a
   bad key) fails loudly.
4. When rules and AI disagree, the case is raised to **elevated** review priority, with the reasons.
5. A human reviewer always decides (`PENDING_HUMAN_REVIEW`): on the web page, or through
   `POST /v1/reviews/{review_id}/decisions`, a person approves (with the rules' category or another) or rejects
   the case with a reason, and the case ends `APPROVED` or `REJECTED`. Failures and degraded AI answers are
   reported to Sentry.
6. Before the AI sees a case, recognisable personal data (e-mail, phone, ID, card and long numbers, names
   after a title) is replaced with placeholders such as `[PHONE]`. The AI gateway checks this itself and
   refuses to send text that still holds anything the rules would mask.

Since round 2, cases can also come in from outside, through an HTTP API or a Thai web page:

1. A case is checked, then stored in a durable queue before the reply ("received"). Sending the same
   request twice never creates two jobs.
2. One Runner takes the cases in order and passes each one to the Core.
3. If the machine stops in the middle of a case, the Runner picks it up again after the restart, within the
   same retry budget, or fails it with a clear reason.
4. The page works like a chat: type a case, check the steps it will run, confirm, then follow it in the
   Flow panel and its event history (Trace). The result is explained in plain language, and the settings
   are shown read-only. Details: [intake_queue.md](docs/intake_queue.md).
5. A case that is still waiting can be cancelled, and every request carries a request id that links the
   access log to the job record.
6. The page shows how many cases wait and for how long, how long cases usually take (median and slowest,
   per workflow) and why recent ones failed.
7. With a Honeycomb key in the environment, every case also becomes one trace: the request, the queue
   wait, each step attempt and the AI call with its tokens. No case text, prompt, AI answer or key is ever
   sent. Details: [observability_tracing.md](docs/observability_tracing.md).

Since roadmap 3.2, a second, unrelated workflow runs on the same Core with no Core change: the **study
guide** (`study_guide.v1`, the owner's first-response rule):

1. A person writes what they want to learn in everyday words or a metaphor, in Thai or English.
2. The AI maps it to one topic of a versioned catalog, or answers "out of scope". It cannot answer a topic
   that is not in the catalog.
3. Rules pick at most 5 resources from a verified library, in the person's language and free ones first,
   and order them: background topics first, then easy to hard.
4. The AI writes one plain sentence per resource. It never sees or writes a URL; code inserts every link
   from the library.
5. The answer comes in layers (a one-line summary, the steps, the details) and asks "did I understand you
   correctly?". Out of scope, it says honestly what it can help with. It decides nothing, so it needs no
   review. Details: [study_guide.md](docs/study_guide.md).
6. On the web page (roadmap 3.4), a switch above the message box chooses a case or a study question. A
   question is sent at once, without the confirm step a case has (ADR-023); the answer shows the summary,
   where to start and the most important resource first, and the steps and details when opened.

## What is inside

| Part | Where | Status |
|---|---|---|
| Core runtime: DAG workflows, bounded child processes, retries, restart recovery, verified receipts | `neuron_flow/` | Working; two planned fixes since extraction: telemetry phase names (PR #21) and `decode()`'s error contract (ADR-025, PR #42) |
| Case triage v1: deterministic keyword rules | `app/domains/case_triage/agents.py`, `workflow.py` | Working |
| Case triage v2: shadow mode with AI second opinion | `app/domains/case_triage/rules.py`, `keywords_v2.json`, `shadow_*.py` | Thai/English official rules built in PR #64 (E2, [evidence](docs/evidence/2026-11-11-e2-rules-v2.md)); original v1 demo retained. Working with the offline mock AI; Claude and Typhoon paths tested against a fake API; **first live runs with Typhoon** on 2026-11-06 (synthetic set, [evidence](docs/evidence/2026-11-06-first-live-typhoon.md)); Claude not run yet |
| AI gateway: versioned prompt, mock, Claude, Typhoon and local open-model providers | `app/llm/` | Working (see above); Typhoon (SCB 10X, Thai-first) is free within rate limits (ADR-021) and is told the answer format in words, because it ignores `response_format` (ADR-022); `local` sends the same requests to a server we run ourselves, by default llama.cpp on 127.0.0.1 with no key (ADR-026) |
| Error monitoring and tracing | `app/observability/` | Sentry errors, degraded-AI warnings and Runner recoveries; traces to Honeycomb (OTLP), off until a key is set; on for the Render service, first trace seen 2026-11-03 |
| Scorecards: 61 development triage cases, 116 robustness triage cases, 40 held-out triage cases, and 67 study-guide requests (EN + TH, metaphors, out of scope, injection) | `app/eval/` | The 61 triage and 67 study-guide cases are CI eval gates; the robustness gate covers the 116 edge cases. Held-out measurement and the three-set live comparison are manual. Mock scores test the pipeline, not AI accuracy |
| Robustness benchmark, stage 1: 270 hard synthetic edge cases (EN + TH) and four pinned open datasets (BLNS, JSONTestSuite, CLINC150, BANKING77) through every layer, offline | `tests/robustness/` | Runs in CI as a gate on every outcome; the first run found 8 bugs, all fixed in roadmap 5.5 (now 0 bugs, 239/270 own items pass after E2). Plan for stages 2–3: [benchmarking.md](docs/benchmarking.md) |
| Open benchmarks (stage 2) and auto-approve limits: CLINC150, BANKING77, MASSIVE Thai/English pairs and BIPIA's injection attacks built at run time from pinned public files, a 128-case hard set, and a **simulated** button that would send a case without a person when the system is confident | `tests/open_benchmarks/`, `app/eval/autosend_sim.py` | Built and measured with Typhoon on 2026-11-11 (roadmap 5.6, 5.9; ADR-031; [design](docs/autosend_simulation.md), [evidence](docs/evidence/2026-11-11-autosend-limits.md)). A replay only: the service never sends without a person |
| Attention signals: plain code that raises the cases a person should see first (distress or danger, a security incident, a legal or privacy request, text that tries to steer routing or approval), with a 64-case held-out set | `app/domains/case_triage/signals.py`, `app/eval/attention_replay.py` | Built and measured on 2026-11-11 (ADR-032, PR #67; [evidence](docs/evidence/2026-11-11-attention-signals.md)): raised `needs_person` cases 6/38 → 38/38 on the set the phrases were written against (saved Typhoon answers) and 12/32 → 29/32 on the held-out set (live Typhoon); 6 of 21 BANKING77 security-intent cases and none of BIPIA's 75 attacks. Phrase lists, not a safety classifier; every case still waits for a person |
| Intake API, durable job queue, single Runner with crash recovery, Thai web page | `app/api/`, `app/persistence/`, `app/services/`, `app/web/`, `app/serve.py` | Working (round 2), tested offline and as a container in CI; live on Render's free plan since 2026-11-01 |
| Study guide (`study_guide.v1`): versioned topic catalog (11 topics, Thai and English), verified resource library (17 links) with a weekly link check, and the five-step workflow | `app/domains/study_guide/` | Working through the API and on the web page (roadmap 3.1–3.4); mock AI in CI; **first live run with Typhoon** on 2026-11-06 (synthetic set). New work paused by the owner on 2026-11-11; its checks keep running |
| Human-review decisions: a ledger, a decisions API and a decision card with a "รอรีวิว" list on the page | `app/services/reviews.py`, `app/persistence/queue_store.py`, `app/web/` | Working since 2026-11-10 (roadmap 2.2, 2.4), with the owner's shared key as the only reviewer (ADR-027) |
| Per-person reviewer tokens, n8n intake, reviewer notifications | — | **Not built yet** (Milestone C in [architecture](docs/architecture.md)) |
| Skill handoff: separate skills that pass work through one exchange, with a translator on each side of a common language; the first route starts the linked job after an approval (roadmap 2.3) | `app/exchange/`, `app/domains/case_triage/apply.py` | **Working since 2026-11-11** (ADR-030, [design and tests](docs/skill_handoff.md)): checked over all 217 triage cases end to end; the first new skill waits for the owner's choice |

## Try it

**Online, on Render:** `render.yaml` describes the whole service, so setup is New → Blueprint in the Render
Dashboard; the step-by-step guide is in [intake_queue.md](docs/intake_queue.md) (in Thai). Render generates
the access key (`NEURON_FLOW_ACCESS_KEY`) and deploys `main` only when the GitHub checks pass. A merge that
changes only docs, tests or CI files does not redeploy (`buildFilter` in `render.yaml`). The free plan
forgets its cases, reviews and decisions when it sleeps, restarts or redeploys, and the API and the page say
so; a paid plan with a disk keeps them.

**On GitHub, no local setup needed:**
- *Actions → Core logic tests* runs every test on Python 3.10 and 3.12, plus the demos and both scorecards.
  The scorecard tables and the study guide's example answers appear on the run page. The eval gates then
  compare every case's answer with `tests/baselines/shadow_eval_mock.json` and
  `tests/baselines/study_guide_eval_mock.json` and fail on any change. The study guide's scorecard also
  fails when an answer has a link outside the library or more than 5 resources. Then the robustness benchmark sends
  the edge cases and open datasets through every layer and compares every outcome with
  `tests/baselines/robustness_v1.json` (docs/benchmarking.md). Its summary, in Thai, is on the run page too.
  The 128 hard auto-send cases are compared with `tests/baselines/autosend_hard_mock.json` too, and the
  auto-approve simulation replays them (a table on the run page; it fails only if a real job did not wait for
  a person). Last, one case goes step by step through the skill-handoff exchange, and every case of the three
  triage sets goes end to end through a decision and the follow-up job it starts (`tests/handoff_check.py`);
  both are on the run page.
- *Actions → Auto-approve limits (open benchmarks + hard set)* builds the open-benchmark sets from pinned public
  files, scores them with Typhoon (or the mock) with the hard set and the existing sets, and simulates the
  auto-approve button on every answer ([docs/autosend_simulation.md](docs/autosend_simulation.md)).
- *Actions → Service container* checks `render.yaml`, builds the same container as Render, submits cases
  over HTTP, approves one and checks the follow-up job it hands on to, restarts it and checks that nothing was
  lost. It also fails when the image lacks a bytecode
  cache for any of its code, and reports how long the first case after a start takes.
- *Actions → Sentry smoke test* checks that error reporting reaches Sentry. It needs the repository secret
  `SENTRY_DSN`; without it, it skips with a notice.
- *Actions → Secret scan* checks every commit of every branch for keys and tokens (gitleaks) on every push
  and pull request, and that new commits carry no personal e-mail address (a pull request fails, a push
  warns; the summary counts the commits in the whole history that carry one).
- *Actions → Study library link check* opens every link in the study-guide library every Monday and on
  every change to it, and fails when one is broken. It never edits the library.
- *Actions → Shadow eval with Typhoon (manual)* and *Study guide eval with Typhoon (manual)* run the two
  scorecards against Typhoon, free within its rate limits. They need the repository secret
  `TYPHOON_API_KEY`, and first check the connection with one fixed sentence (ADR-021). The shadow eval can
  run the 116 robustness edge cases instead of the 61 cases (`case_set: robustness_edge_v1`).
- *Actions → Local open model eval* runs both scorecards against an open-weight model that the job runs
  itself: llama.cpp's server, built from a pinned commit, serving Typhoon 2.5 Qwen3 4B (Apache-2.0) from a
  file checked against its SHA-256, on 127.0.0.1 of the runner (ADR-026). No secret, nothing sent to an AI
  company, CPU only. Pull requests that change `app/llm/` get a 5-case smoke run.
- *Actions → Shadow eval with Claude (manual)* runs the scorecard against real Claude. It needs the
  repository secret `ANTHROPIC_API_KEY`.
- *Actions → Study guide eval with Claude (manual)* runs the study guide's scorecard against real Claude, with
  the same secret.

**Locally (Python 3.10+):**
```bash
python -m unittest discover -s tests -v        # 509 tests
python -m examples.case_triage_demo            # v1 rules, one synthetic case
python -m examples.case_triage_shadow_demo     # v2 shadow mode, three synthetic cases (offline mock AI)
python -m app.eval.triage_shadow_eval          # scorecard on 61 synthetic cases
python -m examples.study_guide_demo            # the study guide's answers to four synthetic requests
python -m app.eval.study_guide_eval            # the study guide's scorecard on 67 synthetic requests
NEURON_FLOW_ACCESS_KEY=<16+ characters> python -m app.serve   # API + web page on http://localhost:8000
```
With `NEURON_FLOW_LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY` set, the same commands use Claude; with
`NEURON_FLOW_LLM_PROVIDER=typhoon` and `TYPHOON_API_KEY`, Typhoon. Add `--min-interval-s 1` to a scorecard
on Typhoon's free API. With `NEURON_FLOW_LLM_PROVIDER=local`, they call an OpenAI-format server on
`http://127.0.0.1:8080/v1` (change it with `NEURON_FLOW_LOCAL_BASE_URL`); set `NEURON_FLOW_LLM_TIMEOUT_S`
higher on a CPU.

## Embedding the Core

Pass an explicit list of `AgentDefinition(name, entrypoint, validator, version)` to
`Runtime(workspace, agents=[...])`. Agents must be trusted, importable Python callables; the runtime does
**not** run untrusted code safely. Submit with `runtime.submit(workflow)` (or `runtime.ingest`), where the
workflow has `job_id`, `input` and `steps`. Each step names a registered `agent` and may set
`depends_on`, `params`, `timeout_s`, `max_attempts` (1–5) and `retry_delay_s`. Messages are JSON only, at
most 1 MiB. The agent `version` is frozen into each job, so an old job refuses to run on changed agents.

## Documentation

| Document | What it is for |
|---|---|
| [Roadmap](docs/ROADMAP.md) | What to build next, in order: tasks, acceptance checks, owner tests and owner decisions |
| [CLAUDE.md](CLAUDE.md) | How Claude Code works on this repo: working with the owner, rules, checks, definition of done |
| [Security policy](SECURITY.md) | How to report a vulnerability privately, and what is in scope |
| [Design philosophy](docs/design_philosophy.md) | The owner's principles, the first-response rule and study resources (mostly Thai) |
| [Architecture](docs/architecture.md) | Layers, Core constraints, how AI fits, decisions (ADRs), milestones and their status |
| [case_triage v1](docs/case_triage_pilot.md) | The deterministic keyword rules |
| [case_triage v2 shadow mode](docs/case_triage_v2_shadow.md) | The AI second opinion: flow, failure handling, configuration, scorecard |
| [Intake API, queue, Runner and web page](docs/intake_queue.md) | Round 2: how a case flows from outside, recovery rules, API reference, Render setup |
| [Sentry error reporting](docs/observability_sentry.md) | What gets reported, privacy rules, alerts |
| [Tracing to Honeycomb](docs/observability_tracing.md) | One trace per case: what a span carries and never carries, setup in Render, how it is checked |
| [Study guide](docs/study_guide.md) | `study_guide.v1`: the workflow and its answer, failure handling, the mock's limits; the scorecard; the box and layered answer on the web page; the topic catalog and verified library, the weekly link check |
| [Effectiveness plan](docs/effectiveness_plan.md) | What "effective" means here, as eleven measures with today's values, and six planned work packages (E1 to E6) that move them: a faster first case, rules that read Thai, a real model behind the page, recorded feedback, the edge of `other`, more Thai study resources |
| [Skill handoff](docs/skill_handoff.md) | How separate skills pass work to each other: one exchange, fixed versioned routes, a common language with a translator on each side; what is recorded and shown, every refusal, and how it is tested |
| [Benchmarking plan](docs/benchmarking.md) | Three stages of testing beyond our own cases: the robustness gate (built), open benchmarks (built), attacks, privacy, load and live drift (first injection measurement done; the rest planned); the datasets, their licences and the ones left out |
| [Auto-approve limits](docs/autosend_simulation.md) | What a button that sends a case without a person would do, simulated on saved answers: the hard set, the open benchmarks, the four policies, what is measured, and what a real button would need (ADR-031) |
| [Funding readiness pack](docs/funding/README.md) | Internal evidence register; not a submitted application |
| [Evidence notes](docs/evidence/2026-11-03-render-operations.md) | Dated measurements; the first one covers Render operations (graceful stops, deploy filter, cold start), and [the first live AI runs](docs/evidence/2026-11-06-first-live-typhoon.md) are Typhoon's (2026-11-06); [the first robustness run](docs/evidence/2026-11-07-robustness-stage1.md) is from 2026-11-07, and [the local open model's first smoke run](docs/evidence/2026-11-08-first-local-model-smoke.md) and [first full run](docs/evidence/2026-11-08-first-local-model-full.md) from 2026-11-08; [the effectiveness baseline](docs/evidence/2026-11-10-effectiveness-baseline.md) (the 116 edge cases with Typhoon, and the first job after a start) is from 2026-11-10, and so is [the image's bytecode cache, before and after](docs/evidence/2026-11-10-e1-bytecode-cache.md) (measured in CI, not yet on Render), and [the answer to the first independent review](docs/evidence/2026-11-10-independent-review-response.md) |

## Scope and limits

- Runs on one machine. No service-level agreement. The online service is protected by one shared access
  key, not per-person accounts, so every review decision is recorded as the owner's; it uses Python's
  standard-library HTTP server (fine for a pilot, not for public traffic).
- An independent review of the code and docs (2026-11-10) found four problems; all four are answered
  ([evidence](docs/evidence/2026-11-10-independent-review-response.md)). One is left to the owner: one of the
  owner's personal e-mail addresses is visible in 53 commits of this public history (D8 in the roadmap).
- Agent child processes isolate failures; they are **not** a security sandbox.
- All test data is synthetic. The open datasets in the robustness benchmark were written for those datasets and hold no real people's records (ADR-024). Mock AI scores are not evidence of AI accuracy: the triage mock scores high because its keywords were written with its cases, and the study guide mock scores low (topic correct 2/48).
- Masking personal data before AI calls is pattern-based; it lowers the risk but does not make real data safe.
- The only real-model runs are on synthetic sets and openly licensed text written for datasets, with two free
  models by SCB 10X:
  - Typhoon's 30B model through its API (2026-11-06, [evidence](docs/evidence/2026-11-06-first-live-typhoon.md)):
    triage AI correct 60/61 in two runs (the rules 29/61), study guide topic correct 46/48 with no link
    outside the library; and on the 116 robustness edge cases (2026-11-10,
    [evidence](docs/evidence/2026-11-10-effectiveness-baseline.md)) AI correct 104/116 (the rules 48/116);
    and once on 1,320 cases for the auto-approve limits (2026-11-11,
    [evidence](docs/evidence/2026-11-11-autosend-limits.md)): it said `high` on 1,288 of 1,318 answers, 149 of
    its 156 mistakes among them, and a simulated button that sends when rules and AI agree would have let 32
    of the hard set's 38 cases that need a person through;
  - the local open model, Typhoon 2.5 4B run on the GitHub runner (ADR-026; 2026-11-08, two smoke runs and
    [one full run](docs/evidence/2026-11-08-first-local-model-full.md)): triage AI correct 58/61 with all 32
    of the rules' mistakes raised for review, study guide topic correct 44/48 with no link outside the
    library, at about 7 times Typhoon's latency.

  The cases and labels are the developer's and the runs are few, so these numbers are a first measurement
  of each model, not accuracy, and say nothing about Claude, which has not been run. No cost claims are made.
- The study guide's mock AI is a keyword simulation: it cannot read a new metaphor. On the 67-request
  scorecard it finds the right topic for 2 of 48 in-scope requests, so its answers prove the workflow runs,
  not that it understands people.

## Origin

Extracted on 2026-10-31 (commit `09100f7`) from the original Neuron Flow document/finance application.
Purchase and invoice agents, CSV/OCR/PDF adapters, the old HTTP/CLI wrappers and the business fixtures
remain only in that earlier history. License: GPL-3.0-only.
