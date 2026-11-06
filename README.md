# System Neuron Flow AI

A small, inspectable workflow runtime that coordinates **trusted agents**, including AI agents. It talks in
plain language on the outside and does deep, checked work inside. It runs on a single machine and uses only
the Python standard library; `sentry-sdk` is an optional extra.

> ภาษาไทย: ระบบที่คุยด้วยภาษาธรรมดา แต่ภายในทำงานลึกและตรวจสอบได้ ดู [หลักปรัชญาการออกแบบ](docs/design_philosophy.md)

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
2. The v1 keyword rules suggest a queue. This stays the **official** suggestion.
3. At the same time an AI model gives a **second opinion**. If the AI is briefly unavailable, it is retried
   once; if it is still unavailable, the case continues on the rules alone. A setup problem (for example a
   bad key) fails loudly.
4. When rules and AI disagree, the case is raised to **elevated** review priority, with the reasons.
5. A human reviewer always decides (`PENDING_HUMAN_REVIEW`). Failures and degraded AI answers are reported
   to Sentry.
6. Before the AI sees a case, recognisable personal data (e-mail, phone, ID, card and long numbers, names
   after a title) is replaced with placeholders such as `[PHONE]`.

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

## What is inside

| Part | Where | Status |
|---|---|---|
| Core runtime: DAG workflows, bounded child processes, retries, restart recovery, verified receipts | `neuron_flow/` | Working; one planned fix since extraction (telemetry phase names, PR #21) |
| Case triage v1: deterministic keyword rules | `app/domains/case_triage/agents.py`, `workflow.py` | Working |
| Case triage v2: shadow mode with AI second opinion | `app/domains/case_triage/shadow_*.py` | Working with the offline mock AI; Claude path tested against a fake API, **not yet run against the real Claude API** |
| AI gateway: versioned prompt, mock and Claude providers | `app/llm/` | Working (see above) |
| Error monitoring and tracing | `app/observability/` | Sentry errors, degraded-AI warnings and Runner recoveries; traces to Honeycomb (OTLP), off until a key is set; on for the Render service, first trace seen 2026-11-03 |
| Scorecards: 61 synthetic labelled triage cases, and 67 study-guide requests (EN + TH, metaphors, out of scope, injection) | `app/eval/` | Run in CI as eval gates; mock scores test the pipeline, not AI accuracy |
| Intake API, durable job queue, single Runner with crash recovery, Thai web page | `app/api/`, `app/persistence/`, `app/services/`, `app/web/`, `app/serve.py` | Working (round 2), tested offline and as a container in CI; live on Render's free plan since 2026-11-01 |
| Study guide (`study_guide.v1`): versioned topic catalog (11 topics, Thai and English), verified resource library (17 links) with a weekly link check, and the five-step workflow | `app/domains/study_guide/` | Working with the offline mock AI through the API (roadmap 3.1, 3.2); **not yet run against real Claude**; no box on the web page yet (3.4) |
| Human-review decisions, n8n intake, reviewer notifications | — | **Not built yet** (Milestone C in [architecture](docs/architecture.md)) |

## Try it

**Online, on Render:** `render.yaml` describes the whole service, so setup is New → Blueprint in the Render
Dashboard; the step-by-step guide is in [intake_queue.md](docs/intake_queue.md) (in Thai). Render generates
the access key (`NEURON_FLOW_ACCESS_KEY`) and deploys `main` only when the GitHub checks pass. A merge that
changes only docs, tests or CI files does not redeploy (`buildFilter` in `render.yaml`). The free plan
forgets its cases when it sleeps or redeploys; a paid plan with a disk keeps them.

**On GitHub, no local setup needed:**
- *Actions → Core logic tests* runs every test on Python 3.10 and 3.12, plus the demos and both scorecards.
  The scorecard tables and the study guide's example answers appear on the run page. The eval gates then
  compare every case's answer with `tests/baselines/shadow_eval_mock.json` and
  `tests/baselines/study_guide_eval_mock.json` and fail on any change. The study guide's scorecard also
  fails when an answer has a link outside the library or more than 5 resources.
- *Actions → Service container* checks `render.yaml`, builds the same container as Render, submits cases
  over HTTP, restarts it and checks that nothing was lost.
- *Actions → Sentry smoke test* checks that error reporting reaches Sentry. It needs the repository secret
  `SENTRY_DSN`; without it, it skips with a notice.
- *Actions → Secret scan* checks every commit of every branch for keys and tokens (gitleaks) on every push
  and pull request.
- *Actions → Study library link check* opens every link in the study-guide library every Monday and on
  every change to it, and fails when one is broken. It never edits the library.
- *Actions → Shadow eval with Claude (manual)* runs the scorecard against real Claude. It needs the
  repository secret `ANTHROPIC_API_KEY`.
- *Actions → Study guide eval with Claude (manual)* runs the study guide's scorecard against real Claude, with
  the same secret.

**Locally (Python 3.10+):**
```bash
python -m unittest discover -s tests -v        # 243 tests
python -m examples.case_triage_demo            # v1 rules, one synthetic case
python -m examples.case_triage_shadow_demo     # v2 shadow mode, three synthetic cases (offline mock AI)
python -m app.eval.triage_shadow_eval          # scorecard on 61 synthetic cases
python -m examples.study_guide_demo            # the study guide's answers to four synthetic requests
python -m app.eval.study_guide_eval            # the study guide's scorecard on 67 synthetic requests
NEURON_FLOW_ACCESS_KEY=<16+ characters> python -m app.serve   # API + web page on http://localhost:8000
```
With `NEURON_FLOW_LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY` set, the same commands use Claude.

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
| [Design philosophy](docs/design_philosophy.md) | The owner's principles, the first-response rule and study resources (mostly Thai) |
| [Architecture](docs/architecture.md) | Layers, Core constraints, how AI fits, decisions (ADRs), milestones and their status |
| [case_triage v1](docs/case_triage_pilot.md) | The deterministic keyword rules |
| [case_triage v2 shadow mode](docs/case_triage_v2_shadow.md) | The AI second opinion: flow, failure handling, configuration, scorecard |
| [Intake API, queue, Runner and web page](docs/intake_queue.md) | Round 2: how a case flows from outside, recovery rules, API reference, Render setup |
| [Sentry error reporting](docs/observability_sentry.md) | What gets reported, privacy rules, alerts |
| [Tracing to Honeycomb](docs/observability_tracing.md) | One trace per case: what a span carries and never carries, setup in Render, how it is checked |
| [Study guide](docs/study_guide.md) | `study_guide.v1`: the workflow and its answer, failure handling, the mock's limits; the topic catalog and verified library, the weekly link check |
| [Funding readiness pack](docs/funding/README.md) | Internal evidence register; not a submitted application |
| [Evidence notes](docs/evidence/2026-11-03-render-operations.md) | Dated measurements; the first one covers Render operations (graceful stops, deploy filter, cold start) |

## Scope and limits

- Runs on one machine. No service-level agreement. The online service is protected by one shared access
  key, not per-person accounts, and uses Python's standard-library HTTP server (fine for a pilot, not for
  public traffic).
- Agent child processes isolate failures; they are **not** a security sandbox.
- All test data is synthetic. Mock AI scores are inflated by design and are not evidence of AI accuracy.
- Masking personal data before AI calls is pattern-based; it lowers the risk but does not make real data safe.
- The real Claude API has not been called yet, so there are no accuracy, latency or cost claims for Claude.
- The study guide's mock AI is a keyword simulation: it cannot read a new metaphor. On the 67-request
  scorecard it finds the right topic for 2 of 48 in-scope requests, so its answers prove the workflow runs,
  not that it understands people. A live Claude run has not been made (D2).

## Origin

Extracted on 2026-10-31 (commit `09100f7`) from the original Neuron Flow document/finance application.
Purchase and invoice agents, CSV/OCR/PDF adapters, the old HTTP/CLI wrappers and the business fixtures
remain only in that earlier history. License: GPL-3.0-only.
