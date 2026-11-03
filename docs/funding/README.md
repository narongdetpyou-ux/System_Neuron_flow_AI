# Funding readiness — internal evidence pack

**As of:** 2026-11-03 (`main` @ `0b03735`). **Use:** planning, technical due diligence, and an honest evidence
register. **Not:** a completed grant application, or an assertion that any grant program will accept this
project.

## What exists

- **Core runtime** (`neuron_flow/`). Since its extraction on 2026-10-31 it has changed once, for the planned telemetry fix (PR #21).
- **169 automated tests** passing on Python 3.10 and 3.12 in CI, and on 3.13 in a development session
  (3.11 was last checked on 2026-11-01, at 53 tests).
  - Last pinned green run on `main` (`0b03735`, 119 tests): https://github.com/narongdetpyou-ux/System_Neuron_flow_AI/actions/runs/41550257103
- **Support-case triage domain:**
  - v1: deterministic keyword rules.
  - v2: shadow mode, where an AI gives a second opinion. Rules stay official and a human always decides.
- **AI gateway** (`app/llm/`). It has an offline mock and a Claude provider. The Claude path is tested only
  against a local fake API, and **no live model has been called yet**.
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
  This was tested offline only.
- The architecture decisions are written down.

These facts do **not** imply any of the following:
- product-market fit or open-source traction
- AI accuracy (no live model has been run)
- production security or independent benchmarking
- a usable HTTP service or a real human-review workflow
- award eligibility

## Non-negotiable before a public open-source application

- **The repository is private.** A license in a private repository does not create public availability or
  user adoption. Before publishing anything, the owner must decide what to publish and check secrets,
  provenance and rights.
  - Since 2026-11-03 (PR #29) the Sentry smoke workflow reads its DSN only from a repository secret, and
    *Actions → Secret scan* checks every commit of every branch with gitleaks. Its one reviewed finding is
    the old DSN, still in the history: revoke that key in Sentry before going public. It is submit-only and
    rate-limited, but it should not be public.
- **No outside evidence yet.** No third-party users, testimonials or security certifications have been
  evidenced. Never fill these fields with synthetic numbers.
- **Applicant facts are unverified.** This pack does not verify the applicant's identity, residence and
  fiscal status, grant-specific eligibility, payment rails, real availability, or exact cost quotations.
- **AI assistance must be disclosed.** Several grant makers limit the use of AI in proposals and/or
  implementation. This pack and much of the code were produced with AI assistance and must **not** be passed
  off as written independently by the applicant. Review each funder's policy first.

## Next evidence gates

1. ✅ Domain proof confirmed in CI, with link and SHA recorded above.
2. Run the scorecard once against the real Claude API (*Actions → Shadow eval with Claude*). Record the run
   link, the model and the results, including failures.
3. ✅ Build the durable admission, single Runner and recovery slice (Milestone B), and test controller
   crashes and idempotency (PR #11; tested in CI; online on Render since 2026-11-01).
4. Verify identity-bound review and artifacts (Milestone C), then get an independent review.
5. Publish an approved public code snapshot if the chosen fund requires it.
6. Collect genuine third-party feedback and scope-specific cost quotations.
