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

(review decisions on REVIEW_REQUIRED jobs come with Milestone C.)
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time

from neuron_flow.model import encode, fingerprint

SCHEMA_VERSION = 1
QUEUED, RUNNING, CANCELLED = "QUEUED", "RUNNING", "CANCELLED"
TERMINAL = ("REVIEW_REQUIRED", "COMPLETED", "FAILED", "DELIVERY_FAILED")  # the outcomes the Runner records
STATUSES = (QUEUED, RUNNING) + TERMINAL + (CANCELLED,)
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
"""


class QueueFull(Exception):
    """Admission refused: too many jobs are already waiting."""


class StateError(RuntimeError):
    """A queue transition that the current job state does not allow."""


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

    def migrate(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(_SCHEMA)
            db.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
            version = db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()["value"]
        if version != str(SCHEMA_VERSION):
            raise RuntimeError(f"Queue database schema {version} is not supported (expected {SCHEMA_VERSION})")

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
              request_id=None, now=None):
        """Insert a QUEUED job, or return the job that already holds this idempotency key.

        Returns ``(job, created)``. The caller compares fingerprints for a reused key.
        """
        now = time.time() if now is None else now
        with self._write() as db:
            existing = db.execute("SELECT * FROM jobs WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if existing is not None:
                return self._job(existing), False
            waiting = db.execute("SELECT COUNT(*) FROM jobs WHERE status=?", (QUEUED,)).fetchone()[0]
            if waiting >= max_queued:
                raise QueueFull(waiting)
            db.execute(
                "INSERT INTO jobs(job_id, idempotency_key, request_fingerprint, workflow_type, input, status,"
                " created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (job_id, idempotency_key, request_fingerprint, workflow_type, encode(input).decode(), QUEUED,
                 now, now))
            queued = {"workflow_type": workflow_type}
            if request_id:
                queued["request_id"] = request_id
            self._event(db, job_id, "job.queued", queued, now)
            return self._select(db, job_id), True

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

    def finish(self, job_id, status, *, result=None, failure=None, step_events=(), now=None):
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

    def admitting_request_id(self, job_id):
        """The request id stored in the job's ``job.queued`` event, or ``None`` (older jobs have none)."""
        with self._connect() as db:
            row = db.execute("SELECT payload FROM job_events WHERE job_id=? AND kind='job.queued' ORDER BY seq LIMIT 1",
                             (job_id,)).fetchone()
        return json.loads(row["payload"]).get("request_id") if row is not None else None

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
        marks = ",".join("?" * len(TERMINAL))
        with self._connect() as db:
            rows = db.execute(
                "SELECT workflow_type, status, claims, created_at, started_at, finished_at, failure"
                f" FROM jobs NOT INDEXED WHERE status IN ({marks}) ORDER BY seq DESC LIMIT ?",
                (*TERMINAL, limit)).fetchall()
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
