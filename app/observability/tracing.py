"""Optional tracing to Honeycomb (roadmap 5.1), with the Python standard library only.

What it sends: OpenTelemetry spans, encoded as OTLP/HTTP JSON and posted to
``<HONEYCOMB_API_ENDPOINT>/v1/traces``. Any OTLP/HTTP receiver accepts the same requests, for example the
OpenTelemetry Collector that CI uses (.github/workflows/tracing-check.yml). ADR-017 explains why this is
a small exporter of our own instead of the OpenTelemetry SDK.

Settings (environment):
* ``HONEYCOMB_API_KEY``: an Ingest key. Tracing is on when it is set. It is read again for every export
  (ADR-013), sent only in the ``x-honeycomb-team`` header, and never stored, logged or shown;
* ``HONEYCOMB_API_ENDPOINT``: default ``https://api.honeycomb.io`` (US); the EU instance is
  ``https://api.eu1.honeycomb.io``. Plain http is accepted only for a receiver on this machine;
* ``OTEL_SERVICE_NAME``: default ``neuron-flow``. In Honeycomb it is the dataset name;
* ``NEURON_FLOW_TRACING=off``: turns tracing off without removing the key;
* ``NEURON_FLOW_ENVIRONMENT``: the ``deployment.environment.name`` of every span. Default ``render`` on
  Render, ``ci`` on GitHub Actions, otherwise ``local``.

Rules:
* off unless configured. A setting it cannot use turns tracing off with a problem code (shown in
  ``/v1/status``); it never stops the service;
* a span carries only the attributes listed in ``SPAN_ATTRIBUTES`` (ids, codes, counts, durations and
  versions), and every text value must be printable ASCII. Case text, prompts, AI answers and keys have no
  attribute to go into, so they cannot be exported; ``tests/test_tracing.py`` scans what is sent;
* exporting never blocks or changes the work: spans wait in a bounded queue for a background thread, and
  are dropped (and counted) when the queue is full or the receiver cannot take them;
* redirects are refused, so the key is never sent to another host.
"""

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import http.client
import json
import logging
import math
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import uuid

from neuron_flow import __version__

KEY_ENV = "HONEYCOMB_API_KEY"
ENDPOINT_ENV = "HONEYCOMB_API_ENDPOINT"
SERVICE_NAME_ENV = "OTEL_SERVICE_NAME"
SWITCH_ENV = "NEURON_FLOW_TRACING"
ENVIRONMENT_ENV = "NEURON_FLOW_ENVIRONMENT"
DEFAULT_ENDPOINT = "https://api.honeycomb.io"
DEFAULT_SERVICE_NAME = "neuron-flow"
TRACES_PATH = "/v1/traces"
SCOPE_NAME = "neuron_flow.app"

# OTLP enum values (opentelemetry-proto trace.proto); OTLP/JSON sends enums as integers.
KIND_INTERNAL, KIND_SERVER, KIND_CLIENT = 1, 2, 3
STATUS_UNSET, STATUS_ERROR = 0, 2

# The only attributes a span may carry, with their types. Names follow the OpenTelemetry semantic
# conventions (HTTP and GenAI) where one exists; the rest are this application's own.
SPAN_ATTRIBUTES = {
    "http.request.method": str, "http.route": str, "http.response.status_code": int, "error.type": str,
    "gen_ai.operation.name": str, "gen_ai.provider.name": str, "gen_ai.request.model": str,
    "gen_ai.response.model": str, "gen_ai.request.max_tokens": int,
    "gen_ai.usage.input_tokens": int, "gen_ai.usage.output_tokens": int,
    "neuron_flow.request_id": str,
    "neuron_flow.job.id": str, "neuron_flow.workflow_type": str, "neuron_flow.job.status": str,
    "neuron_flow.job.claims": int, "neuron_flow.core.status": str, "neuron_flow.failure.reason": str,
    "neuron_flow.queue.wait_ms": float, "neuron_flow.job.run_ms": float,
    "neuron_flow.step.id": str, "neuron_flow.step.agent": str, "neuron_flow.step.attempt": int,
    "neuron_flow.step.max_attempts": int, "neuron_flow.step.outcome": str, "neuron_flow.agent.version": str,
    "neuron_flow.ai.status": str, "neuron_flow.ai.reason": str, "neuron_flow.ai.usage_estimated": bool,
    "neuron_flow.ai.prompt_id": str, "neuron_flow.ai.prompt_sha256": str, "neuron_flow.ai.redaction": str,
    "neuron_flow.ai.masked_items": int, "neuron_flow.ai.latency_ms": float, "neuron_flow.ai.placement": str,
}
RESOURCE_ATTRIBUTES = {
    "service.name": str, "service.version": str, "service.instance.id": str, "deployment.environment.name": str,
    "neuron_flow.process": str, "telemetry.sdk.name": str, "telemetry.sdk.language": str,
    "telemetry.sdk.version": str,
}
HTTP_METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
TEXT_LIMIT = 256

