"""HTTP routes of the intake API and the web page. Framework-free, standard library only.

  GET  /                          the web page (it holds no secrets and asks for the access key)
  GET  /static/app.css, app.js    page assets
  GET  /healthz                   liveness for the host: process up, queue database readable (no key)
  GET  /readyz                    readiness: 200 while the Runner can work cases, else 503 and a state code (no key)
  GET  /v1/status                 Runner heartbeat, queue counts and timings, AI mode, tracing, storage, limits, steps
  POST /v1/jobs                   admit a job: 202 new, 200 duplicate, 400/401/409/413/415/429/503
  GET  /v1/jobs                   newest first: ?limit=1-100&before=<seq>
  GET  /v1/jobs/{job_id}          status, step plan, reviewer proposal, step timeline, AI provenance
  GET  /v1/jobs/{job_id}/events   bounded pages: ?after=<seq>&limit=1-100
  POST /v1/jobs/{job_id}/cancel   withdraw a job that is still QUEUED: 200, or 409 not_cancellable
  GET  /v1/reviews                cases waiting for a person: ?state=PENDING|APPROVED|REJECTED&limit=1-100&after=
  GET  /v1/reviews/{review_id}    the case, the proposal (rules, AI second opinion, why raised), every decision
  GET  /v1/reviews/scorecard      rules and AI against the categories people recorded (roadmap 2.8) and reviewer
                                  time per group (2.10); counts only
  POST /v1/reviews/{review_id}/decisions   approve or reject: 201 new, 200 the same decision again, 400/404/409
  GET  /v1/me                     who the credential is and what its role may do
  GET  /v1/tokens                 the owner: every personal token, without secrets
  POST /v1/tokens                 the owner: issue a token for a reviewer or a submitter; 201, shown once
  POST /v1/tokens/{token_id}/revoke   the owner: revoke at once; 200, or 404

Every ``/v1`` route needs ``Authorization: Bearer <credential>``: the owner's shared key
``NEURON_FLOW_ACCESS_KEY`` or a personal token, and the credential's role must be allowed on the route
(``app.services.access``, ADR-034; 401 for a wrong credential, 403 for a role without the right). Responses never
contain file paths, credentials or stack traces; the one exception is the reply that creates a token, which holds
it once. Every response carries ``X-Request-Id``: a well-formed id the client sent, or a new random one. The same
id is written in the access log line and, for a new job, in its ``job.queued`` event, so one request can be
followed from the log to the job record.

When tracing is on (``app.observability.tracing``), every ``/v1`` request also becomes one span, and a job
that a request admits records that span as its parent, so the Runner's spans of the job join the same
trace. The page files, ``/healthz`` and ``/readyz`` are not traced.

Liveness and readiness are two checks (roadmap 1.7, ADR-036). ``/healthz`` stays the host's health check: it fails only
when this process cannot read the queue, because Render restarts a service whose check fails and, on the free plan, a
restart empties the queue. ``/readyz`` says whether the Runner can work cases now, as a state code and nothing else:
with the AI settings broken it answers 503 ``blocked_config`` while ``/healthz`` answers 200 and cases are still
admitted, to wait in the queue.

The API only reads, admits and cancels jobs that are still queued, and records people's review decisions in the
queue database (``app.services.reviews``); it never opens the Core ``Runtime`` (ADR-001). An approval's
skill-handoff route (ADR-030, ``app.exchange``) is written in the same transaction as the decision; a job's detail
shows where it came from (``handoff.from``) and what it handed on (``handoff.to``), and ``/v1/status`` lists the
routes. A route-only workflow type cannot be admitted here.

Retention is stated, not implied: ``/v1/status``, every new job's reply and every decision's reply carry
``retention`` (whether the data folder survives a restart, and the queue database's ``store_id``). On storage
that is not persistent (Render's free plan) a 202 means "stored until the next sleep, restart or deploy", and the
page uses ``store_id`` to tell people when the cases they sent are gone (review of 2026-11-10, point 3).
"""

