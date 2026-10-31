"""Optional Sentry error reporting for Neuron Flow jobs.

Design rules (see docs/observability_sentry.md):

* Lives in the application layer. ``neuron_flow`` (Core) never imports Sentry,
  so Core stays dependency-free and its behaviour is unchanged.
* Core turns agent failures into *step records*, not raised exceptions, so
  Sentry's automatic capture would never see them. ``SentryReporter`` reads the
  job snapshot after ``Runtime.run`` and sends one event per FAILED step and
  one per DELIVERY_FAILED job. BLOCKED steps are consequences, so they are
  attached as context to the root failure instead of creating noise.
* Degraded steps: a SUCCEEDED step whose output is ``{"status": "unavailable",
  "reason": "<code>"}`` (e.g. the AI second opinion was unavailable) sends one
  ``warning`` event, grouped by agent and reason. Only the fixed reason code
  and error class name are read from the output.
* Privacy first: job ``input``, step ``params``, step ``output`` and receipt
  paths are never sent. Error *messages* are omitted by default because an
  agent or validator may echo user text; opt in with
  ``include_error_messages=True`` or ``NEURON_FLOW_SENTRY_INCLUDE_MESSAGES=1``.
* If ``sentry-sdk`` is not installed or no DSN is configured, every call is a
  no-op. Reporting failures never change the job result.
"""

import os
import re

_MESSAGE_LIMIT = 300
_CODE = re.compile(r"^[a-z0-9_]{1,60}$")
_CODE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,99}$")
_SCRUBBED_KEYS = ("request", "user", "breadcrumbs")


def _sdk():
    try:
        import sentry_sdk
    except ImportError:
        return None
    return sentry_sdk


def _truthy(value):
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _before_send(event, _hint):
    """Drop fields that could carry user data and strip frame locals."""
    for key in _SCRUBBED_KEYS:
        event.pop(key, None)
    for exception in (event.get("exception") or {}).get("values") or []:
        for frame in (exception.get("stacktrace") or {}).get("frames") or []:
            frame.pop("vars", None)
    return event


def init_sentry(dsn=None, *, environment=None, release=None, traces_sample_rate=None):
    """Initialise the Sentry SDK. Returns True only when reporting is active.

    Values fall back to SENTRY_DSN, SENTRY_ENVIRONMENT, SENTRY_RELEASE and
    SENTRY_TRACES_SAMPLE_RATE. Never hard-code a DSN in source control.
    """
    sdk = _sdk()
    dsn = dsn or os.environ.get("SENTRY_DSN")
    if sdk is None or not dsn:
        return False
    if traces_sample_rate is None:
        traces_sample_rate = float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0"))
    from neuron_flow import __version__
    sdk.init(
        dsn=dsn,
        environment=environment or os.environ.get("SENTRY_ENVIRONMENT", "development"),
        release=release or os.environ.get("SENTRY_RELEASE", f"neuron-flow@{__version__}"),
        send_default_pii=False,
        include_local_variables=False,
        max_breadcrumbs=0,
        traces_sample_rate=traces_sample_rate,
        before_send=_before_send,
    )
    return True