_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_PRINTABLE = re.compile(r"^[\x20-\x7e]+$")
_HEX_ID = {32: re.compile(r"^[0-9a-f]{32}$"), 16: re.compile(r"^[0-9a-f]{16}$")}
_TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$")
_COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
_OFF, _ON = {"off", "0", "false", "no"}, {"", "on", "1", "true", "yes"}
log = logging.getLogger("neuron_flow.tracing")


# -- ids and the W3C trace context ------------------------------------------------------------------

def _random_hex(size):
    while True:
        value = secrets.token_hex(size)
        if value.strip("0"):  # an all-zero id is invalid
            return value


def new_trace_id():
    return _random_hex(16)


def new_span_id():
    return _random_hex(8)


def format_traceparent(trace_id, span_id):
    return f"00-{trace_id}-{span_id}-01"


def parse_traceparent(value):
    """``(trace_id, span_id)`` from a W3C ``traceparent`` value, or ``None`` when it is not one."""
    match = _TRACEPARENT.fullmatch(value) if isinstance(value, str) else None
    if match is None or not match.group(1).strip("0") or not match.group(2).strip("0"):
        return None
    return match.group(1), match.group(2)


def to_ns(seconds):
    """Unix time in seconds (a float, as the queue and Core store it) to integer nanoseconds."""
    return int(round(seconds * 1_000_000_000))


# -- spans ------------------------------------------------------------------------------------------

def _checked(attributes, allowed):
    clean = {}
    for key, value in attributes.items():
        if value is None:
            continue
        expected = allowed.get(key)
        if expected is None:
            raise ValueError(f"span attribute not allowed: {key}")
        if expected is float and type(value) is int:
            value = float(value)
        if type(value) is not expected:
            raise ValueError(f"span attribute {key} must be {expected.__name__}")
        if expected is str:
            if not value or not _PRINTABLE.fullmatch(value):
                raise ValueError(f"span attribute {key} must be printable ASCII")
            value = value[:TEXT_LIMIT]
        elif expected is int and not -(2 ** 63) <= value < 2 ** 63:
            raise ValueError(f"span attribute {key} is out of range")
        elif expected is float and not math.isfinite(value):
            raise ValueError(f"span attribute {key} must be finite")
        clean[key] = value
    return clean


@dataclass(frozen=True)
class Span:
    name: str
    trace_id: str
    span_id: str
    parent_id: object  # a span id, or None for a root span
    kind: int
    start_ns: int
    end_ns: int
    attributes: dict
    status: int = STATUS_UNSET

    def __post_init__(self):
        if not isinstance(self.name, str) or not 1 <= len(self.name) <= 120 or not _PRINTABLE.fullmatch(self.name):
            raise ValueError("span name must be 1-120 printable ASCII characters")
        for value, size in ((self.trace_id, 32), (self.span_id, 16)):
            if not isinstance(value, str) or not _HEX_ID[size].fullmatch(value):
                raise ValueError("span ids must be lower-case hex")
        parent = self.parent_id
        if parent is not None and not (isinstance(parent, str) and _HEX_ID[16].fullmatch(parent)):
            raise ValueError("parent span id must be lower-case hex")
        if self.kind not in (KIND_INTERNAL, KIND_SERVER, KIND_CLIENT):
            raise ValueError("unknown span kind")
        if self.status not in (STATUS_UNSET, STATUS_ERROR):
            raise ValueError("unknown span status")
        if type(self.start_ns) is not int or type(self.end_ns) is not int or not 0 < self.start_ns <= self.end_ns:
            raise ValueError("span times must be integer nanoseconds, start <= end")
        object.__setattr__(self, "attributes", _checked(self.attributes, SPAN_ATTRIBUTES))

    def otlp(self):
        """This span in OTLP/JSON: hex ids, 64-bit integers as strings, enums as integers."""
        span = {"traceId": self.trace_id, "spanId": self.span_id}
        if self.parent_id:
            span["parentSpanId"] = self.parent_id
        span.update(name=self.name, kind=self.kind, startTimeUnixNano=str(self.start_ns),
                    endTimeUnixNano=str(self.end_ns), attributes=_key_values(self.attributes))
        if self.status != STATUS_UNSET:
            span["status"] = {"code": self.status}
        return span