from dataclasses import dataclass, field
import hashlib
import hmac
import json
import logging
from pathlib import Path
import re
import secrets
import time

from neuron_flow import __version__
from neuron_flow.model import decode

from app.domains.case_triage.contracts import SUMMARY_MAX_CHARS, SUMMARY_MIN_CHARS
from app.domains.study_guide.contracts import MESSAGE_MAX_CHARS, MESSAGE_MIN_CHARS
from app.exchange import Exchange
from app.llm import LLMConfig, LLMConfigError
from app.observability.tracing import Tracing, parse_traceparent
from app.persistence import DECIDED, PENDING, QUEUED, REVIEW_REQUIRED, StateError
from app.persistence.queue_store import iso
from app.services import access
from app.services.admission import AdmissionError, admit
from app.services.metrics import queue_metrics
from app.services.results import plan_view
from app.services import review_labels
from app.services import reviews as review_service
from app.services.workflows import CATALOG, DEFAULT_WORKFLOW, preview_spec
from app.settings import MIN_ACCESS_KEY_LENGTH

from .limits import RateLimiter

MAX_BODY_BYTES = 16 * 1024
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
JOB_PATH = re.compile(r"^/v1/jobs/(job_[0-9a-f]{24})(/events|/cancel)?$")
JOB_ID_TEXT = re.compile(r"(?:job|rev)_[0-9a-f]{24}")  # a review id is named after its job, so it counts as one
REVIEW_PATH = re.compile(r"^/v1/reviews/(rev_[0-9a-f]{24})(/decisions)?$")
TOKEN_PATH = re.compile(r"^/v1/tokens/([0-9a-f]{16})/revoke$")
SCORECARD_PATH = "/v1/reviews/scorecard"
LOST_ON = ("sleep", "restart", "deploy")  # what wipes a data folder that is not persistent (Render's free plan)
READY = ("idle", "running")  # the Runner states in which ``/readyz`` answers 200
# The Runner's heartbeat state as a readiness code. A Runner that has not reached its loop yet is "starting".
_READINESS = {"idle": "idle", "running": "running", "blocked_config": "blocked_config", "starting": "starting",
              "reconciling": "starting", "stopped": "not_alive"}
# A client may send its own id: 1-64 characters, letters, digits, '.', '_' or '-'. Nothing else reaches the logs.
REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
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
    request_id: str = ""                          # set by ApiApp.request_id(); empty means "not yet"
    trace_parent: str = ""                        # the request's span as a W3C traceparent; empty when not traced


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


def finalize(response, request_id=None):
    """Add the security headers every response carries, and the request id when there is one."""
    extra = [("X-Request-Id", request_id)] if request_id else []
    response.headers = [*_COMMON_HEADERS, *response.headers, *extra]
    return response


def new_request_id():
    return "req_" + secrets.token_hex(8)


def readiness(row, *, now, stale_s, since):
    """The Runner's readiness as one code: ``idle`` or ``running`` when it can work cases, otherwise
    ``blocked_config`` (the AI settings cannot work), ``starting`` or ``not_alive`` (roadmap 1.7).

    ``row`` is the queue's heartbeat row (``None`` before the first one) and ``since`` the time this API process
    started. A heartbeat from before that belongs to an earlier Runner and does not count: until the new Runner writes
    one the code is ``starting``, and ``not_alive`` once ``stale_s`` has passed without one.
    """
    if row is None or row["heartbeat_at"] < since:
        return "starting" if now - since <= stale_s else "not_alive"
    if now - row["heartbeat_at"] > stale_s:
        return "not_alive"
    return _READINESS.get(row["state"], "unknown")