class SentryReporter:
    """Translate a finished job snapshot into privacy-safe Sentry events."""

    def __init__(self, *, include_error_messages=None, sdk=None):
        if include_error_messages is None:
            include_error_messages = _truthy(os.environ.get("NEURON_FLOW_SENTRY_INCLUDE_MESSAGES", ""))
        self.include_error_messages = include_error_messages
        self.sdk = sdk if sdk is not None else _sdk()

    @property
    def active(self):
        if self.sdk is None:
            return False
        client = getattr(self.sdk, "get_client", None)
        return bool(client().is_active()) if client is not None else True

    def _error_fields(self, error):
        error = error if isinstance(error, dict) else {}
        fields = {"error_type": str(error.get("type", "Unknown"))[:100]}
        if self.include_error_messages and error.get("message"):
            fields["error_message"] = str(error["message"])[:_MESSAGE_LIMIT]
        return fields

    def report_job(self, snapshot, spec):
        """Send events for a snapshot from ``Runtime.run``/``Runtime.status``.

        Returns the list of event ids sent (empty when inactive or clean).
        """
        if not self.active:
            return []
        steps_spec = {step["id"]: step for step in spec.get("steps", [])}
        versions = spec.get("agent_versions", {})
        states = snapshot.get("steps", {})
        blocked = sorted(step_id for step_id, state in states.items() if state.get("status") == "BLOCKED")
        sent = []
        for step_id, state in states.items():
            if state.get("status") != "FAILED":
                continue
            definition = steps_spec.get(step_id, {})
            agent = definition.get("agent", "unknown")
            fields = self._error_fields(state.get("error"))
            exhausted = state.get("attempts", 0) >= definition.get("max_attempts", 1)
            sent.append(self._send(
                f"Neuron Flow step failed: {agent} ({fields['error_type']})",
                fingerprint=["neuron-flow", "step-failed", agent, fields["error_type"]],
                tags={"neuron_flow.event": "step_failed", "neuron_flow.agent": agent,
                      "neuron_flow.error_type": fields["error_type"],
                      "neuron_flow.agent_version": str(versions.get(agent, {}).get("version", "?")),
                      "neuron_flow.retries_exhausted": str(exhausted).lower()},
                context={"job_id": snapshot.get("job_id"), "job_status": snapshot.get("status"),
                         "step_id": step_id, "attempts": state.get("attempts"),
                         "max_attempts": definition.get("max_attempts"),
                         "blocked_dependents": blocked, **fields}))
        for step_id, state in states.items():
            output = state.get("output")
            if state.get("status") != "SUCCEEDED" or not isinstance(output, dict) \
                    or output.get("status") != "unavailable":
                continue
            # Degraded but finished: e.g. the AI second opinion was unavailable and the
            # case went to review on the rules suggestion alone. Warn, don't page.
            agent = steps_spec.get(step_id, {}).get("agent", "unknown")
            reason = output.get("reason")
            reason = reason if isinstance(reason, str) and _CODE.fullmatch(reason) else "unspecified"
            error_type = output.get("error_type")
            error_type = error_type if isinstance(error_type, str) and _CODE_NAME.fullmatch(error_type) else "Unknown"
            sent.append(self._send(
                f"Neuron Flow step degraded: {agent} ({reason})", level="warning",
                fingerprint=["neuron-flow", "step-degraded", agent, reason],
                tags={"neuron_flow.event": "step_degraded", "neuron_flow.agent": agent,
                      "neuron_flow.degraded_reason": reason, "neuron_flow.error_type": error_type,
                      "neuron_flow.agent_version": str(versions.get(agent, {}).get("version", "?"))},
                context={"job_id": snapshot.get("job_id"), "job_status": snapshot.get("status"),
                         "step_id": step_id, "attempts": state.get("attempts"), "reason": reason,
                         "error_type": error_type}))
        if snapshot.get("status") == "DELIVERY_FAILED":
            details = snapshot.get("delivery_error_details") or {}
            fields = self._error_fields({"type": details.get("type", "DeliveryError"),
                                         "message": snapshot.get("delivery_error")})
            sent.append(self._send(
                f"Neuron Flow report delivery failed ({fields['error_type']})",
                fingerprint=["neuron-flow", "delivery-failed", fields["error_type"]],
                tags={"neuron_flow.event": "delivery_failed", "neuron_flow.error_type": fields["error_type"]},
                context={"job_id": snapshot.get("job_id"), **fields}))
        return [event_id for event_id in sent if event_id]

    def capture_exception(self, exc, *, job_id=None):
        """Report an exception raised by Runtime itself (e.g. agent version drift)."""
        if not self.active:
            return None
        with self.sdk.new_scope() as scope:
            scope.set_tag("neuron_flow.event", "runtime_exception")
            scope.set_context("neuron_flow", {"job_id": job_id, "exception_type": type(exc).__name__})
            return self.sdk.capture_exception(exc)

    def _send(self, message, *, fingerprint, tags, context, level="error"):
        try:
            with self.sdk.new_scope() as scope:
                scope.fingerprint = fingerprint
                for key, value in tags.items():
                    scope.set_tag(key, value)
                scope.set_context("neuron_flow", context)
                return self.sdk.capture_message(message, level=level)
        except Exception:
            # Observability must never change a job outcome.
            return None


def run_job(runtime, job_id, reporter=None):
    """Run a submitted job and report failures. Returns the normal snapshot."""
    reporter = reporter or SentryReporter()
    try:
        snapshot = runtime.run(job_id)
    except Exception as exc:
        reporter.capture_exception(exc, job_id=job_id)
        raise
    reporter.report_job(snapshot, runtime.store.job(job_id)["spec"])
    return snapshot