def _any_value(value):
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    return {"stringValue": value}


def _key_values(attributes):
    return [{"key": key, "value": _any_value(value)} for key, value in sorted(attributes.items())]


def encode_request(resource, spans):
    """One ``ExportTraceServiceRequest`` in OTLP/JSON, as ASCII bytes."""
    body = {"resourceSpans": [{
        "resource": {"attributes": _key_values(_checked(resource, RESOURCE_ATTRIBUTES))},
        "scopeSpans": [{"scope": {"name": SCOPE_NAME, "version": __version__},
                        "spans": [span.otlp() for span in spans]}],
    }]}
    return json.dumps(body, separators=(",", ":"), allow_nan=False).encode("ascii")


@dataclass(frozen=True)
class RequestTrace:
    """The ids of one HTTP request's span, made before the request is handled so that a job it admits can
    name it as its parent."""
    trace_id: str
    span_id: str
    start_ns: int

    @property
    def traceparent(self):
        return format_traceparent(self.trace_id, self.span_id)


def http_span(trace, *, method, route, status, request_id, end_ns):
    """The server span of one API request. ``route`` is a template such as ``/v1/jobs/{job_id}`` (never the
    real path), or ``None`` for a path the API does not know; ``status`` is ``None`` when the client left."""
    method = method if method in HTTP_METHODS else "_OTHER"
    attributes = {"http.request.method": method, "http.route": route, "http.response.status_code": status,
                  "neuron_flow.request_id": request_id or None}
    failed = status is None or status >= 500
    if failed:
        attributes["error.type"] = str(status) if status is not None else "connection_closed"
    return Span(f"{method} {route}" if route else method, trace.trace_id, trace.span_id, None, KIND_SERVER,
                trace.start_ns, max(end_ns, trace.start_ns), attributes, STATUS_ERROR if failed else STATUS_UNSET)


# -- the exporter -----------------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib would send x-honeycomb-team to a redirect target; refuse every redirect instead."""

    def redirect_request(self, *_args, **_kwargs):
        return None