class ApiApp:
    def __init__(self, settings, store, *, catalog=None, clock=time.time, reporter=None, tracing=None, exchange=None):
        self.settings = settings
        self.store = store
        self.catalog = CATALOG if catalog is None else catalog
        # The skill-handoff exchange (ADR-030); a route table that does not fit the catalog fails at start.
        self.exchange = exchange or Exchange(self.catalog)
        self.clock = clock
        self.started_at = clock()  # readiness counts only Runner heartbeats written after this (``readiness``)
        self.reporter = reporter
        self.tracing = tracing if tracing is not None else Tracing.off()
        key = settings.access_key
        self._key_digest = hashlib.sha256(key.encode("utf-8")).digest() if key else None
        self._submit_limit = RateLimiter(settings.submit_per_minute, 60, total_capacity=settings.submit_per_minute * 4)
        self._decide_limit = RateLimiter(settings.submit_per_minute, 60, total_capacity=settings.submit_per_minute * 4)
        self._token_limit = RateLimiter(10, 60)  # new personal tokens per client and minute (ADR-034)
        self._auth_limit = RateLimiter(10, 60)
        self._assets = {path: ((WEB_DIR / name).read_bytes(), content_type)
                        for path, (name, content_type) in _ASSETS.items()}
        self._plans = {}  # workflow name -> step plan; the catalog and the environment are fixed per process

    # -- entry point ---------------------------------------------------------------------------

    def request_id(self, headers):
        """The id for one request: the client's ``X-Request-Id`` if it is safe to log, else a new one.

        Refused (and replaced): anything malformed, anything that contains a job or review id (access lines
        never carry job ids, and a review id is named after its job), the access key itself and anything that
        holds the start of a personal token (a client that confuses the two headers).
        """
        sent = headers.get("x-request-id", "").strip()
        if not REQUEST_ID.fullmatch(sent) or JOB_ID_TEXT.search(sent) or access.TOKEN_LIKE.search(sent):
            return new_request_id()
        if self._key_digest is not None and hmac.compare_digest(
                hashlib.sha256(sent.encode("utf-8")).digest(), self._key_digest):
            return new_request_id()
        return sent

    def handle(self, request):
        if not request.request_id:
            request.request_id = self.request_id(request.headers)
        try:
            response = self._route(request)
        except BadParameter as exc:
            response = error(400, "invalid_parameter", str(exc))
        except Exception as exc:  # never leak a traceback; the log line carries no request data
            log.exception("api: unexpected error on %s %s", request.method, route_label(request.path))
            if self.reporter is not None:
                self.reporter.capture_exception(exc)
            response = error(500, "internal_error", "Something went wrong on the server",
                             request_id=request.request_id)
        return finalize(response, request.request_id)

    def _route(self, request):
        method, path = request.method, request.path
        reading = method in ("GET", "HEAD")
        if path in self._assets:
            return self._asset(path) if reading else _not_allowed("GET, HEAD")
        if path == "/healthz":
            return self._health() if reading else _not_allowed("GET, HEAD")
        if path == "/readyz":
            return self._ready() if reading else _not_allowed("GET, HEAD")
        if not path.startswith("/v1/"):
            return error(404, "not_found", "No such page")
        identity, denied = self._authorize(request)
        if denied is not None:
            return denied
        template = route_template(path)
        if access.known(method, template) and not access.allowed(method, template, identity.role):
            return error(403, "forbidden", "Your role cannot do this", role=identity.role)
        if path == "/v1/status":
            return self._status() if reading else _not_allowed("GET, HEAD")
        if path == "/v1/me":
            return json_response(200, access.me_view(identity)) if reading else _not_allowed("GET, HEAD")
        if path == "/v1/tokens":
            if method == "POST":
                return self._issue(request, identity)
            return self._tokens() if reading else _not_allowed("GET, HEAD, POST")
        token_match = TOKEN_PATH.fullmatch(path)
        if token_match is not None:
            return self._revoke(request, token_match.group(1), identity) if method == "POST" else _not_allowed("POST")
        if path == "/v1/jobs":
            if method == "POST":
                return self._submit(request)
            return self._list(request) if reading else _not_allowed("GET, HEAD, POST")
        if path == "/v1/reviews":
            return self._reviews(request) if reading else _not_allowed("GET, HEAD")
        if path == SCORECARD_PATH:
            return self._scorecard() if reading else _not_allowed("GET, HEAD")
        review_match = REVIEW_PATH.fullmatch(path)
        if review_match is not None:
            if review_match.group(2):
                return (self._decide(request, review_match.group(1), identity) if method == "POST"
                        else _not_allowed("POST"))
            return self._review(review_match.group(1)) if reading else _not_allowed("GET, HEAD")
        match = JOB_PATH.fullmatch(path)
        if match is None:
            return error(404, "not_found", "No such API route")
        if match.group(2) == "/cancel":
            return self._cancel(request, match.group(1)) if method == "POST" else _not_allowed("POST")
        if not reading:
            return _not_allowed("GET, HEAD")
        job = self.store.get(match.group(1))
        if job is None:
            return error(404, "job_not_found", "No job with this id")
        return self._events(request, job) if match.group(2) else json_response(200, self._job_view(job))

    # -- access ----------------------------------------------------------------------------------

    def _authorize(self, request):
        """``(identity, None)`` for a valid credential, or ``(None, response)``: 503 without a configured key, 429
        after too many wrong credentials from this client, 401 for a wrong, unknown, revoked or lost one."""
        if self._key_digest is None:
            return None, error(503, "access_key_not_configured",
                               f"Set NEURON_FLOW_ACCESS_KEY (at least {MIN_ACCESS_KEY_LENGTH} characters) and"
                               " restart the service", problem=self.settings.access_key_problem)
        if self._auth_limit.blocked(request.client):
            retry = self._auth_limit.retry_after(request.client)
            return None, error(429, "too_many_attempts", "Too many wrong access keys; wait and try again",
                               headers=[("Retry-After", str(retry))], retry_after_s=retry)
        scheme, _, credential = request.headers.get("authorization", "").partition(" ")
        identity = None
        if scheme.lower() == "bearer" and credential.strip():
            identity = access.authenticate(self.store, credential.strip(), self._key_digest, now=self.clock())
        if identity is not None:
            return identity, None
        self._auth_limit.allow(request.client)  # count the failure
        return None, error(401, "unauthorized", "Missing or wrong access key",
                           headers=[("WWW-Authenticate", "Bearer")])

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

    def _ready(self):
        """Readiness, apart from liveness (roadmap 1.7, ADR-036): a state code only, never the Runner's detail text,
        which may name a setting. Cases are admitted whatever it says; they wait in the queue."""
        try:
            row = self.store.runner()
        except Exception:
            return json_response(503, {"ok": False, "state": "queue_unavailable"})
        state = readiness(row, now=self.clock(), stale_s=self.settings.runner_stale_s, since=self.started_at)
        return json_response(200 if state in READY else 503, {"ok": state in READY, "state": state})

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
            "metrics": queue_metrics(self.store, now),
            "ai": {**llm, "simulated": llm.get("provider") == "mock", "problem": problem},
            "tracing": self.tracing.status(),
            # Persistent only when the start found the folder on a disk of its own (roadmap 1.7); never a path.
            "storage": {"kind": self.settings.storage, "persistent": self.settings.persistent,
                        "check": self.settings.storage_check.result,
                        "filesystem": self.settings.storage_check.filesystem},
            "retention": self._retention(),
            "reviews": {**self.store.review_counts(), **review_service.policy()},
            "access": access.policy(),
            # A case's summary (case_triage) and a study request's message (study_guide.v1), checked at admission.
            "limits": {"max_queued": self.settings.max_queued, "submit_per_minute": self.settings.submit_per_minute,
                       "summary_min_chars": SUMMARY_MIN_CHARS, "summary_max_chars": SUMMARY_MAX_CHARS,
                       "message_min_chars": MESSAGE_MIN_CHARS, "message_max_chars": MESSAGE_MAX_CHARS,
                       "max_body_bytes": MAX_BODY_BYTES},
            "workflows": [{"name": w.name, "description": w.description, "steps": self._steps(w),
                           "route_only": w.route_only} for w in self.catalog.values()],
            # The skill-handoff routes and their common language (ADR-030), in plain words; never a fact value.
            "handoff": {**self.exchange.view(), "counts": self.store.handoff_counts()},
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
        except ValueError:  # a SpecError, or any other parse failure: the client's input, never a 500
            return error(400, "invalid_json", "The body is not valid JSON, or it repeats a field")
        try:
            job, created = admit(self.store, body, max_queued=self.settings.max_queued, catalog=self.catalog,
                                 request_id=request.request_id, trace_parent=request.trace_parent)
        except AdmissionError as exc:
            headers = [("Retry-After", "60")] if exc.status == 503 else []
            return error(exc.status, exc.code, exc.message, headers=headers, **exc.extra)
        return json_response(202 if created else 200,
                             {**self._job_view(job), "created": created, "retention": self._retention()},
                             [("Location", f"/v1/jobs/{job['job_id']}")])

    def _cancel(self, request, job_id):
        """Withdraw a queued job. The body may be empty or ``{}``; nothing in it changes the outcome.

        Core cannot pause or stop a running job, so only QUEUED jobs can be cancelled. Cancelling an
        already cancelled job is a no-op that returns the same record (200, ``changed: false``).
        """
        if request.body.strip():
            content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                return error(415, "unsupported_media_type", "Send JSON with Content-Type: application/json")
            try:
                body = decode(request.body)
            except ValueError:  # a SpecError, or any other parse failure: the client's input, never a 500
                return error(400, "invalid_json", "The body is not valid JSON, or it repeats a field")
            if body != {}:
                return error(400, "invalid_fields", "A cancel request takes no fields; send {} or nothing")
        try:
            job, changed = self.store.cancel(job_id, request_id=request.request_id)
        except KeyError:
            return error(404, "job_not_found", "No job with this id")
        except StateError as exc:
            return error(409, "not_cancellable", "Only a job that is still waiting in the queue can be cancelled",
                         job_status=str(exc))
        return json_response(200, {**self._job_view(job), "changed": changed})

    def _reviews(self, request):
        raw_state = (request.query.get("state") or [PENDING])[-1]
        state = review_service.known_state(raw_state)
        if state is None:
            raise BadParameter("state must be PENDING, APPROVED or REJECTED")
        limit = _int_param(request, "limit", 20, 1, 100)
        raw_after = (request.query.get("after") or [None])[-1]
        after = review_service.parse_after(raw_after) if raw_after is not None else None
        if raw_after is not None and after is None:
            raise BadParameter("after must be the next_after value of the previous page")
        items, next_after = self.store.list_reviews(state=state, limit=limit, after=after)
        return json_response(200, {"state": state, "reviews": [review_service.review_summary(item) for item in items],
                                   "next_after": f"{next_after[0]}-{next_after[1]}" if next_after else None,
                                   "counts": self.store.review_counts()})

    def _review(self, review_id):
        review = self.store.get_review(review_id)
        if review is None:
            return error(404, "review_not_found", "No review with this id")
        return json_response(200, review_service.review_detail(review))

    def _scorecard(self):
        """Rules and AI against the categories people recorded (roadmap 2.8): counts and rates, never case text.
        It says what its labels are (``label_scope``) and how long the decisions it counts will last."""
        return json_response(200, {**review_labels.report(self.store), "retention": self._retention()})

    def _decide(self, request, review_id, identity):
        """A person's decision. The reviewer comes from the credential (the owner's shared key or a reviewer's
        personal token, ADR-034), never from the body."""
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            return error(415, "unsupported_media_type", "Send JSON with Content-Type: application/json")
        if len(request.body) > MAX_BODY_BYTES:
            return error(413, "body_too_large", f"The body is larger than {MAX_BODY_BYTES} bytes")
        allowed, retry = self._decide_limit.allow(request.client)
        if not allowed:
            return error(429, "rate_limited", "Too many decisions; wait and try again",
                         headers=[("Retry-After", str(retry))], retry_after_s=retry)
        try:
            body = decode(request.body)
        except ValueError:  # a SpecError, or any other parse failure: the client's input, never a 500
            return error(400, "invalid_json", "The body is not valid JSON, or it repeats a field")
        try:
            review, row, created = review_service.decide(self.store, review_id, body, reviewer=identity.reviewer,
                                                         request_id=request.request_id, exchange=self.exchange)
        except review_service.DecisionError as exc:
            return error(exc.status, exc.code, exc.message, **exc.extra)
        # What the decision handed on (ADR-030): the same rows for a repeated click, never a second job.
        handoffs = [self.exchange.handoff_view(item) for item in self.store.handoffs_from(review["job_id"])]
        return json_response(201 if created else 200,
                             {"created": created, "decision": review_service.decision_view(row),
                              "review": review_service.review_detail(review), "handoffs": handoffs,
                              "retention": self._retention()},
                             [("Location", f"/v1/reviews/{review_id}")])

    # -- personal tokens (the owner only, ADR-034) ----------------------------------------------------

    def _json_body(self, request, limiter, what):
        """The decoded JSON body, or an error response: the content type, size, rate and syntax checks the write
        routes share. Returns ``(body, None)`` or ``(None, response)``."""
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            return None, error(415, "unsupported_media_type", "Send JSON with Content-Type: application/json")
        if len(request.body) > MAX_BODY_BYTES:
            return None, error(413, "body_too_large", f"The body is larger than {MAX_BODY_BYTES} bytes")
        allowed, retry = limiter.allow(request.client)
        if not allowed:
            return None, error(429, "rate_limited", f"Too many {what}; wait and try again",
                               headers=[("Retry-After", str(retry))], retry_after_s=retry)
        try:
            return decode(request.body), None
        except ValueError:  # a SpecError, or any other parse failure: the client's input, never a 500
            return None, error(400, "invalid_json", "The body is not valid JSON, or it repeats a field")

    def _issue(self, request, identity):
        """A new personal token. The reply is the only place its secret ever appears."""
        body, refused = self._json_body(request, self._token_limit, "new tokens")
        if refused is not None:
            return refused
        try:
            token, row = access.issue(self.store, body, created_by=identity.token_id, now=self.clock())
        except access.TokenError as exc:
            return error(exc.status, exc.code, exc.message, **exc.extra)
        log.info("api: access token %s issued for the role %s", row["token_id"], row["role"])
        return json_response(201, {"token": token, "shown_once": True, "token_info": access.token_view(row),
                                   "retention": self._retention()}, [("Location", "/v1/tokens")])

    def _tokens(self):
        rows = self.store.list_tokens()
        return json_response(200, {"tokens": [access.token_view(row) for row in rows],
                                   "active": sum(1 for row in rows if row["revoked_at"] is None),
                                   **access.policy(), "retention": self._retention()})

    def _revoke(self, request, token_id, identity):
        """Revoke a token. The body may be empty or ``{}``; revoking it again returns the same record."""
        if request.body.strip():
            content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                return error(415, "unsupported_media_type", "Send JSON with Content-Type: application/json")
            try:
                body = decode(request.body)
            except ValueError:
                return error(400, "invalid_json", "The body is not valid JSON, or it repeats a field")
            if body != {}:
                return error(400, "invalid_fields", "A revoke request takes no fields; send {} or nothing")
        try:
            row, changed = self.store.revoke_token(token_id, revoked_by=identity.token_id, now=self.clock())
        except KeyError:
            return error(404, "token_not_found", "No token with this id")
        if changed:
            log.info("api: access token %s revoked", token_id)
        return json_response(200, {"token_info": access.token_view(row), "changed": changed})

    def _retention(self):
        """How long what the API just stored will last: persistent storage, or until the next wipe."""
        persistent = self.settings.persistent
        store = self.store.store_info()
        return {"persistent": persistent, "lost_on": [] if persistent else list(LOST_ON),
                "store_id": store["id"], "store_started_at": store["created_at"]}

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

    def _steps(self, workflow):
        """The steps a new job of this workflow would run (``None`` if they cannot be described here).

        Built once per workflow from a placeholder case; nothing is admitted and Core is not opened.
        """
        if workflow.name not in self._plans:
            try:
                self._plans[workflow.name] = plan_view(preview_spec(workflow, LLMConfig.from_env()))
            except Exception:  # informational: the page then shows no preview, and admission is unaffected
                log.warning("api: could not describe the steps of workflow %s", workflow.name, exc_info=True)
                self._plans[workflow.name] = None
        return self._plans[workflow.name]

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
            admission = self.store.admission(job["job_id"])
            view["request_id"] = admission.get("request_id")
            # The trace in Honeycomb that holds this job's spans (recorded only when tracing was on).
            trace = parse_traceparent(admission.get("trace_parent"))
            view["trace_id"] = trace[0] if trace else None
            # The plan frozen when the Runner claimed the job: what it really runs. None while queued.
            view["plan"] = plan_view(job["spec"]) if job["spec"] else None
            view["result"] = job["result"]
            # A person's review: waiting (REVIEW_REQUIRED) or decided (APPROVED, REJECTED); None for other jobs.
            view["human_review"] = (review_service.job_review_view(self.store.review_of_job(job["job_id"]))
                                    if job["status"] == REVIEW_REQUIRED or job["status"] in DECIDED else None)
            # Skill handoffs (ADR-030): the one that started this job, and those this job started or had refused.
            came = self.store.handoff_to(job["job_id"])
            view["handoff"] = {"from": self.exchange.handoff_view(came) if came else None,
                               "to": [self.exchange.handoff_view(item) for item in self.store.handoffs_from(job["job_id"])]}
        else:
            view["summary_preview"] = (case.get("summary") or case.get("message") or "")[:90]
            came = self.store.handoff_to(job["job_id"])
            view["from_job_id"] = came["source_job_id"] if came else None
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
    """Path for log lines, with job, review and token ids replaced, so logs stay short and comparable. Anything that
    looks like a personal token (pasted into an address by mistake) is replaced too."""
    path = re.sub(r"nf_[0-9a-f]{16}_[A-Za-z0-9_-]*", "{token}", path)
    path = re.sub(r"(?<=/v1/tokens/)[^/]+", "{token_id}", path)
    return re.sub(r"rev_[0-9a-f]{24}", "{review_id}", re.sub(r"job_[0-9a-f]{24}", "{job_id}", path))[:100]


def traced(path):
    """Only API requests become spans: the page files and the health check carry no work."""
    return path.startswith("/v1/")


def route_template(path):
    """The route of an API path as a fixed template (``/v1/jobs/{job_id}``), or ``None`` for an unknown path.

    Spans carry this, never the path itself, so a path a client made up cannot carry text into a trace."""
    if path in ("/v1/status", "/v1/jobs", "/v1/reviews", SCORECARD_PATH, "/v1/me", "/v1/tokens"):
        return path
    if TOKEN_PATH.fullmatch(path):
        return "/v1/tokens/{token_id}/revoke"
    review = REVIEW_PATH.fullmatch(path)
    if review:
        return "/v1/reviews/{review_id}" + (review.group(2) or "")
    match = JOB_PATH.fullmatch(path)
    return "/v1/jobs/{job_id}" + (match.group(2) or "") if match else None
