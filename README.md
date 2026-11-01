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

Since round 2, cases can also come in from outside, through an HTTP API or a Thai web page:

1. A case is checked, then stored in a durable queue before the reply ("received"). Sending the same
   request twice never creates two jobs.
2. One Runner takes the cases in order and passes each one to the Core.
3. If the machine stops in the middle of a case, the Runner picks it up again after the restart, within the
   same retry budget, or fails it with a clear reason.
4. The page shows each case moving through the queue and explains the result in plain language.
   Details: [intake_queue.md](docs/intake_queue.md).

## What is inside

| Part | Where | Status |
|---|---|---|
| Core runtime: DAG workflows, bounded child processes, retries, restart recovery, verified receipts | `neuron_flow/` | Working; unchanged since extraction |
| Case triage v1: deterministic keyword rules | `app/domains/case_triage/agents.py`, `workflow.py` | Working |
| Case triage v2: shadow mode with AI second opinion | `app/domains/case_triage/shadow_*.py` | Working with the offline mock AI; Claude path tested against a fake API, **not yet run against the real Claude API** |
| AI gateway: versioned prompt, mock and Claude providers | `app/llm/` | Working (see above) |
| Error monitoring | `app/observability/` | Sentry errors, degraded-AI warnings and Runner recoveries |
| Scorecard: 61 synthetic labelled cases (EN + TH) | `app/eval/` | Runs in CI; mock scores test the pipeline, not AI accuracy |
| Intake API, durable job queue, single Runner with crash recovery, Thai web page | `app/api/`, `app/persistence/`, `app/services/`, `app/web/`, `app/serve.py` | Working (round 2), tested offline and as a container in CI; **not deployed yet** (host: Render) |
| Human-review decisions, n8n intake, reviewer notifications | — | **Not built yet** (Milestone C in [architecture](docs/architecture.md)) |

## Try it

**Online, on Render:** `render.yaml` describes the whole service, so setup is New → Blueprint in the Render
Dashboard; the step-by-step guide is in [intake_queue.md](docs/intake_queue.md) (in Thai). Render generates
the access key (`NEURON_FLOW_ACCESS_KEY`) and deploys `main` only when the GitHub checks pass. The free plan
forgets its cases when it sleeps; a paid plan with a disk keeps them.

**On GitHub, no local setup needed:**
- *Actions → Core logic tests* runs every test on Python 3.10 and 3.12, plus both demos and the scorecard.
  The scorecard table appears on the run page.
- *Actions → Service container* checks `render.yaml`, builds the same container as Render, submits cases
  over HTTP, restarts it and checks that nothing was lost.
- *Actions → Sentry smoke test* checks that error reporting reaches Sentry.
- *Actions → Shadow eval with Claude (manual)* runs the scorecard against real Claude. It needs the
  repository secret `ANTHROPIC_API_KEY`.

**Locally (Python 3.10+):**
```bash
python -m unittest discover -s tests -v        # 98 tests
python -m examples.case_triage_demo            # v1 rules, one synthetic case
python -m examples.case_triage_shadow_demo     # v2 shadow mode, three synthetic cases (offline mock AI)
python -m app.eval.triage_shadow_eval          # scorecard on 61 synthetic cases
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
| [Funding readiness pack](docs/funding/README.md) | Internal evidence register; not a submitted application |

## Scope and limits

- Runs on one machine. No service-level agreement. The online service is protected by one shared access
  key, not per-person accounts, and uses Python's standard-library HTTP server (fine for a pilot, not for
  public traffic).
- Agent child processes isolate failures; they are **not** a security sandbox.
- All test data is synthetic. Mock AI scores are inflated by design and are not evidence of AI accuracy.
- The real Claude API has not been called yet, so there are no accuracy, latency or cost claims for Claude.

## Origin

Extracted on 2026-10-31 (commit `09100f7`) from the original Neuron Flow document/finance application.
Purchase and invoice agents, CSV/OCR/PDF adapters, the old HTTP/CLI wrappers and the business fixtures
remain only in that earlier history. License: GPL-3.0-only.
