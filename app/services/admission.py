"""Admission: check a request, then store it durably in the queue before replying (ADR-002).

Flow for one ``POST /v1/jobs``:
1. the body must be exactly ``{workflow_type, idempotency_key, input}``;
2. the workflow type must be in the catalog, and the input must pass that workflow's own checks,
   so invalid input is refused before any agent could run;
3. the request fingerprint is the SHA-256 of the workflow type plus the normalized input;
4. a new idempotency key creates one QUEUED job; the same key with the same fingerprint returns
   the existing job (a retry or a double click never makes a second job); the same key with a
   different fingerprint is a conflict.
"""

import re
import secrets

from neuron_flow import SpecError
from neuron_flow.model import fingerprint

from app.observability.tracing import parse_traceparent
from app.persistence import QueueFull

from .workflows import CATALOG

IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_FIELDS = {"workflow_type", "idempotency_key", "input"}


class AdmissionError(Exception):
    """A refused request. ``status`` is the HTTP status, ``code`` a stable machine-readable reason."""

    def __init__(self, status, code, message, **extra):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra


def new_job_id():
    return "job_" + secrets.token_hex(12)


def request_fingerprint(workflow_type, normalized_input):
    return fingerprint({"workflow_type": workflow_type, "input": normalized_input})


def admit(store, body, *, max_queued, catalog=CATALOG, request_id=None, trace_parent=None):
    """Returns ``(job, created)``; raises :class:`AdmissionError` when the request is refused.

    ``request_id`` (already checked by the API) and ``trace_parent`` (the admitting request's span, made by
    the API's tracing; only a well-formed W3C value is kept) are stored in the new job's first event.
    """
    if not isinstance(body, dict) or set(body) != _FIELDS:
        raise AdmissionError(400, "invalid_fields", "The body must contain exactly: workflow_type, idempotency_key, input")
    workflow_type = body["workflow_type"]
    workflow = catalog.get(workflow_type) if isinstance(workflow_type, str) else None
    if workflow is None:
        raise AdmissionError(400, "unknown_workflow_type", "Unknown workflow_type", allowed=sorted(catalog))
    key = body["idempotency_key"]
    if not isinstance(key, str) or not IDEMPOTENCY_KEY.fullmatch(key):
        raise AdmissionError(400, "invalid_idempotency_key",
                             "idempotency_key must be 8-128 letters, digits, '.', '_', ':' or '-'")
    try:
        normalized = workflow.check_input(body["input"])
    except SpecError as exc:
        raise AdmissionError(400, "invalid_input", str(exc)) from None
    digest = request_fingerprint(workflow.name, normalized)
    try:
        job, created = store.admit(job_id=new_job_id(), idempotency_key=key, request_fingerprint=digest,
                                   workflow_type=workflow.name, input=normalized, max_queued=max_queued,
                                   request_id=request_id,
                                   trace_parent=trace_parent if parse_traceparent(trace_parent) else None)
    except QueueFull:
        raise AdmissionError(503, "queue_full", "The queue is full; try again in a few minutes") from None
    if not created and job["request_fingerprint"] != digest:
        raise AdmissionError(409, "idempotency_conflict",
                             "This idempotency_key was already used for a different request", job_id=job["job_id"])
    return job, created