def _iso(timestamp):
    if timestamp is None:
        return None
    moment = datetime.fromtimestamp(timestamp, timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def _rejected_spans(raw):
    """How many spans the receiver rejected, from an OTLP ``partialSuccess`` reply (0 when it says none)."""
    try:
        reply = json.loads(raw.decode("utf-8")) if raw.strip() else {}
        rejected = int((reply.get("partialSuccess") or {}).get("rejectedSpans") or 0)
    except (ValueError, TypeError, AttributeError):
        return 0
    return max(0, rejected)


class Exporter:
    """Send spans in batches from one background thread. ``submit`` never blocks and never raises."""

    def __init__(self, url, resource, *, environ=None, opener=None, interval_s=2.0, timeout_s=10.0,
                 max_queue=2048, max_batch=256, retry_delays_s=(1.0, 3.0)):
        self.url = url
        self.host = urlsplit(url).hostname
        self.resource = _checked(resource, RESOURCE_ATTRIBUTES)
        self.interval_s, self.timeout_s = interval_s, timeout_s
        self.max_queue, self.max_batch, self.retry_delays_s = max_queue, max_batch, tuple(retry_delays_s)
        self._environ = os.environ if environ is None else environ
        self._open = (opener or urllib.request.build_opener(_NoRedirect)).open  # default proxy and TLS handling
        self._cond = threading.Condition()
        self._queue = deque()
        self._thread = None
        self._busy = False
        self._flush = False
        self._closed = False
        self._deadline = None
        self._stopping = threading.Event()
        self._stats = {"exported_spans": 0, "dropped_spans": 0, "failed_exports": 0,
                       "last_ok_at": None, "last_error": None, "last_error_at": None}
        self._logged = None

    # -- the caller's side ----------------------------------------------------------------------

    def submit(self, spans):
        """Queue all of ``spans`` (one job's trace stays whole), or drop all of them when there is no room."""
        spans = list(spans)
        if not spans:
            return
        with self._cond:
            if self._closed or len(self._queue) + len(spans) > self.max_queue:
                self._stats["dropped_spans"] += len(spans)
                return
            self._queue.extend(spans)
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="tracing-export", daemon=True)
                self._thread.start()
            if len(self._queue) >= self.max_batch:
                self._cond.notify_all()

    def flush(self, timeout_s=5.0):
        """Send what is queued now. Returns True when nothing is left to send."""
        deadline = time.monotonic() + timeout_s
        with self._cond:
            while (self._queue or self._busy) and self._thread is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._flush = True
                self._cond.notify_all()
                self._cond.wait(min(remaining, 0.05))
            return not self._queue and not self._busy

    def shutdown(self, timeout_s=2.0):
        """Stop taking spans, try once more to send what is queued, and give up after ``timeout_s``."""
        with self._cond:
            self._closed = True
            self._deadline = time.monotonic() + timeout_s
            thread = self._thread
            self._cond.notify_all()
        self._stopping.set()  # no more waiting between retries
        if thread is not None:
            thread.join(timeout_s + 0.5)

    def status(self):
        with self._cond:
            stats = dict(self._stats)
            stats["queued_spans"] = len(self._queue)
        stats["last_ok_at"], stats["last_error_at"] = _iso(stats["last_ok_at"]), _iso(stats["last_error_at"])
        return stats

    # -- the background thread ------------------------------------------------------------------

    def _run(self):
        while True:
            with self._cond:
                if not (self._closed or self._flush) and len(self._queue) < self.max_batch:
                    self._cond.wait(self.interval_s)
                if self._closed and (not self._queue or time.monotonic() >= self._deadline):
                    self._stats["dropped_spans"] += len(self._queue)
                    self._queue.clear()
                    self._cond.notify_all()
                    return
                batch = [self._queue.popleft() for _ in range(min(self.max_batch, len(self._queue)))]
                if not self._queue:
                    self._flush = False
                self._busy = bool(batch)
            try:
                if batch:
                    self._export(batch)
            except Exception as exc:  # never let the thread die: the spans are lost, the work is not
                self._failed(f"internal_{type(exc).__name__}"[:60], len(batch))
            finally:
                with self._cond:
                    self._busy = False
                    self._cond.notify_all()

    def _export(self, batch):
        body = encode_request(self.resource, batch)
        outcome = None
        for delay in (0.0, *self.retry_delays_s):
            if delay and self._stopping.wait(delay):
                break  # stopping: no more retries
            outcome, retry, rejected = self._post(body)
            if outcome is None or not retry:
                break
        if outcome is None:
            self._sent(len(batch), rejected)
        else:
            self._failed(outcome, len(batch))

    def _post(self, body):
        """``(None, False, rejected)`` when the receiver took the batch, else ``(error code, retry?, 0)``."""
        key = (self._environ.get(KEY_ENV) or "").strip()  # read at call time (ADR-013)
        if not key:
            return "key_missing", False, 0
        request = urllib.request.Request(self.url, data=body, method="POST", headers={
            "Content-Type": "application/json", "x-honeycomb-team": key,
            "User-Agent": f"neuron-flow/{__version__}"})
        try:
            with self._open(request, timeout=self.timeout_s) as response:
                raw = response.read(65536)
                status = response.status
        except urllib.error.HTTPError as exc:
            try:
                exc.close()
            except Exception:
                pass
            return f"http_{exc.code}", exc.code in (408, 429) or exc.code >= 500, 0
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
            return "network", True, 0
        if not 200 <= status < 300:
            return f"http_{status}", False, 0
        return None, False, _rejected_spans(raw)

    def _sent(self, count, rejected):
        rejected = min(rejected, count)
        with self._cond:
            self._stats["exported_spans"] += count - rejected
            self._stats["dropped_spans"] += rejected
            self._stats["last_ok_at"] = time.time()
            self._stats["last_error"] = "spans_rejected" if rejected else None
            if rejected:
                self._stats["last_error_at"] = time.time()
        self._log("spans_rejected" if rejected else None, rejected)

    def _failed(self, code, count):
        with self._cond:
            self._stats["dropped_spans"] += count
            self._stats["failed_exports"] += 1
            self._stats["last_error"], self._stats["last_error_at"] = code, time.time()
        self._log(code, count)

    def _log(self, code, count):
        """One line when the outcome changes, never one per batch, and never the key."""
        if code == self._logged:
            return
        if code is None:
            log.info("tracing: sending spans to %s works again", self.host)
        elif code == "spans_rejected":
            log.warning("tracing: %s rejected %d spans", self.host, count)
        else:
            log.warning("tracing: could not send %d spans to %s (%s); they were dropped", count, self.host, code)
        self._logged = code


# -- one object per process -------------------------------------------------------------------------

