# Funding readiness — internal evidence pack

**As of:** 2026-11-07 (`main` @ `cf06f4d`). **Use:** planning, technical due diligence, and an honest evidence
register. **Not:** a completed grant application, or an assertion that any grant program will accept this
project.

## What exists

- **Core runtime** (`neuron_flow/`). Since its extraction on 2026-10-31 it has changed twice: the planned telemetry fix (PR #21) and `decode()`'s error contract (ADR-025, PR #42).
- **Two domains on the same Core:** synthetic case triage (v1 rules, v2 AI second opinion in shadow mode) and the study guide (`study_guide.v1`, roadmap 3.1–3.4: at most 5 resources per answer from a verified library of 17 links, on the web page since PR #39). Neither needed a Core change.
- **477 automated tests**; Python 3.10 and 3.12 verification is recorded in the
  [E2 evidence note](../evidence/2026-11-11-e2-rules-v2.md)
  (3.11 was last checked on 2026-11-01, at 53 tests).
  - Last pinned green run on `main` (`cf06f4d`, 276 tests): https://github.com/narongdetpyou-ux/System_Neuron_flow_AI/actions/runs/42372717144
- **Support-case triage domain:**
  - v1: deterministic keyword rules.
  - v2: shadow mode, where an AI gives a second opinion. Rules stay official and a human always decides.
- **AI gateway** (`app/llm/`). It has an offline mock, a Claude provider and a Typhoon provider (SCB 10X's
  free research API). The Claude path is tested only against a local fake API; **Claude has not been
  called**. Typhoon was run on the synthetic sets on 2026-11-06 ([evidence note](../evidence/2026-11-06-first-live-typhoon.md)):
  a first measurement of that model on developer-labelled cases, not accuracy. A `local` provider runs an
  open-weight model on a server the project runs itself; Typhoon 2.5 4B on a GitHub runner had its first
  full run on the same sets on 2026-11-08 ([evidence note](../evidence/2026-11-08-first-local-model-full.md)),
  with no key and nothing sent to an AI company.
- **Scorecard** (`app/eval/`) with 61 synthetic, developer-labelled cases in English and Thai.
- **Sentry error monitoring.** CI smoke-test events have been received by the Sentry project.
- **Intake service (Milestone B)**: HTTP API, durable job queue, a single Runner with crash recovery and a
  Thai web page, online on Render's free plan since 2026-11-01 with synthetic data only. Queued cases can
  be cancelled, and request ids link the access log to each job. Operational observations are in
  [the Render evidence note](../evidence/2026-11-03-render-operations.md); there are no real users yet.
- **Documentation:**
  - [Design philosophy](../design_philosophy.md)
  - [Architecture](../architecture.md): layers, constraints, decisions and milestone status
  - Domain docs for [v1](../case_triage_pilot.md) and [v2](../case_triage_v2_shadow.md)
- **This directory:** an internal project concept and an *illustrative* budget, both clearly marked as such.

## Documents

1. [Internal project brief](INTERNAL_PROJECT_BRIEF.md): problem, hypothesis, scope, beneficiaries,
   deliverables, limitations.
2. [Illustrative budget and milestones](BUDGET_ILLUSTRATIVE.md): explicit cost assumptions and verifiable gates.
3. [Evidence, eligibility and blockers](EVIDENCE_AND_ELIGIBILITY.md): fact-based readiness checklist with
   funder-policy links.
4. [Measurement protocol](METRICS_PLAN.md): which checks are automated now, and which are still prospective.

## What a grant reviewer can honestly verify today

- The Core library exists, and two domain versions run on it without Core changes.
- The automated tests pass in CI.
- The AI integration handles outages, off-contract answers, prompt injection and secrets as documented.
  This was tested offline; the off-contract handling was also seen live, when Typhoon's first run answered
  in plain text instead of JSON and all 5 answers were refused rather than guessed at.
- A first live run of a free model (Typhoon) on the synthetic sets is recorded with run links, rates as
  fractions and every failure ([evidence note](../evidence/2026-11-06-first-live-typhoon.md)), and so is the
  first full run of an open-weight model the project runs itself
  ([evidence note](../evidence/2026-11-08-first-local-model-full.md)).
- The architecture decisions are written down.

These facts do **not** imply any of the following:
- product-market fit or open-source traction
- AI accuracy (the only real-model runs are two free models by SCB 10X, Typhoon through its API and Typhoon
  2.5 4B run on a GitHub runner, on developer-labelled synthetic cases; Claude has not been run)
- production security or independent benchmarking
- a usable HTTP service or a real human-review workflow
- award eligibility

## Non-negotiable before a public open-source application

- **The repository has been public since 2026-11-08, with its full history** (ROADMAP 7.4, D5). Being
  public does not show user adoption, and provenance and rights stay the owner's to confirm in any
  application.
  - Since 2026-11-03 (PR #29) the Sentry smoke workflow reads its DSN only from a repository secret, and
    *Actions → Secret scan* checks every commit of every branch with gitleaks. Its one reviewed finding is
    the old DSN, still in the history; before the switch the owner replaced it and reported it disabled.
    It was submit-only and rate-limited.
- **No outside evidence yet.** No third-party users, testimonials or security certifications have been
  evidenced. Never fill these fields with synthetic numbers.
- **Applicant facts are unverified.** This pack does not verify the applicant's identity, residence and
  fiscal status, grant-specific eligibility, payment rails, real availability, or exact cost quotations.
- **AI assistance must be disclosed.** Several grant makers limit the use of AI in proposals and/or
  implementation. This pack and much of the code were produced with AI assistance and must **not** be passed
  off as written independently by the applicant. Review each funder's policy first.

## Next evidence gates

1. ✅ Domain proof confirmed in CI, with link and SHA recorded above.
2. 🟡 Run the scorecard against a real model and record the run link, the model and the results, including
   failures. Done with Typhoon, a free model by SCB 10X, on 2026-11-06 ([evidence note](../evidence/2026-11-06-first-live-typhoon.md));
   the same run with real Claude (*Actions → Shadow eval with Claude*) waits for the owner's decision D2.
3. ✅ Build the durable admission, single Runner and recovery slice (Milestone B), and test controller
   crashes and idempotency (PR #11; tested in CI; online on Render since 2026-11-01).
4. Verify identity-bound review and artifacts (Milestone C), then get an independent review.
5. Publish an approved public code snapshot if the chosen fund requires it.
6. Collect genuine third-party feedback and scope-specific cost quotations.
