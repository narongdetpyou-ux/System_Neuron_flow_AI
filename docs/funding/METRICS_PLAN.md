# Measurement and evidence protocol

This file specifies **prospective** tests. It is not a report of completed
results. Current baseline: original five tests plus a new domain pilot suite;
link to the exact CI run and commit before describing a result as verified.

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
| Runtime regression | Existing original five core tests | All pass |
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
