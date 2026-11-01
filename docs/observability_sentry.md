# Sentry error reporting

**Status:** on `main` since 2026-11-01 (PR #8; degraded-step warnings in PR #9). Optional, application layer
only. Core (`neuron_flow/`) does not import Sentry.
**Sentry project:** organization `neuron-flow`, project `neuron-flow-runtime` (platform: Python).

## Why an adapter instead of plain `sentry_sdk.init()`

Core catches agent failures inside child processes and stores them as step records
(`FAILED`, `BLOCKED`, `DELIVERY_FAILED`). They are never raised to the caller, so
Sentry's automatic exception capture would miss almost every real failure.
`app.observability.SentryReporter` reads the finished job snapshot and sends:

| Situation | Sentry event | Grouping (fingerprint) |
|---|---|---|
| Step `FAILED` | one `error` event per failed step | `neuron-flow / step-failed / <agent> / <error type>` |
| Step `BLOCKED` | no separate event; listed as `blocked_dependents` on the root failure | — |
| Job `DELIVERY_FAILED` | one `error` event | `neuron-flow / delivery-failed / <error type>` |
| Step `SUCCEEDED` but degraded: output `{"status": "unavailable", "reason": "<code>"}` (e.g. AI second opinion unavailable) | one `warning` event | `neuron-flow / step-degraded / <agent> / <reason>` |
| `Runtime.run` raises (e.g. agent version drift, unknown agent) | exception event, then re-raised | Sentry default |

Tags: `neuron_flow.event`, `neuron_flow.agent`, `neuron_flow.agent_version`,
`neuron_flow.error_type`, `neuron_flow.retries_exhausted`, and `neuron_flow.degraded_reason`
for degraded steps.
Context `neuron_flow`: `job_id`, `step_id`, `attempts`, `max_attempts`, `job_status`.

## Privacy defaults

- Never sent: job `input`, step `params`, step `output`, receipt paths, frame local
  variables, request/user data, breadcrumbs (`send_default_pii=False`).
- Error messages are **off by default** because an agent or validator may echo user
  text. Enable with `NEURON_FLOW_SENTRY_INCLUDE_MESSAGES=1` (truncated to 300 chars).
- AI agents follow the same rule. The AI gateway passes on only the provider's HTTP status
  and error type, never its message. Prompts, case text and model answers never go into
  exception messages or Sentry context.

## Alerts (configured in Sentry, not in code)

1. **"Neuron Flow: email me on new or returning errors"** emails the project owner when an
   issue is new, comes back after being resolved, or reappears after being ignored. It sends
   at most one email per issue every 30 minutes.
2. Sentry's default **"Send a notification for high priority issues"** is also active.
3. The synthetic smoke-test issue (`smoke.permanent`, NEURON-FLOW-RUNTIME-1) is set to
   **ignored forever**. The recurring CI check therefore keeps recording events without
   sending email. Real failures have different fingerprints, so they still alert.

## Setup

```bash
pip install -e ".[observability]"
export SENTRY_DSN="<DSN from Sentry → neuron-flow-runtime → Settings → Client Keys>"
export SENTRY_ENVIRONMENT=development        # optional
python -m examples.sentry_smoke_test         # sends one synthetic failure
```

**No local environment needed:** `.github/workflows/sentry-smoke.yml` runs the smoke
test on GitHub Actions whenever the observability code changes (or manually via
*Actions → Sentry smoke test → Run workflow*). That workflow contains the DSN on purpose:
a DSN can only submit events, not read them, and this key ("CI and development") is
rate-limited to 200 events/hour in Sentry. If it leaks or gets abused, revoke it in
Sentry → neuron-flow-runtime → Settings → Client Keys and set a `SENTRY_DSN` repository
secret instead (the secret automatically takes priority). Use a separate, non-committed
DSN for any production deployment. The unit tests use a stub SDK and need no network.

## Usage in application code

```python
from app.observability import init_sentry, run_job

init_sentry()                       # returns False (no-op) without DSN or SDK
with Runtime(workspace, agents=registry()) as runtime:
    runtime.submit(spec)
    snapshot = run_job(runtime, spec["job_id"])   # same return value as runtime.run
```

The Runner (`app/services/runner.py`, Milestone B) calls `run_job` for every job. When it starts
and finds a job that a stopped Runner left unfinished, it also calls `report_recovery`:

| Outcome | Level | Meaning |
|---|---|---|
| `resumed` | warning | The job continues; Core retries the interrupted step within its retry budget |
| `runner_attempts_exhausted` | error | The job stopped the Runner too many times and was failed |
| `configuration_changed` | error | The model, prompt or code changed while the job was interrupted, so it was failed instead of re-run under other settings |

Only the job id, the outcome code and the claim count are sent.

## Limits

Reporting is best effort: a Sentry outage or misconfiguration never changes a job
result. Child-process crashes are reported as the step error Core records
(`ChildProcessError`, `TimeoutError`), not as native crash dumps.
