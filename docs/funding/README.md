# Funding readiness — internal evidence pack

**As-of:** 2026-10-31. **Use:** planning, technical due diligence, and an
honest evidence register. **Not:** a completed grant application or an
assertion that the grant program will accept this project.

## What exists

- The source-controlled portable Core Runtime and five original focused
  core regression tests; see root README and `tests/test_core.py`.
- A reviewed architecture proposal at
  [Architecture Review v2](../System_Neuron_Flow_Architecture_Review_v2.md).
- Deterministic, synthetic support-case triage domain proof and regression
  tests in `app/domains/case_triage/`, `tests/test_case_triage.py`
  and `docs/case_triage_pilot.md`. **Check current CI** before claiming it passed.
- A clearly marked internal technical project concept and an *illustrative*
  grant budget in this directory.

## Documents

1. [Internal project brief](INTERNAL_PROJECT_BRIEF.md) — problem, hypothesis,
   scope, beneficiaries, deliverables, limitations.
2. [Illustrative budget and milestones](BUDGET_ILLUSTRATIVE.md) — explicit
   cost assumptions and verifiable gates.
3. [Evidence, eligibility and blockers](EVIDENCE_AND_ELIGIBILITY.md) —
   fact-based readiness checklist with funder-policy links.
4. [Measurement protocol](METRICS_PLAN.md) — prospective checks, not
   fabricated metrics.

## What a grant reviewer can honestly verify today

The Core library exists; a domain integration example has been added;
unit/integration test code exists; architecture decisions have been documented.
These facts do **not** imply product-market fit, open-source traction,
production security, independent benchmarking, a usable HTTP service, a
real-world human approval workflow, or guaranteed award eligibility.

## Non-negotiable before a public open-source application

- The repository is presently **private**. A license in a private repository
  does not create public availability or user adoption. The owner must decide
  what to publish and inspect all secrets, provenance and rights before doing so.
- No third-party users, testimonials or security certifications have been
  evidenced. Never replace these fields with synthetic numbers.
- Applicant identity, residence and fiscal status, grant-specific eligibility,
  payment rails, real availability, and exact project-cost quotations are
  not verified in this pack.
- Several grant makers limit use of AI in proposals and/or implementation.
  This pack was produced with AI assistance and must **not** be passed off as
  independently written by the applicant. Review each funder's policy first.

## Next evidence gates

1. Confirm the domain-proof GitHub Actions run and save its link plus SHA.
2. Build the proposed durable admission, sole Runner and recovery application
   slice; test controller crash and idempotency.
3. Verify identity-bound review and artifacts; perform an independent review.
4. Publish an approved public code snapshot if the chosen fund requires it.
5. Collect genuine third-party feedback and scope-specific cost quotations.
