"""HTTP routes of the intake API and the web page. Framework-free, standard library only.

  GET  /                          the web page (it holds no secrets and asks for the access key)
  GET  /static/app.css, app.js    page assets
  GET  /healthz                   liveness for the host: process up, queue database readable (no key)
  GET  /v1/status                 Runner heartbeat, queue counts, AI mode, storage, limits
  POST /v1/jobs                   admit a job: 202 new, 200 duplicate, 400/401/409/413/415/429/503
  GET  /v1/jobs                   newest first: ?limit=1-100&before=<seq>
  GET  /v1/jobs/{job_id}          status, reviewer proposal, step timeline, AI provenance
  GET  /v1/jobs/{job_id}/events   bounded pages: ?after=<seq>&limit=1-100

Every ``/v1`` route needs ``Authorization: Bearer <NEURON_FLOW_ACCESS_KEY>``. Responses never contain
file paths, credentials or stack traces. The API only reads and admits; it never opens the Core
``Runtime`` (ADR-001).
"""

from dataclasses import dataclass, field
import hashlib
import hmac
import json
import logging
from pathlib import Path
import re
import time

from neuron_flow import __version__
from neuron_flow.model import SpecError, decode

from app.domains.case_triage.contracts import SUMMARY_MAX_CHARS, SUMMARY_MIN_CHARS
from app.llm import LLMConfig, LLMConfigError
from app.persistence import QUEUED
from app.persistence.queue_store import iso
from app.services.admission import AdmissionError, admit
from app.services.workflows import CATALOG, DEFAULT_WORKFLOW
from app.settings import MIN_ACCESS_KEY_LENGTH

from .limits import RateLimiter

MAX_BODY_BYTES = 16 * 1024
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
JOB_PATH = re.compile(r"^/v1/jobs/(job_[0-9a-f]{24})(/events)?$")
_ASSETS = {"/": ("index.html", "text/html; charset=utf-8"),
           "/static/app.css": ("app.css", "text/css; charset=utf-8"),
           "/static/app.js": ("app.js", "text/javascript; charset=utf-8")}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
_COMMON_HEADERS = (("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer"),
                   ("X-Frame-Options", "DENY"), ("Strict-Transport-Security", "max-age=31536000"))
log = logging.getLogger("neuron_flow.api")


@dataclass
class Request:
    method: str
    path: str
    query: dict = field(default_factory=dict)     # name -> list of values
    headers: dict = field(default_factory=dict)   # lower-case names
    body: bytes = b""
    client: str = "local"


@dataclass
class Response:
    status: int
    body: bytes = b""
    headers: list = field(default_factory=list)


class BadParameter(ValueError):
    pass


def json_response(status, payload, headers=()):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return Response(status, body, [("Content-Type", "application/json; charset=utf-8"),
                                   ("Cache-Control", "no-store"), *headers])


def error(status, code, message, *, headers=(), **extra):
    return json_response(status, {"error": code, "message": message, **extra}, headers)


def finalize(response):
    """Add the security headers every response carries."""
    response.headers = [*_COMMON_HEADERS, *response.headers]
    return response


