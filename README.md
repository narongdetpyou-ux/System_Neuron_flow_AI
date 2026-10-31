# System Neuron Flow AI — Core Logic Extraction

This branch isolates **portable internal logic** from the original Neuron Flow document/finance application.
It is a foundation for a different system, **not** a release of the original application.

## Included
- `engine.py`: Dendrite → Synapse → Axon → Soma → AxonTerminal; supervised multiprocessing, workflow DAGs, retries, idempotent local delivery and restart recovery.
- `model.py`: strict JSON contracts, size limits, deterministic workflow validation.
- `storage.py`: SQLite persistence, events, workspace ownership.
- `supervision.py`: bounded isolated trusted Python operations and hard deadlines (not a hostile-code sandbox).
- `integrity.py`: hashes, manifests, atomic workspace backup/restore.
- `telemetry.py`: bounded phase telemetry.
- `case_memory.py`: six-dimensional process-memory retrieval with immutable reviewer-declared evidence.
- `evaluation.py`: stable cohort routing, paired outcome and efficiency regression gates.
- `tests/`: minimal domain-independent regression checks.

## Excluded
Purchase/invoice agents; CSV, OCR, PDF and external connector adapters; batch reporting and local HTTP/CLI application wrappers; distribution/release assets; historical verification snapshots; business documentation, policies and fixtures. These remain in the original `main` history, with no history rewrite.

## Embedding contract
Provide an explicit list of `AgentDefinition(name, entrypoint, validator, version)` to `Runtime(workspace, agents=[...])`.
Agents must be trusted importable Python callables; the runtime does **not** execute arbitrary untrusted Python safely. Use `runtime.submit(workflow)` or `runtime.ingest(workflow)` with `job_id`, `input`, and `steps`. Each step declares its registered `agent`, optional `depends_on`, `params`, `timeout_s`, `max_attempts`, `retry_delay_s`.

No domain agent, demo invoice, external integration or runnable document application is bundled. Reviewers remain caller-attested, not authenticated by the CaseMemory store.

## Verify
```bash
python -m unittest discover -s tests -v
```

Scope: single-machine Python runtime, no service-level agreement, network security boundary or production sandbox. This branch is deliberately a portable starting point, not a fully general batch-processing service.

## Current domain proof and funding preparation

- [Architecture Review v2](docs/System_Neuron_Flow_Architecture_Review_v2.md)
- [Deterministic case-triage pilot](docs/case_triage_pilot.md)
- [Internal funding-readiness evidence pack](docs/funding/README.md)
- [Optional Sentry error reporting](docs/observability_sentry.md)

Run the synthetic example: `python -m examples.case_triage_demo`.
The example is **not** an AI agent, public API, real-world user pilot or
operational human-review service. Funding documentation includes explicit
eligibility, evidence, ownership and cost-estimate gaps; it is not a
submitted application.
