"""The single Runner: the only process that opens the Core ``Runtime`` (ADR-001).

What it does, in order:
1. opens ``Runtime`` on ``<data>/core``. That takes the workspace lock, so a second Runner fails
   fast with ``WorkspaceBusy`` instead of running the same jobs twice;
2. reconciles. A job that the queue still shows as RUNNING was interrupted: the previous Runner
   stopped. The Runner re-submits the exact spec frozen at the first claim and runs it. Core
   retries the interrupted step, and that retry counts against the step's ``max_attempts`` (its
   retry budget). Two cases fail instead of running: a job already claimed ``max_claims`` times
   (so one bad job cannot crash the Runner forever), and a job whose spec would now be built
   differently because the model, prompt or code changed while it was interrupted
   (``configuration_changed``: it is never finished silently under other settings);
3. claims the oldest QUEUED job, freezes its spec, submits and runs it, and records the outcome;
4. writes a heartbeat every few seconds, shown on the status page;
5. with tracing on, turns each finished job into spans (``app.observability.job_spans``) and hands them to
   the exporter. Building or sending a trace can never change a job's outcome.

If the AI settings cannot work (for example ``anthropic`` without an API key), the Runner starts no
jobs. It stays up, reports ``blocked_config`` with the reason, and queued jobs wait until the
settings are fixed. Nothing is dropped.

Run it with ``python -m app.services.runner``; ``python -m app.serve`` starts it for you.
"""

from contextlib import contextmanager
import logging
import os
import secrets
import signal
import sys
import threading
import time

from neuron_flow import Runtime
from neuron_flow.model import fingerprint
from neuron_flow.storage import WorkspaceBusy

from app.llm import LLMConfig, LLMConfigError
from app.observability import SentryReporter, Tracing, init_sentry, job_spans, run_job
from app.persistence import TERMINAL, QueueStore
from app.settings import Settings

from .results import AI_STEP, CORE_FINAL, step_events, summarize
from .workflows import CATALOG, agents_for

HEARTBEAT_S = 2.0
EXIT_BUSY = 3
log = logging.getLogger("neuron_flow.runner")


def _with_core_versions(runtime, job_id, spec):
    """The frozen spec with the agent versions Core recorded when it accepted the job.

    Core adds ``agent_versions`` to its own copy of the spec on submit; the queue keeps the spec as the
    Runner built it, without them. Only the trace reads this. When Core never saw the job, or its copy
    cannot be read, the queue's spec is returned unchanged and the step spans carry no version.
    """
    try:
        versions = runtime.store.job(job_id)["spec"].get("agent_versions")
    except Exception:  # KeyError: Core never saw the job; anything else: the trace must not fail
        return spec
    return dict(spec, agent_versions=versions) if isinstance(versions, dict) else spec