class ApiApp:
    def __init__(self, settings, store, *, catalog=None, clock=time.time, reporter=None):
        self.settings = settings
        self.store = store
        self.catalog = CATALOG if catalog is None else catalog
        self.clock = clock
        self.reporter = reporter
        key = settings.access_key
        self._key_digest = hashlib.sha256(key.encode("utf-8")).digest() if key else None
        self._submit_limit = RateLimiter(settings.submit_per_minute, 60, total_capacity=settings.submit_per_minute * 4)
        self._auth_limit = RateLimiter(10, 60)
        self._assets = {path: ((WEB_DIR / name).read_bytes(), content_type)
                        for path, (name, content_type) in _ASSETS.items()}

    # -- entry point ---------------------------------------------------------------------------

    def handle(self, request):
        try:
            response = self._route(request)
        except BadParameter as exc:
            response = error(400, "invalid_parameter", str(exc))
        except Exception as exc:  # never leak a traceback; the log line carries no request data
            log.exception("api: unexpected error on %s %s", request.method, route_label(request.path))
            if self.reporter is not None:
                self.reporter.capture_exception(exc)
            response = error(500, "internal_error", "Something went wrong on the server")
        return finalize(response)

    def _route(self, request):
        method, path = request.method, request.path
        reading = method in ("GET", "HEAD")
        if path in self._assets:
            return self._asset(path) if reading else _not_allowed("GET, HEAD")
        if path == "/healthz":
            return self._health() if reading else _not_allowed("GET, HEAD")
        if not path.startswith("/v1/"):
            return error(404, "not_found", "No such page")
        denied = self._authorize(request)
        if denied is not None:
            return denied
        if path == "/v1/status":
            return self._status() if reading else _not_allowed("GET, HEAD")
        if path == "/v1/jobs":
            if method == "POST":
                return self._submit(request)
            return self._list(request) if reading else _not_allowed("GET, HEAD, POST")
        match = JOB_PATH.fullmatch(path)
        if match is None:
            return error(404, "not_found", "No such API route")
        if not reading:
            return _not_allowed("GET, HEAD")
        job = self.store.get(match.group(1))
        if job is None:
            return error(404, "job_not_found", "No job with this id")
        return self._events(request, job) if match.group(2) else json_response(200, self._job_view(job))

    # -- access ----------------------------------------------------------------------------------

    def _authorize(self, request):
        if self._key_digest is None:
            return error(503, "access_key_not_configured",
                         f"Set NEURON_FLOW_ACCESS_KEY (at least {MIN_ACCESS_KEY_LENGTH} characters) and restart"
                         " the service", problem=self.settings.access_key_problem)
        if self._auth_limit.blocked(request.client):
            retry = self._auth_limit.retry_after(request.client)
            return error(429, "too_many_attempts", "Too many wrong access keys; wait and try again",
                         headers=[("Retry-After", str(retry))], retry_after_s=retry)
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        presented = hashlib.sha256(token.strip().encode("utf-8")).digest()
        if scheme.lower() == "bearer" and token.strip() and hmac.compare_digest(presented, self._key_digest):
            return None
        self._auth_limit.allow(request.client)  # count the failure
        return error(401, "unauthorized", "Missing or wrong access key", headers=[("WWW-Authenticate", "Bearer")])

    # -- routes ----------------------------------------------------------------------------------

    def _asset(self, path):
        body, content_type = self._assets[path]
        headers = [("Content-Type", content_type), ("Cache-Control", "no-cache")]
        if path == "/":
            headers.append(("Content-Security-Policy", CSP))
        return Response(200, body, headers)

    def _health(self):
        try:
            self.store.ping()
        except Exception:
            return json_response(503, {"ok": False})
        # Whether a key is set (never the key itself) lets the page show setup steps without a 401.
        return json_response(200, {"ok": True, "access_key": "configured" if self._key_digest else "not_configured"})

    def _status(self):
        runner = self.store.runner()
        now = self.clock()
        runner_view = {"alive": False, "state": "unknown", "heartbeat_age_s": None, "current_job": None,
                       "detail": None, "started_at": None}
        llm = None
        if runner is not None:
            age = max(0.0, now - runner["heartbeat_at"])
            runner_view.update(alive=age <= self.settings.runner_stale_s and runner["state"] != "stopped",
                               state=runner["state"], heartbeat_age_s=round(age, 1),
                               current_job=runner["current_job"], detail=runner["detail"],
                               started_at=iso(runner["started_at"]))
            llm = runner["llm"]
        problem = runner_view["detail"] if runner_view["state"] == "blocked_config" else None
        if llm is None:  # no Runner heartbeat yet: show what the environment asks for
            try:
                config = LLMConfig.from_env()
                llm = {"provider": config.provider, "model": config.model}
            except LLMConfigError as exc:
                llm, problem = {"provider": None, "model": None}, str(exc)[:300]
        return json_response(200, {
            "service": "neuron-flow", "version": __version__,
            "runner": runner_view, "queue": self.store.counts(),
            "ai": {**llm, "simulated": llm.get("provider") == "mock", "problem": problem},
            "storage": {"kind": self.settings.storage, "persistent": self.settings.persistent},
            "limits": {"max_queued": self.settings.max_queued, "submit_per_minute": self.settings.submit_per_minute,
                       "summary_min_chars": SUMMARY_MIN_CHARS, "summary_max_chars": SUMMARY_MAX_CHARS,
                       "max_body_bytes": MAX_BODY_BYTES},
            "workflows": [{"name": w.name, "description": w.description} for w in self.catalog.values()],
            "default_workflow": DEFAULT_WORKFLOW if DEFAULT_WORKFLOW in self.catalog else next(iter(self.catalog)),
        })

    def _submit(self, request):
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            return error(415, "unsupported_media_type", "Send JSON with Content-Type: application/json")
        if len(request.body) > MAX_BODY_BYTES:
            return error(413, "body_too_large", f"The body is larger than {MAX_BODY_BYTES} bytes")
        allowed, retry = self._submit_limit.allow(request.client)
        if not allowed:
            return error(429, "rate_limited", "Too many submissions; wait and try again",
                         headers=[("Retry-After", str(retry))], retry_after_s=retry)
        try:
            body = decode(request.body)
        except SpecError:
            return error(400, "invalid_json", "The body is not valid JSON, or it repeats a field")
        try:
            job, created = admit(self.store, body, max_queued=self.settings.max_queued, catalog=self.catalog)
        except AdmissionError as exc:
            headers = [("Retry-After", "60")] if exc.status == 503 else []
            return error(exc.status, exc.code, exc.message, headers=headers, **exc.extra)
        return json_response(202 if created else 200, {**self._job_view(job), "created": created},
                             [("Location", f"/v1/jobs/{job['job_id']}")])

    def _list(self, request):
        limit = _int_param(request, "limit", 20, 1, 100)
        before = _int_param(request, "before", None, 1, 2 ** 62)
        jobs, next_before = self.store.list_jobs(limit=limit, before=before)
        return json_response(200, {"jobs": [self._job_view(job, detail=False) for job in jobs],
                                   "next_before": next_before})

    def _events(self, request, job):
        after = _int_param(request, "after", 0, 0, 2 ** 62)
        limit = _int_param(request, "limit", 50, 1, 100)
        events, has_more = self.store.events(job["job_id"], after=after, limit=limit)
        return json_response(200, {"job_id": job["job_id"], "events": events,
                                   "next_after": events[-1]["seq"] if events else after, "has_more": has_more})

    # -- views -----------------------------------------------------------------------------------

    def _job_view(self, job, *, detail=True):
        case = job["input"]
        review = (job["result"] or {}).get("review") or {}
        view = {"job_id": job["job_id"], "seq": job["seq"], "workflow_type": job["workflow_type"],
                "status": job["status"], "case_id": case.get("case_id"), "claims": job["claims"],
                "created_at": iso(job["created_at"]), "updated_at": iso(job["updated_at"]),
                "started_at": iso(job["started_at"]), "finished_at": iso(job["finished_at"]),
                "review_priority": review.get("review_priority"), "suggested_queue": review.get("suggested_queue"),
                "agreement": review.get("agreement"), "failure": job["failure"]}
        if job["status"] == QUEUED:
            view["queue_position"] = self.store.queue_position(job)
        if detail:
            view["input"] = case
            view["result"] = job["result"]
        else:
            view["summary_preview"] = case.get("summary", "")[:90]
        return view


def _not_allowed(allow):
    return error(405, "method_not_allowed", "This method is not allowed here", headers=[("Allow", allow)])


def _int_param(request, name, default, low, high):
    values = request.query.get(name)
    if not values:
        return default
    raw = values[-1]
    if not (raw.isascii() and raw.isdigit()) or len(raw) > 20:
        raise BadParameter(f"{name} must be a whole number")
    value = int(raw)
    if not low <= value <= high:
        raise BadParameter(f"{name} must be between {low} and {high}")
    return value


def route_label(path):
    """Path for log lines, with job ids replaced, so logs stay short and comparable."""
    return re.sub(r"job_[0-9a-f]{24}", "{job_id}", path)[:100]
