# Sentry error reporting

**Status:** on `main` since 2026-11-01 (PR #8; degraded-step warnings in PR #9). Optional, application layer
only. Core (`neuron_flow/`) does not import Sentry.
**Sentry project:** organization `neuron-flow`, project `neuron-flow-runtime` (platform: Python).
Sentry reports what went wrong. How long each step took, and the AI's tokens, are in the traces sent to
Honeycomb: [observability_tracing.md](observability_tracing.md).

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
| The Runner starts no jobs because the AI settings cannot work (`blocked_config`, e.g. Typhoon chosen without a key; roadmap 1.7) | one `error` event per Runner start | `neuron-flow / runner-blocked / <error type>` |

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
*Actions → Sentry smoke test → Run workflow*). It reads the DSN only from the repository
secret `SENTRY_DSN` (Settings → Secrets and variables → Actions; roadmap 7.4). Without the
secret, a push skips the test with a notice, and a manual run fails and says how to add it.
Use a separate DSN for any production deployment (Render's Environment tab). The unit tests
use a stub SDK and need no network.

**The old DSN is still in the git history.** Until 2026-11-03 the workflow carried the
"CI and development" key inline. A DSN can only submit events, not read them, and that key
is rate-limited to 200 events/hour, but it stays readable in the history, which is public
since 2026-11-08. Before the switch the owner created a new key, put it in the `SENTRY_DSN`
secret and in Render, and reported the old key disabled (Sentry → neuron-flow-runtime →
Settings → Client Keys). *Actions → Secret scan* lists it as the one reviewed finding
(`.github/.gitleaksignore`).

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

When the AI settings cannot work, the Runner stays up, starts no jobs and reports `blocked_config`
(queued cases wait; `/readyz` answers 503 `blocked_config` while `/healthz` stays 200, roadmap 1.7). It
then calls `report_runner_blocked` once, so the owner hears about it without watching the page:
message `Neuron Flow Runner blocked: the AI settings cannot work (<error type>)`, tags
`neuron_flow.event=runner_blocked` and `neuron_flow.error_type`, context `state` and `error_type`. Only the
error's class name is sent (anything else becomes `Unknown`), never its message, a key or a setting's value;
the page and `/v1/status` show the reason. A restart of the Runner reports again, once. The alert in
"Alerts" above already emails on a new issue, so no rule is needed for it.

## Limits

Reporting is best effort: a Sentry outage or misconfiguration never changes a job
result. Child-process crashes are reported as the step error Core records
(`ChildProcessError`, `TimeoutError`), not as native crash dumps.
