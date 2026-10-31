# Deterministic support-case triage: domain proof v1

**Status:** Domain proof only. Not a production workflow, human review service,
AI Agent, background queue or public API.

Purpose: demonstrate that an unrelated domain package can submit a validated
two-step DAG to the existing portable Core Runtime without modifying Core files.

## Run

From the repository root with Python 3.10 or 3.12:

    python -m examples.case_triage_demo
    python -m unittest discover -s tests -v

The script creates a temporary workspace and feeds one **synthetic** case.
It uses no external APIs, credentials, real customer data, or generative AI.

## Trust and execution boundary

- The caller invokes `build_workflow(job_id, case)`, which validates a bounded
  JSON case. It does not accept user-provided import paths.
- `registry()` supplies two fixed `AgentDefinition` entries and independent
  output validators.
- Core handles DAG scheduling, bounded execution, persistence and report receipt.
- Classify chooses a suggested category and queue using **toy keyword rules**.
- Prepare emits `PENDING_HUMAN_REVIEW` as an **output field**, not a Core or
  application-level waiting state. No real human approval flow exists.
- Core step outputs remain JSON-bounded; larger artifacts are not supported here.

## Evidence boundaries

Passing the pilot establishes only this narrow deterministic integration.
It does not establish model accuracy, agent security isolation, enterprise
reliability, third-party adoption, privacy compliance, or automated human review.

A funding application may link to CI plus this example as implementation proof,
but must not describe the planned queue, review service or API as completed.
