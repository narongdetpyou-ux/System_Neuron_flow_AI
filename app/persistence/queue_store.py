"""The durable job queue of the application layer: one SQLite file, separate from Core's.

Who writes what:
* the API admits jobs (``admit``), cancels jobs that are still queued (``cancel``) and reads them;
* the single Runner claims jobs, freezes the exact Core spec it submits, records outcomes and
  writes a heartbeat.

Core's own database (``<data>/core/state.sqlite3``) is never opened here. Only the Runner talks to
Core, through the public ``Runtime`` API (ADR-001).

Every write runs inside ``BEGIN IMMEDIATE``, so two writers (API threads, the Runner process) never
interleave, and the API replies only after the transaction has committed (ADR-002). Rows never hold
credentials or file paths, and events never hold case text.

Application job states::

    QUEUED -> RUNNING -> REVIEW_REQUIRED | COMPLETED | FAILED | DELIVERY_FAILED
    QUEUED -> CANCELLED   (only before the Runner claims it; a cancelled job never reaches Core)
    REVIEW_REQUIRED -> APPROVED | REJECTED   (a person's decision, roadmap 2.2 and ADR-027)

Reviews (schema version 2): when the Runner records ``REVIEW_REQUIRED``, the same transaction creates the job's
review (``PENDING``). A person's decision is one append-only row in ``review_decisions``; the same transaction
moves the review to ``APPROVED`` or ``REJECTED``, raises its version and moves the job to the same state. Only the
API writes decisions; the Runner never does, and the AI never does. A decision applies once per review version,
and an idempotency key makes a retried click return the same decision instead of a second one.

``meta`` also holds ``store_id`` and ``store_created_at``: a random id and the time of the first ``migrate()``. A
new id means the queue started empty again (on Render's free plan, after every sleep, restart and deploy), so the
page can tell people that the cases they sent earlier are gone instead of letting them vanish silently.

Handoffs (schema version 3, ADR-030): when a job reaches ``COMPLETED`` (``finish``) or ``APPROVED`` (``decide``), the
caller may pass a ``handoff`` builder, the skill-handoff exchange's ``prepare``. It runs inside the same
transaction, on the job's new record, and returns a plan or ``None``. A ``STARTED`` plan inserts the target's
``QUEUED`` job (idempotency key ``handoff:<source>:<route>``) and its ``handoffs`` row; a ``REFUSED`` plan inserts
the row with its reason code and no job. Either way the source gets a ``handoff.*`` event, and all of it commits
with the source's new state or not at all. The queue limit does not apply to a handoff: its source was admitted
under it, a job starts at most one handoff, and chains stop at the route table's depth.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import sqlite3
import time

from neuron_flow.model import encode, fingerprint

SCHEMA_VERSION = 3
QUEUED, RUNNING, CANCELLED = "QUEUED", "RUNNING", "CANCELLED"
REVIEW_REQUIRED, APPROVED, REJECTED = "REVIEW_REQUIRED", "APPROVED", "REJECTED"
TERMINAL = (REVIEW_REQUIRED, "COMPLETED", "FAILED", "DELIVERY_FAILED")  # the outcomes the Runner records
DECIDED = (APPROVED, REJECTED)  # a person's decision on a REVIEW_REQUIRED job
STATUSES = (QUEUED, RUNNING) + TERMINAL + DECIDED + (CANCELLED,)
PENDING = "PENDING"
REVIEW_STATES = (PENDING, APPROVED, REJECTED)
DECISION_STATE = {"APPROVE": APPROVED, "REJECT": REJECTED}
_JSON_COLUMNS = ("input", "spec", "result", "failure")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT UNIQUE NOT NULL,
    idempotency_key TEXT UNIQUE NOT NULL,
    request_fingerprint TEXT NOT NULL,
    workflow_type TEXT NOT NULL,
    input TEXT NOT NULL,
    status TEXT NOT NULL,
    spec TEXT,
    spec_fingerprint TEXT,
    claims INTEGER NOT NULL DEFAULT 0,
    runner_id TEXT,
    result TEXT,
    failure TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS jobs_by_status ON jobs(status, seq);
CREATE TABLE IF NOT EXISTS job_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS job_events_by_job ON job_events(job_id, seq);
CREATE TABLE IF NOT EXISTS runner (
    slot INTEGER PRIMARY KEY CHECK (slot = 1),
    runner_id TEXT NOT NULL,
    pid INTEGER NOT NULL,
    state TEXT NOT NULL,
    current_job TEXT,
    detail TEXT,
    llm TEXT,
    started_at REAL NOT NULL,
    heartbeat_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id TEXT UNIQUE NOT NULL,
    job_id TEXT UNIQUE NOT NULL REFERENCES jobs(job_id),
    version INTEGER NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('PENDING', 'APPROVED', 'REJECTED')),
    priority TEXT NOT NULL CHECK (priority IN ('normal', 'elevated')),
    suggested_category TEXT,
    proposal_sha256 TEXT NOT NULL,
    created_at REAL NOT NULL,
    decided_at REAL
);
CREATE INDEX IF NOT EXISTS reviews_by_state ON reviews(state, seq);
CREATE TABLE IF NOT EXISTS review_decisions (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id TEXT UNIQUE NOT NULL,
    review_id TEXT NOT NULL REFERENCES reviews(review_id),
    version INTEGER NOT NULL,
    reviewer_token_id TEXT NOT NULL,
    reviewer_role TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('APPROVE', 'REJECT')),
    final_category TEXT,
    reason TEXT NOT NULL,
    idempotency_key TEXT UNIQUE NOT NULL,
    request_sha256 TEXT NOT NULL,
    request_id TEXT,
    created_at REAL NOT NULL,
    UNIQUE (review_id, version)
);
CREATE INDEX IF NOT EXISTS review_decisions_by_review ON review_decisions(review_id, seq);
CREATE TABLE IF NOT EXISTS handoffs (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    handoff_id TEXT UNIQUE NOT NULL,
    route_id TEXT NOT NULL,
    routes_tag TEXT NOT NULL,
    vocabulary_tag TEXT NOT NULL,
    translator_out TEXT NOT NULL,
    translator_in TEXT NOT NULL,
    source_job_id TEXT NOT NULL REFERENCES jobs(job_id),
    source_state TEXT NOT NULL,
    target_workflow_type TEXT NOT NULL,
    target_job_id TEXT UNIQUE REFERENCES jobs(job_id),
    depth INTEGER NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('STARTED', 'REFUSED')),
    reason TEXT,
    error_type TEXT,
    envelope TEXT,
    envelope_sha256 TEXT,
    created_at REAL NOT NULL,
    UNIQUE (source_job_id, route_id),
    CHECK ((state = 'STARTED') = (target_job_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS handoffs_by_source ON handoffs(source_job_id, seq);
"""
HANDOFF_STATES = ("STARTED", "REFUSED")