class _Problem(Exception):
    """A tracing setting that cannot be used; ``args[0]`` is a fixed code."""


def traces_url(endpoint):
    """``<endpoint>/v1/traces``, after checking that the key can only travel to the intended host."""
    if not isinstance(endpoint, str) or len(endpoint) > 200:
        raise _Problem("invalid_endpoint")
    try:
        parts = urlsplit(endpoint)
        host = (parts.hostname or "").lower()
        parts.port  # raises ValueError for a bad port
    except ValueError:
        raise _Problem("invalid_endpoint") from None
    if (not host or parts.username or parts.password or "@" in parts.netloc or parts.query or parts.fragment
            or not (parts.scheme == "https" or (parts.scheme == "http" and host in _LOOPBACK))):
        raise _Problem("invalid_endpoint")
    path = parts.path.rstrip("/")
    if not path.endswith(TRACES_PATH):
        path += TRACES_PATH
    return f"{parts.scheme}://{parts.netloc}{path}"


def _settings(env, process):
    switch = (env.get(SWITCH_ENV) or "").strip().lower()
    if switch in _OFF:
        raise _Problem("switched_off")
    if switch not in _ON:
        raise _Problem("invalid_switch")
    if not (env.get(KEY_ENV) or "").strip():
        raise _Problem("not_configured")
    url = traces_url((env.get(ENDPOINT_ENV) or "").strip() or DEFAULT_ENDPOINT)
    service = (env.get(SERVICE_NAME_ENV) or "").strip() or DEFAULT_SERVICE_NAME
    if not _NAME.fullmatch(service):
        raise _Problem("invalid_service_name")
    environment = (env.get(ENVIRONMENT_ENV) or "").strip() or (
        "render" if env.get("RENDER") else "ci" if env.get("GITHUB_ACTIONS") else "local")
    if not _NAME.fullmatch(environment):
        raise _Problem("invalid_environment")
    commit = (env.get("RENDER_GIT_COMMIT") or env.get("GITHUB_SHA") or "").strip().lower()
    version = __version__ + (f"+{commit[:12]}" if _COMMIT.fullmatch(commit) else "")
    resource = {"service.name": service, "service.version": version, "service.instance.id": str(uuid.uuid4()),
                "deployment.environment.name": environment, "neuron_flow.process": process,
                "telemetry.sdk.name": "neuron-flow", "telemetry.sdk.language": "python",
                "telemetry.sdk.version": __version__}
    return url, service, resource


class Tracing:
    """Tracing for one process (the API or the Runner). Every method is safe to call when tracing is off."""

    def __init__(self, exporter=None, *, problem=None, service_name=None):
        self.exporter = exporter
        self.problem = problem
        self.service_name = service_name

    @classmethod
    def off(cls, problem="not_configured"):
        return cls(None, problem=problem)

    @classmethod
    def from_env(cls, process, environ=None, **exporter_options):
        env = os.environ if environ is None else environ
        try:
            url, service, resource = _settings(env, process)
        except _Problem as problem:
            return cls.off(problem.args[0])
        return cls(Exporter(url, resource, environ=env, **exporter_options), service_name=service)

    @property
    def enabled(self):
        return self.exporter is not None

    @property
    def destination(self):
        return self.exporter.host if self.exporter is not None else None

    def start_request(self):
        """New ids for an API request's span, or ``None`` when tracing is off."""
        if self.exporter is None:
            return None
        return RequestTrace(new_trace_id(), new_span_id(), time.time_ns())

    def finish_request(self, trace, *, method, route, status, request_id):
        if trace is None or self.exporter is None:
            return
        try:
            self.exporter.submit([http_span(trace, method=method, route=route, status=status,
                                            request_id=request_id, end_ns=time.time_ns())])
        except Exception as exc:  # a span we cannot build is dropped; the request is unaffected
            log.warning("tracing: could not record a request span (%s)", type(exc).__name__)

    def export(self, spans):
        if self.exporter is not None:
            self.exporter.submit(spans)

    def status(self):
        """For ``/v1/status``: on or off (with the reason), where spans go, and how this process's exports went."""
        view = {"enabled": self.enabled, "problem": self.problem, "destination": self.destination,
                "service_name": self.service_name}
        if self.exporter is not None:
            view.update(self.exporter.status())
        return view

    def flush(self, timeout_s=5.0):
        return self.exporter.flush(timeout_s) if self.exporter is not None else True

    def shutdown(self, timeout_s=2.0):
        if self.exporter is not None:
            self.exporter.shutdown(timeout_s)
