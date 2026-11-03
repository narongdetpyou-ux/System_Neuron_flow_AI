# Measurement and evidence protocol

This file specifies the measurement protocol. The table "Metrics and gates" lists
**prospective** targets, not completed results.

**Current baseline (2026-11-03):** 127 automated tests, green in CI. Last pinned run: `main` @
`0b03735` with 119 tests (https://github.com/narongdetpyou-ux/System_Neuron_flow_AI/actions/runs/41550257103). The first baseline (2026-11-01, `main` @ `59c6889`) had 53 tests.
Always link the exact CI run and commit before describing a result as verified.

## Checks already automated (synthetic data)

| Check | What the test does | Result in CI |
|---|---|---|
| Domain independence so far | Added v1 and the v2 AI shadow mode | 0 Core code files changed |
| AI provider outage | Simulated outage on every attempt | Case still reaches human review on the rules suggestion |
| Off-contract AI answer | Unknown category, broken JSON, cut-off answer | Retried once, then marked unavailable; never saved |
| Prompt injection | Injected instructions in English and Thai | Answer stays within fixed choices; review still required |
| Secret handling | Real-path run with a test key | Key absent from every stored file; redirects refused |
| Model or prompt change | Re-run an old job after changing the model | Job refuses to run (`Agent version changed`) |
| AI outcome change | Two scorecard reports compared with `candidate_gate` | Any per-case change is flagged |
| Scorecard | 61 labelled synthetic cases (EN + TH), mock AI | Pipeline completes 61/61. Mock scores are inflated by design and are **not** accuracy |

## Test populations

- **Synthetic smoke fixtures:** generated, non-personal support-case strings.
- **Reproducible failure fixtures:** timeout, controller termination, corrupted
  artifact, bad output validator, duplicate request, agent version mismatch.
- **User study, optional:** real volunteers only after consent, with disclosed
  task scope and redacted/approved data. Never use actual customer tickets
  without permission.

## Metrics and gates

| Metric | Operational definition | Proposed gate |
|---|---|---|
| Domain independence | Core source diffs required to add a second domain | 0 Core code files |
| Duplicate admission | Identical request key + payload issued concurrently | 1 logical admitted job |
| Idempotency conflict | Identical key with divergent payload | Deterministic conflict, 0 extra execution |
| Crash reconciliation | Controlled kill of Runner during an active step | Terminal state or documented bounded re-attempt; no permanently orphaned queue item |
| Review authorization | Unauthorized reviewer attempts decision | Every attempted unauthorized decision rejected |
| Review idempotency | Replay same authorized review decision/version | 1 durable decision and at most 1 linked phase-B job |
| Artifact integrity | Deliberately flip one byte after writing | Verification rejects changed bytes |
| Core contract rejection | Unknown agent, invalid DAG, >1MiB JSON | Error before any trusted agent executes |
| Runtime regression | All existing automated tests (127 as of 2026-11-03) | All pass |
| Live AI quality | Scorecard run against a real model, with labels reviewed by a person | Recorded honestly, failures included; no target set before the first live run |
| Documentation reproducibility | Fresh checkout on supported Python versions | Tests and synthetic demo run without hidden credentials |

These are test **targets**, not measured success rates. Benchmark sample
sizes, machine hardware, full outcomes, failure logs and CI links must be
recorded in a separate dated evidence report after actual execution.

## Evaluation conduct

- Freeze code SHA, test version and input set before runs.
- Log command, OS/Python versions, data scope, measured numerator/denominator,
  failures, retries, and unexpected exclusions.
- Distinguish simulated faults from unplanned incidents.
- Do not equate output-hash integrity with authorship authenticity.
- Do not equate a candidate-vs-reference consistency check with independent
  ground truth, nor a keyword-rule demo with AI model accuracy.
- Record counterexamples and unresolved failures; do not silently rerun away
  a negative result.