class Runner:
    def __init__(self, settings, *, store=None, catalog=None, llm_config=None, reporter=None, tracing=None):
        self.settings = settings
        self.store = store or QueueStore(settings.queue_db)
        self.catalog = CATALOG if catalog is None else catalog
        self.llm_config = llm_config
        self.reporter = reporter or SentryReporter()
        self.tracing = tracing if tracing is not None else Tracing.off()
        self.runner_id = f"runner-{os.getpid()}-{secrets.token_hex(3)}"
        self.started_at = time.time()
        self.stop_event = threading.Event()
        self._lock = threading.Lock()
        self._status = {"state": "starting", "current_job": None, "detail": None}
        self._llm = None

    # -- entry points --------------------------------------------------------------------------

    def serve(self):
        """Run until ``stop_event`` is set. Raises ``WorkspaceBusy`` if another Runner owns the workspace."""
        self.store.migrate()
        try:
            config, agents = self._prepare()
        except LLMConfigError as exc:
            log.error("runner: not starting jobs, the AI settings cannot work: %s", exc)
            with self._heartbeat():
                self._set("blocked_config", detail=str(exc)[:300])
                self.stop_event.wait()
            return
        # The workspace lock comes first: a Runner that cannot get it never writes a heartbeat,
        # so it cannot overwrite the status of the Runner that is working.
        with Runtime(self.settings.core_dir, agents=agents,
                     max_workers=self.settings.runner_workers) as runtime, self._heartbeat():
            log.info("runner: started (ai=%s/%s, storage=%s)", config.provider, config.model, self.settings.storage)
            self.reconcile(runtime, config)
            self._set("idle")
            while not self.stop_event.is_set():
                if not self.process_next(runtime, config):
                    self.stop_event.wait(self.settings.runner_poll_s)

    def drain(self):
        """Reconcile, then run queued jobs until none are left. Returns how many were claimed."""
        self.store.migrate()
        config, agents = self._prepare()
        with Runtime(self.settings.core_dir, agents=agents, max_workers=self.settings.runner_workers) as runtime:
            self.reconcile(runtime, config)
            processed = 0
            while self.process_next(runtime, config):
                processed += 1
        self._set("stopped")
        return processed

    # -- the work ------------------------------------------------------------------------------

    def _prepare(self):
        """Freeze the AI settings for this Runner and build the trusted agent registry."""
        config = self.llm_config or LLMConfig.from_env()
        agents = agents_for(self.catalog, config)  # a real provider without a key fails here
        self._llm = {"provider": config.provider, "model": config.model}
        return config, agents

    def reconcile(self, runtime, config):
        self._set("reconciling")
        for job in self.store.running_jobs():
            if job["claims"] >= self.settings.max_claims:
                log.warning("runner: %s interrupted the Runner %d times; marking it failed", job["job_id"], job["claims"])
                self.store.finish(job["job_id"], "FAILED",
                                  failure={"reason": "runner_attempts_exhausted", "claims": job["claims"]})
                self.reporter.report_recovery(job["job_id"], outcome="runner_attempts_exhausted", claims=job["claims"])
                continue
            job = self.store.reclaim(job["job_id"], self.runner_id)
            log.info("runner: recovering %s (claim %d)", job["job_id"], job["claims"])
            self.reporter.report_recovery(job["job_id"], outcome="resumed", claims=job["claims"])
            self._process(runtime, config, job, recovering=True)

    def process_next(self, runtime, config):
        job = self.store.claim_next(self.runner_id)
        if job is None:
            return False
        self._process(runtime, config, job, recovering=False)
        return True

    def _process(self, runtime, config, job, *, recovering):
        job_id = job["job_id"]
        self._set("running", current_job=job_id)
        started = time.monotonic()
        try:
            workflow = self.catalog.get(job["workflow_type"])
            if workflow is None:
                self.store.finish(job_id, "FAILED", failure={"reason": "unknown_workflow_type"})
                return
            spec = job["spec"]
            current = workflow.build_spec(job_id, job["input"], config)
            if spec is None:
                spec = current
                self.store.freeze_spec(job_id, spec)  # recorded before Core ever sees it
            elif fingerprint(spec) != fingerprint(current):
                # Interrupted, and the settings (model, prompt, code) changed before this restart.
                # Never finish it silently under settings it was not admitted with.
                self._configuration_changed(job, "SpecChanged")
                return
            try:
                runtime.submit(spec)  # the same spec again is a no-op, so recovery may repeat it
            except ValueError as exc:
                # The frozen spec no longer matches the registered agents (model, prompt or agent
                # changed after admission). Never re-run it silently with the new settings.
                self._configuration_changed(job, type(exc).__name__)
                return
            snapshot = runtime.status(job_id)
            if not (recovering and snapshot["status"] in CORE_FINAL):
                try:
                    snapshot = run_job(runtime, job_id, self.reporter)  # also reports failures to Sentry
                except ValueError as exc:  # SpecError: "Agent version changed" or "no longer registered"
                    self._configuration_changed(job, type(exc).__name__)
                    return
            status, result, failure = summarize(snapshot, spec, workflow)
            self.store.finish(job_id, status, result=result, failure=failure, step_events=step_events(result))
            log.info("runner: %s %s in %.1fs", job_id, status, time.monotonic() - started)
        except Exception as exc:
            log.exception("runner: unexpected error on %s", job_id)
            self.reporter.capture_exception(exc, job_id=job_id)
            try:
                self.store.finish(job_id, "FAILED", failure={"reason": "runtime_error", "error_type": type(exc).__name__})
            except Exception:
                log.exception("runner: could not record the failure of %s; it will be reconciled", job_id)
        finally:
            self._trace(runtime, job_id)
            self._set("idle")

    def _trace(self, runtime, job_id):
        """Hand the spans of a job that has an outcome to the exporter. Off: nothing is read at all."""
        if not self.tracing.enabled:
            return
        try:
            job = self.store.get(job_id)
            if job is None or job["status"] not in TERMINAL:
                return  # not recorded yet (it will be reconciled, and traced then)
            events = []
            if job["spec"] is not None:
                events = runtime.synapse.events_for("monitor", job_id)
                job = dict(job, spec=_with_core_versions(runtime, job_id, job["spec"]))
            self.tracing.export(job_spans(job, self.store.admission(job_id), events, ai_step=AI_STEP))
        except Exception as exc:  # tracing never changes a job; only the type is logged, never a message
            log.warning("runner: could not build the trace of %s (%s)", job_id, type(exc).__name__)

    def _configuration_changed(self, job, error_type):
        log.warning("runner: %s was admitted under other settings; failing it instead of re-running it", job["job_id"])
        self.store.finish(job["job_id"], "FAILED", failure={"reason": "configuration_changed", "error_type": error_type})
        self.reporter.report_recovery(job["job_id"], outcome="configuration_changed", claims=job["claims"])

    # -- heartbeat -----------------------------------------------------------------------------

    @contextmanager
    def _heartbeat(self):
        beat = threading.Thread(target=self._heartbeat_loop, name="runner-heartbeat", daemon=True)
        beat.start()
        try:
            yield
        finally:
            self.stop_event.set()
            beat.join(timeout=HEARTBEAT_S + 1)
            self._set("stopped")

    def _set(self, state, *, current_job=None, detail=None):
        with self._lock:
            self._status = {"state": state, "current_job": current_job, "detail": detail}
        self._beat()

    def _beat(self):
        with self._lock:
            status = dict(self._status)
        try:
            self.store.heartbeat(runner_id=self.runner_id, pid=os.getpid(), started_at=self.started_at,
                                 llm=self._llm, **status)
        except Exception:  # the status page is informational; never let it stop the work
            log.debug("runner: heartbeat not written", exc_info=True)

    def _heartbeat_loop(self):
        while not self.stop_event.wait(HEARTBEAT_S):
            self._beat()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    settings = Settings.from_env()
    init_sentry()  # no-op unless SENTRY_DSN is set and sentry-sdk is installed
    tracing = Tracing.from_env("runner")  # off unless HONEYCOMB_API_KEY is set
    runner = Runner(settings, tracing=tracing)

    def stop(signum, _frame):
        log.info("runner: stopping after the current job (signal %d)", signum)
        runner.stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        runner.serve()
    except WorkspaceBusy:
        log.error("runner: another Runner holds the workspace lock; exiting")
        return EXIT_BUSY
    finally:
        tracing.shutdown()  # sends what is queued, for at most two seconds
    return 0


if __name__ == "__main__":
    sys.exit(main())
