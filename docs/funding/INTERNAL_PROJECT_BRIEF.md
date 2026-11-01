# Internal technical project brief — System Neuron Flow AI

**Status:** Internal working brief. Not a completed funder application.
**Date:** 2026-10-31; implementation section updated 2026-11-01 (`main` @ `59c6889`).
**Applicant:** Independent developer (name, legal status and country-specific
eligibility to be supplied and confirmed by the applicant).
**Code:** https://github.com/narongdetpyou-ux/System_Neuron_flow_AI
(private at time of preparation).
**License in repository:** GPL-3.0-only; code rights and provenance still
require review before public release.

## One-sentence objective

Develop and evaluate a small, inspectable, single-machine workflow execution
platform that safely coordinates *trusted* task agents, persists progress,
retries bounded failures, and produces verifiable completion receipts.

**Guiding principle (set by the owner):** plain language on the outside and deep,
verifiable work inside, with equitable learning support offered without being
asked. See [design philosophy](../design_philosophy.md).

## Problem statement (hypothesis, not yet independently validated)

Small teams that automate multi-step processes may struggle to understand
which task ran, which part failed, what can be retried safely and which output
corresponds to a specific execution. The proposed project tests whether a
minimal, evidence-oriented execution layer can reduce those operational
problems without requiring a distributed infrastructure stack.

## Why this project is distinct enough to investigate

The focus is not another general-purpose chatbot or a claim to beat established
orchestrators. The testable design thesis is an easily inspected **single-owner
runtime** combining strict JSON DAG contracts, persistent state, bounded
subprocess supervision, interrupted-run recovery, output validation and
receipt integrity. Differentiation versus existing systems has **not**
yet been benchmarked or validated with prospective users.

## Current implementation

- Core: existing `neuron_flow/` package, with DAG validation, trusted
  `AgentDefinition`, SQLite state/events, bounded child processes, retry
  and recovery, report receipts, integrity primitives, case-memory and
  candidate evaluation utilities.
- Domain demonstration: synthetic support-case triage in
  `app/domains/case_triage/`.
  - v1 uses deterministic keyword rules.
  - v2 adds an AI second opinion in shadow mode. The rules stay the official
    suggestion and every proposal waits for a human; nothing is approved
    automatically.
  - Both versions run on the unchanged Core.
- AI gateway in `app/llm/` (offline mock + Claude provider). It handles
  outages, off-contract answers, prompt injection and secrets as documented.
  This was tested offline only: **no live model has been called yet**.
- Measurement and monitoring:
  - A scorecard over 61 synthetic labelled cases in English and Thai runs in
    CI. Its mock scores test the pipeline, not accuracy.
  - Sentry error monitoring, with live smoke-test events received.
  - 53 automated tests.
- Architecture: [architecture](../architecture.md) covers the layers, decisions
  and milestone status, including the planned admission queue, single Runner,
  API and two-phase human review. **Those services are not implemented.**

## Intended beneficiaries (to validate, not asserted customers)

- Independent developers who need reproducible multi-step tasks.
- Small internal automation teams with a trusted-agent execution environment.
- Open-source maintainers seeking a compact educational reference
  for recoverable workflows.

## Scope of proposed funded work

1. Durable job admission plus idempotency, status projection and a single
   workspace-owning Runner.
2. Crash reconciliation between application queue and Core SQLite; explicit
   policy for retries with external side effects.
3. A versioned two-phase human review demonstration with authenticated identity
   in the application layer, durable decision record and linked phase-B job.
4. Bounded artifact access, checksums, backup exercise and documentation.
5. Reproducible test scenarios and a second independent domain to test the
   no-core-modification rule.

Out of scope: untrusted Python sandboxing, distributed worker claims,
multi-tenancy, arbitrary user code, unreviewed payment side effects,
production SLA, clinical/legal decision making, and model-accuracy claims.

## Candidate deliverables

- Executable Python repository with defined CLI/test commands and CI evidence.
- One-domain and two-domain demonstrations using the same Core unchanged.
- Architecture decision records, risk model and incident/recovery notes.
- Versioned API contracts and reproducible synthetic acceptance tests.
- Pilot feedback notes only if real external volunteers participate,
  with consent and clear distinction from synthetic fixtures.

## Impact and evaluation — measurement must come later

Primary technical outcomes will be measured by repeat submissions returning
one application request identity, verified recovery after process termination,
correct rejection of malformed input, receipt hash integrity, and domain
isolation. Pilot-usability outcomes require actual volunteers. No throughput,
accuracy, user counts, economic savings or external adoption numbers are
claimed in this brief.

## Ethical and operational constraints

Only registered, trusted code executes. Child-process termination is
**not** a hostile-code sandbox. The initial deployment is one machine and
one tenant. Core hashes do not prove reviewer authentication. Application-level
authorization must be developed and independently challenged before opening
any network-facing service.

## Funding rationale

Funding would buy focused engineering time, repeatable test infrastructure,
external security review and user-evidence collection. It is not sought to
claim that a production business or mature hosted platform already exists.

**Important:** Because some funders prohibit AI-authored submissions, this
AI-assisted internal brief must be checked against each program's terms and
must not be submitted where that would breach their rules.