class QueueFull(Exception):
    """Admission refused: too many jobs are already waiting."""


class StateError(RuntimeError):
    """A queue transition that the current job state does not allow."""


class DecisionConflict(Exception):
    """A decision the review's current state does not allow. ``code`` is the API's error code:
    ``idempotency_conflict``, ``already_decided`` or ``version_conflict``; ``extra`` goes into the reply."""

    def __init__(self, code, **extra):
        super().__init__(code)
        self.code, self.extra = code, extra


def review_id_for(job_id):
    """One review per job, named after it: ``job_<hex>`` → ``rev_<hex>``."""
    return "rev_" + job_id[len("job_"):]


def _priority(review):
    return "elevated" if review.get("review_priority") == "elevated" else "normal"


def _insert_review(db, job_id, review, now):
    """The job's PENDING review, from the reviewer proposal the Runner recorded (``result.review``)."""
    db.execute("INSERT OR IGNORE INTO reviews(review_id, job_id, version, state, priority, suggested_category,"
               " proposal_sha256, created_at) VALUES(?,?,?,?,?,?,?,?)",
               (review_id_for(job_id), job_id, 1, PENDING, _priority(review), review.get("suggested_category"),
                fingerprint(review), now))


def iso(timestamp):
    """UTC time with milliseconds, for example ``2026-11-01T08:02:17.123Z``."""
    if timestamp is None:
        return None
    moment = datetime.fromtimestamp(timestamp, timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


class QueueStore:
    def __init__(self, path, *, timeout_s=10.0):
        self.path = Path(path)
        self.timeout_s = timeout_s

    # -- connections -------------------------------------------------------------------------

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=self.timeout_s, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute(f"PRAGMA busy_timeout={int(self.timeout_s * 1000)}")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA foreign_keys=ON")
            yield db
        finally:
            db.close()

    @contextmanager
    def _write(self):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")

    def migrate(self, now=None):
        """Create the tables, or upgrade a version-1 queue (no reviews yet) to version 2 and a version-2 queue (no
        handoffs yet) to version 3.

        The upgrade runs in one ``BEGIN IMMEDIATE`` transaction and re-reads the version inside it, so the API
        and the Runner may both call this at the same start: one upgrades, the other sees version 2. Every job
        that is already ``REVIEW_REQUIRED`` gets its ``PENDING`` review, so nothing waits without one.
        """
        now = time.time() if now is None else now
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(_SCHEMA)
        with self._write() as db:
            row = db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if row is None:
                version = str(SCHEMA_VERSION)
                db.execute("INSERT INTO meta(key, value) VALUES('schema_version', ?)", (version,))
            else:
                version = row["value"]
            if version == "1":
                self._upgrade_1_to_2(db, now)
                version = "2"
            if version == "2":  # the handoffs table was created above; nothing else changes
                db.execute("UPDATE meta SET value='3' WHERE key='schema_version'")
                version = "3"
            if version != str(SCHEMA_VERSION):
                raise RuntimeError(f"Queue database schema {version} is not supported (expected {SCHEMA_VERSION})")
            db.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('store_id', ?)", ("store_" + secrets.token_hex(8),))
            db.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('store_created_at', ?)", (repr(float(now)),))

    def _upgrade_1_to_2(self, db, now):
        rows = db.execute("SELECT job_id, result, finished_at FROM jobs WHERE status=? ORDER BY seq",
                          (REVIEW_REQUIRED,)).fetchall()
        for row in rows:
            review = (json.loads(row["result"]) if row["result"] else {}).get("review")
            if isinstance(review, dict):
                _insert_review(db, row["job_id"], review, row["finished_at"] or now)
        db.execute("UPDATE meta SET value='2' WHERE key='schema_version'")

    def store_info(self):
        """``{"id", "created_at"}`` of this queue database: a new id means it started empty again."""
        with self._connect() as db:
            rows = {row["key"]: row["value"] for row in
                    db.execute("SELECT key, value FROM meta WHERE key IN ('store_id', 'store_created_at')")}
        created = rows.get("store_created_at")
        return {"id": rows.get("store_id"), "created_at": iso(float(created)) if created else None}

    def ping(self):
        with self._connect() as db:
            db.execute("SELECT 1 FROM jobs LIMIT 1").fetchall()

    # -- rows --------------------------------------------------------------------------------

    @staticmethod
    def _job(row):
        if row is None:
            return None
        job = dict(row)
        for column in _JSON_COLUMNS:
            if job[column] is not None:
                job[column] = json.loads(job[column])
        return job

    @staticmethod
    def _event(db, job_id, kind, payload, now):
        db.execute("INSERT INTO job_events(job_id, kind, payload, at) VALUES(?,?,?,?)",
                   (job_id, kind, encode(payload).decode(), now))

    def _select(self, db, job_id):
        return self._job(db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone())

    # -- admission (API) ---------------------------------------------------------------------

    def admit(self, *, job_id, idempotency_key, request_fingerprint, workflow_type, input, max_queued,
              request_id=None, trace_parent=None, now=None):
        """Insert a QUEUED job, or return the job that already holds this idempotency key.

        Returns ``(job, created)``. The caller compares fingerprints for a reused key. ``request_id`` and
        ``trace_parent`` (the W3C ``traceparent`` of the admitting request's span, when tracing is on) go
        into the new job's ``job.queued`` event.
        """
        now = time.time() if now is None else now
        with self._write() as db:
            existing = db.execute("SELECT * FROM jobs WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if existing is not None:
                return self._job(existing), False
            waiting = db.execute("SELECT COUNT(*) FROM jobs WHERE status=?", (QUEUED,)).fetchone()[0]
            if waiting >= max_queued:
                raise QueueFull(waiting)
            queued = {"workflow_type": workflow_type}
            if request_id:
                queued["request_id"] = request_id
            if trace_parent:
                queued["trace_parent"] = trace_parent
            self._insert_job(db, job_id=job_id, idempotency_key=idempotency_key,
                             request_fingerprint=request_fingerprint, workflow_type=workflow_type, input=input,
                             queued=queued, now=now)
            return self._select(db, job_id), True

    def _insert_job(self, db, *, job_id, idempotency_key, request_fingerprint, workflow_type, input, queued, now):
        db.execute(
            "INSERT INTO jobs(job_id, idempotency_key, request_fingerprint, workflow_type, input, status,"
            " created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (job_id, idempotency_key, request_fingerprint, workflow_type, encode(input).decode(), QUEUED, now, now))
        self._event(db, job_id, "job.queued", queued, now)

    # -- handoffs (ADR-030) --------------------------------------------------------------------

    def _handoff(self, db, builder, job_id, decision, now):
        """Run the exchange's builder on the job's new record and write what it plans, in the caller's transaction."""
        if builder is None:
            return None
        job = self._select(db, job_id)
        row = db.execute("SELECT depth FROM handoffs WHERE target_job_id=?", (job_id,)).fetchone()
        plan = builder(job, decision=decision, depth=row["depth"] if row is not None else 0)
        if plan is None:
            return None
        if plan["state"] not in HANDOFF_STATES:
            raise ValueError(f"unknown handoff state {plan['state']}")
        target = plan.get("target") if plan["state"] == "STARTED" else None
        if target is not None:
            self._insert_job(db, job_id=target["job_id"], idempotency_key=target["idempotency_key"],
                             request_fingerprint=target["request_fingerprint"],
                             workflow_type=target["workflow_type"], input=target["input"],
                             queued={"workflow_type": target["workflow_type"], "handoff_id": plan["handoff_id"],
                                     "route_id": plan["route_id"], "from_job_id": job_id}, now=now)
        envelope = plan.get("envelope")
        db.execute(
            "INSERT INTO handoffs(handoff_id, route_id, routes_tag, vocabulary_tag, translator_out, translator_in,"
            " source_job_id, source_state, target_workflow_type, target_job_id, depth, state, reason, error_type,"
            " envelope, envelope_sha256, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (plan["handoff_id"], plan["route_id"], plan["routes_tag"], plan["vocabulary_tag"], plan["translator_out"],
             plan["translator_in"], job_id, job["status"], plan["target_workflow_type"],
             target["job_id"] if target else None, plan["depth"], plan["state"], plan.get("reason"),
             plan.get("error_type"), None if envelope is None else encode(envelope).decode(),
             None if envelope is None else fingerprint(envelope), now))
        # Ids and codes only: a fact value may be a person's words, so it never goes into an event.
        payload = {"handoff_id": plan["handoff_id"], "route_id": plan["route_id"]}
        if target is not None:
            self._event(db, job_id, "handoff.started", {**payload, "target_job_id": target["job_id"],
                                                        "target_workflow_type": target["workflow_type"]}, now)
        else:
            self._event(db, job_id, "handoff.refused", {**payload, "reason": plan.get("reason")}, now)
        return plan

    @staticmethod
    def _handoff_row(row):
        item = dict(row)
        item["envelope"] = json.loads(item["envelope"]) if item["envelope"] is not None else None
        return item

    def handoffs_from(self, job_id):
        """Every handoff this job started or that was refused, oldest first."""
        with self._connect() as db:
            rows = db.execute("SELECT * FROM handoffs WHERE source_job_id=? ORDER BY seq", (job_id,)).fetchall()
        return [self._handoff_row(row) for row in rows]

    def handoff_to(self, job_id):
        """The handoff that started this job, or ``None`` for a job admitted from outside."""
        with self._connect() as db:
            row = db.execute("SELECT * FROM handoffs WHERE target_job_id=?", (job_id,)).fetchone()
        return self._handoff_row(row) if row is not None else None

    def handoff_counts(self):
        with self._connect() as db:
            rows = db.execute("SELECT state, COUNT(*) AS n FROM handoffs GROUP BY state").fetchall()
        counts = {state: 0 for state in HANDOFF_STATES}
        counts.update({row["state"]: row["n"] for row in rows})
        return counts

    def cancel(self, job_id, *, request_id=None, now=None):
        """Withdraw a job the Runner has not claimed yet.

        Returns ``(job, changed)``: ``changed`` is False when the job was already cancelled. Raises
        :class:`StateError` for any other state, and ``KeyError`` for an unknown job. The check and the
        update run in one ``BEGIN IMMEDIATE`` transaction, like ``claim_next``, so a claim and a cancel
        of the same job can never both succeed.
        """
        now = time.time() if now is None else now
        with self._write() as db:
            row = db.execute("SELECT status FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row["status"] == CANCELLED:
                return self._select(db, job_id), False
            if row["status"] != QUEUED:
                raise StateError(row["status"])
            db.execute("UPDATE jobs SET status=?, finished_at=?, updated_at=? WHERE job_id=? AND status=?",
                       (CANCELLED, now, now, job_id, QUEUED))
            self._event(db, job_id, "job.cancelled", {"request_id": request_id} if request_id else {}, now)
            return self._select(db, job_id), True

    # -- Runner ------------------------------------------------------------------------------

    def claim_next(self, runner_id, now=None):
        """Move the oldest QUEUED job to RUNNING and return it (or ``None``)."""
        now = time.time() if now is None else now
        with self._write() as db:
            row = db.execute("SELECT job_id, claims FROM jobs WHERE status=? ORDER BY seq LIMIT 1",
                             (QUEUED,)).fetchone()
            if row is None:
                return None
            db.execute("UPDATE jobs SET status=?, claims=claims+1, runner_id=?, started_at=COALESCE(started_at, ?),"
                       " updated_at=? WHERE job_id=? AND status=?",
                       (RUNNING, runner_id, now, now, row["job_id"], QUEUED))
            self._event(db, row["job_id"], "job.claimed", {"claim": row["claims"] + 1}, now)
            return self._select(db, row["job_id"])

    def running_jobs(self):
        with self._connect() as db:
            rows = db.execute("SELECT * FROM jobs WHERE status=? ORDER BY seq", (RUNNING,)).fetchall()
        return [self._job(row) for row in rows]

    def reclaim(self, job_id, runner_id, now=None):
        """A new Runner takes over a job left RUNNING by a stopped one (counts as another claim)."""
        now = time.time() if now is None else now
        with self._write() as db:
            cursor = db.execute("UPDATE jobs SET claims=claims+1, runner_id=?, updated_at=? WHERE job_id=? AND status=?",
                                (runner_id, now, job_id, RUNNING))
            if cursor.rowcount != 1:
                raise StateError(f"{job_id} is not RUNNING")
            job = self._select(db, job_id)
            self._event(db, job_id, "job.recovering", {"claim": job["claims"]}, now)
            return job

    def freeze_spec(self, job_id, spec, now=None):
        """Record the exact Core spec once, before it is submitted. Recovery re-uses it unchanged."""
        now = time.time() if now is None else now
        data, digest = encode(spec).decode(), fingerprint(spec)
        with self._write() as db:
            row = db.execute("SELECT status, spec_fingerprint FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None or row["status"] != RUNNING:
                raise StateError(f"{job_id} is not RUNNING")
            if row["spec_fingerprint"] is None:
                db.execute("UPDATE jobs SET spec=?, spec_fingerprint=?, updated_at=? WHERE job_id=?",
                           (data, digest, now, job_id))
            elif row["spec_fingerprint"] != digest:
                raise StateError(f"{job_id} already has a different frozen spec")

    def finish(self, job_id, status, *, result=None, failure=None, step_events=(), handoff=None, now=None):
        """Record the Runner's outcome. ``handoff`` (the exchange's ``prepare``) runs in the same transaction."""
        if status not in TERMINAL:
            raise ValueError(f"{status} is not a final status")
        now = time.time() if now is None else now
        with self._write() as db:
            cursor = db.execute(
                "UPDATE jobs SET status=?, result=?, failure=?, finished_at=?, updated_at=? WHERE job_id=? AND status=?",
                (status, None if result is None else encode(result).decode(),
                 None if failure is None else encode(failure).decode(), now, now, job_id, RUNNING))
            if cursor.rowcount != 1:
                raise StateError(f"{job_id} is not RUNNING")
            for kind, payload in step_events:
                self._event(db, job_id, kind, payload, now)
            self._event(db, job_id, f"job.{status.lower()}",
                        {"reason": (failure or {}).get("reason")}, now)
            review = (result or {}).get("review")
            if status == REVIEW_REQUIRED and isinstance(review, dict):
                _insert_review(db, job_id, review, now)  # in the same transaction: no job waits without a review
            self._handoff(db, handoff, job_id, None, now)  # a route from COMPLETED starts its job in this commit

    def heartbeat(self, *, runner_id, pid, state, current_job=None, detail=None, llm=None, started_at, now=None):
        now = time.time() if now is None else now
        with self._write() as db:
            db.execute(
                "INSERT INTO runner(slot, runner_id, pid, state, current_job, detail, llm, started_at, heartbeat_at)"
                " VALUES(1,?,?,?,?,?,?,?,?) ON CONFLICT(slot) DO UPDATE SET runner_id=excluded.runner_id,"
                " pid=excluded.pid, state=excluded.state, current_job=excluded.current_job,"
                " detail=excluded.detail, llm=excluded.llm, started_at=excluded.started_at,"
                " heartbeat_at=excluded.heartbeat_at",
                (runner_id, pid, state, current_job, detail, None if llm is None else encode(llm).decode(),
                 started_at, now))

    # -- reads (API) ---------------------------------------------------------------------------

    def get(self, job_id):
        with self._connect() as db:
            return self._select(db, job_id)

    def queue_position(self, job):
        """1 for the next job to run. Only meaningful while the job is QUEUED."""
        with self._connect() as db:
            return db.execute("SELECT COUNT(*) FROM jobs WHERE status=? AND seq<=?",
                              (QUEUED, job["seq"])).fetchone()[0]

    def list_jobs(self, *, limit=20, before=None):
        """Newest first. Returns ``(jobs, next_before)``; ``next_before`` is ``None`` on the last page."""
        query, args = "SELECT * FROM jobs", []
        if before is not None:
            query, args = query + " WHERE seq<?", [before]
        with self._connect() as db:
            rows = db.execute(query + " ORDER BY seq DESC LIMIT ?", (*args, limit + 1)).fetchall()
        jobs = [self._job(row) for row in rows[:limit]]
        return jobs, (jobs[-1]["seq"] if len(rows) > limit else None)

    def events(self, job_id, *, after=0, limit=50):
        """Events after a cursor, oldest first. Returns ``(events, has_more)``."""
        with self._connect() as db:
            rows = db.execute("SELECT seq, kind, payload, at FROM job_events WHERE job_id=? AND seq>? ORDER BY seq LIMIT ?",
                              (job_id, after, limit + 1)).fetchall()
        events = [{"seq": row["seq"], "kind": row["kind"], "at": iso(row["at"]),
                   "payload": json.loads(row["payload"])} for row in rows[:limit]]
        return events, len(rows) > limit

    def admission(self, job_id):
        """The payload of the job's ``job.queued`` event (workflow type, and the request id and trace parent
        when they were recorded), or ``{}`` for an unknown job."""
        with self._connect() as db:
            row = db.execute("SELECT payload FROM job_events WHERE job_id=? AND kind='job.queued' ORDER BY seq LIMIT 1",
                             (job_id,)).fetchone()
        return json.loads(row["payload"]) if row is not None else {}

    def admitting_request_id(self, job_id):
        """The request id stored in the job's ``job.queued`` event, or ``None`` (older jobs have none)."""
        return self.admission(job_id).get("request_id")

    def counts(self):
        with self._connect() as db:
            rows = db.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status").fetchall()
        result = {status: 0 for status in STATUSES}
        result.update({row["status"]: row["n"] for row in rows})
        return result

    def waiting(self):
        """``(count, oldest_created_at)`` of the jobs still QUEUED; the time is ``None`` when none wait."""
        with self._connect() as db:
            row = db.execute("SELECT COUNT(*) AS n, MIN(created_at) AS oldest FROM jobs WHERE status=?",
                             (QUEUED,)).fetchone()
        return row["n"], row["oldest"]

    def recent_outcomes(self, limit):
        """The newest ``limit`` jobs that ran to an outcome, newest first (cancelled jobs never ran).

        Only what the run-time figures need: the workflow type, the outcome, the claim count, the three
        timestamps and the failure reason. Never the case text. ``NOT INDEXED`` makes SQLite walk the
        table backwards by ``seq`` and stop after ``limit`` rows, instead of sorting every finished job
        on each status request.
        """
        ran = TERMINAL + DECIDED  # a decided job ran to REVIEW_REQUIRED first
        marks = ",".join("?" * len(ran))
        with self._connect() as db:
            rows = db.execute(
                "SELECT workflow_type, status, claims, created_at, started_at, finished_at, failure"
                f" FROM jobs NOT INDEXED WHERE status IN ({marks}) ORDER BY seq DESC LIMIT ?",
                (*ran, limit)).fetchall()
        outcomes = []
        for row in rows:
            failure = json.loads(row["failure"]) if row["failure"] is not None else None
            outcomes.append({"workflow_type": row["workflow_type"], "status": row["status"], "claims": row["claims"],
                             "created_at": row["created_at"], "started_at": row["started_at"],
                             "finished_at": row["finished_at"],
                             "reason": failure.get("reason") if isinstance(failure, dict) else None})
        return outcomes

    def runner(self):
        with self._connect() as db:
            row = db.execute("SELECT * FROM runner WHERE slot=1").fetchone()
        if row is None:
            return None
        info = dict(row)
        info["llm"] = None if info["llm"] is None else json.loads(info["llm"])
        return info

    # -- reviews (API) -------------------------------------------------------------------------

    @staticmethod
    def _review(row):
        review = dict(row)
        for column in ("input", "result"):
            if column in review and review[column] is not None:
                review[column] = json.loads(review[column])
        return review

    _REVIEW_SELECT = ("SELECT r.*, j.workflow_type, j.input, j.status AS job_status,"
                      " CASE r.priority WHEN 'elevated' THEN 0 ELSE 1 END AS rank"
                      " FROM reviews r JOIN jobs j ON j.job_id = r.job_id")

    def list_reviews(self, *, state=PENDING, limit=20, after=None):
        """One page of reviews in one state. Returns ``(reviews, next_after)``; ``next_after`` is ``None`` on the
        last page and otherwise a ``(rank, seq)`` pair to pass back.

        ``PENDING``: elevated first, then the oldest (the order a reviewer should work in). ``APPROVED`` and
        ``REJECTED``: the newest first (rank is always 0 there)."""
        if state not in REVIEW_STATES:
            raise ValueError(f"unknown review state {state}")
        query, args = self._REVIEW_SELECT + " WHERE r.state=?", [state]
        if state == PENDING:
            if after is not None:
                query += " AND (rank > ? OR (rank = ? AND r.seq > ?))"
                args += [after[0], after[0], after[1]]
            query += " ORDER BY rank, r.seq"
        else:
            if after is not None:
                query += " AND r.seq < ?"
                args.append(after[1])
            query += " ORDER BY r.seq DESC"
        with self._connect() as db:
            rows = db.execute(query + " LIMIT ?", (*args, limit + 1)).fetchall()
        reviews = [self._review(row) for row in rows[:limit]]
        last = reviews[-1] if reviews else None
        next_after = None
        if len(rows) > limit and last is not None:
            next_after = (last["rank"] if state == PENDING else 0, last["seq"])
        return reviews, next_after

    def get_review(self, review_id):
        """The review with its job's input and result, and every decision on it (oldest first), or ``None``."""
        with self._connect() as db:
            row = db.execute(self._REVIEW_SELECT.replace("j.input,", "j.input, j.result,") + " WHERE r.review_id=?",
                             (review_id,)).fetchone()
            if row is None:
                return None
            review = self._review(row)
            review["decisions"] = [dict(item) for item in db.execute(
                "SELECT * FROM review_decisions WHERE review_id=? ORDER BY seq", (review_id,)).fetchall()]
        return review

    def review_of_job(self, job_id):
        """The job's review with its latest decision (``None`` before any), or ``None`` for a job without one."""
        with self._connect() as db:
            row = db.execute("SELECT * FROM reviews WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                return None
            review = dict(row)
            latest = db.execute("SELECT * FROM review_decisions WHERE review_id=? ORDER BY seq DESC LIMIT 1",
                                (review["review_id"],)).fetchone()
        review["decision"] = dict(latest) if latest is not None else None
        return review

    def review_counts(self):
        """``{"PENDING": n, "APPROVED": n, "REJECTED": n, "elevated_pending": n}``."""
        with self._connect() as db:
            rows = db.execute("SELECT state, COUNT(*) AS n, SUM(priority='elevated') AS elevated FROM reviews"
                              " GROUP BY state").fetchall()
        counts = {state: 0 for state in REVIEW_STATES}
        counts["elevated_pending"] = 0
        for row in rows:
            counts[row["state"]] = row["n"]
            if row["state"] == PENDING:
                counts["elevated_pending"] = row["elevated"] or 0
        return counts

    def decide(self, review_id, *, decision, final_category, reason, expected_version, idempotency_key,
               request_sha256, reviewer_token_id, reviewer_role, request_id=None, handoff=None, now=None):
        """Record a person's decision. Returns ``(decision_row, created)``.

        One ``BEGIN IMMEDIATE`` transaction: the decision row, the review's new state and version, the job's new
        state and its event, and (with ``handoff``, the exchange's ``prepare``) the handoff that the new state
        starts, all or nothing. The idempotency key is checked first, so a retried click returns the
        same decision (``created`` False) even after the review is decided. Raises ``KeyError`` for an unknown
        review and :class:`DecisionConflict` when the key was used for another request, the review is already
        decided, or ``expected_version`` is not the current version.
        """
        if decision not in DECISION_STATE:
            raise ValueError(f"unknown decision {decision}")
        now = time.time() if now is None else now
        with self._write() as db:
            existing = db.execute("SELECT * FROM review_decisions WHERE idempotency_key=?",
                                  (idempotency_key,)).fetchone()
            if existing is not None:
                if existing["review_id"] != review_id or existing["request_sha256"] != request_sha256:
                    raise DecisionConflict("idempotency_conflict")
                return dict(existing), False
            review = db.execute("SELECT * FROM reviews WHERE review_id=?", (review_id,)).fetchone()
            if review is None:
                raise KeyError(review_id)
            if review["state"] != PENDING:
                raise DecisionConflict("already_decided", review_state=review["state"], version=review["version"])
            if expected_version != review["version"]:
                raise DecisionConflict("version_conflict", version=review["version"])
            decision_id = "dec_" + secrets.token_hex(12)
            state = DECISION_STATE[decision]
            db.execute("INSERT INTO review_decisions(decision_id, review_id, version, reviewer_token_id, reviewer_role,"
                       " decision, final_category, reason, idempotency_key, request_sha256, request_id, created_at)"
                       " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (decision_id, review_id, review["version"], reviewer_token_id, reviewer_role, decision,
                        final_category, reason, idempotency_key, request_sha256, request_id, now))
            moved = db.execute("UPDATE reviews SET state=?, version=version+1, decided_at=? WHERE review_id=?"
                               " AND state=? AND version=?", (state, now, review_id, PENDING, review["version"]))
            job = db.execute("UPDATE jobs SET status=?, updated_at=? WHERE job_id=? AND status=?",
                             (state, now, review["job_id"], REVIEW_REQUIRED))
            if moved.rowcount != 1 or job.rowcount != 1:
                raise StateError(f"{review['job_id']} is not waiting for review")  # rolls the whole decision back
            # The event names the decision, never the reason: a reason is free text and could repeat the case.
            payload = {"review_id": review_id, "decision_id": decision_id, "version": review["version"],
                       "decision": decision, "final_category": final_category, "reviewer_role": reviewer_role}
            if request_id:
                payload["request_id"] = request_id
            self._event(db, review["job_id"], f"review.{state.lower()}", payload, now)
            row = db.execute("SELECT * FROM review_decisions WHERE decision_id=?", (decision_id,)).fetchone()
            self._handoff(db, handoff, review["job_id"], dict(row), now)  # an approval's route, in this commit
            return dict(row), True
