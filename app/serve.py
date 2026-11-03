"""Start the whole service in one container: the HTTP API in this process, and the single Runner as
a supervised child process. In the image (used by Render and Railway), ``app.boot`` prepares the data
folder, drops root and starts tini, which runs ``python -m app.serve`` as the ``neuron`` user.

Steps:
1. read the settings (data folder, port, access key) from the environment;
2. when started as root directly (not through ``app.boot``), give the data folder to the unprivileged
   ``neuron`` user from the image and drop root before anything else runs;
3. create the queue database;
4. start the Runner; if it stops unexpectedly, start it again after a short pause (its
   reconciliation then finishes any interrupted job);
5. serve HTTP until SIGTERM, then ask the Runner to stop after its current job;
6. with tracing on (``HONEYCOMB_API_KEY``), send the spans that are still queued before exiting.
"""

import logging
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from app.api import ApiApp, make_server
from app.boot import RUN_AS, drop_privileges, prepare_data_folders
from app.observability import SentryReporter, Tracing, init_sentry
from app.persistence import QueueStore
from app.settings import Settings

RESTART_DELAYS_S = (1, 2, 5, 10, 30)
STOP_GRACE_S = 25
log = logging.getLogger("neuron_flow.serve")


class RunnerSupervisor:
    """Keep exactly one Runner child alive while the service runs."""

    def __init__(self, command=None):
        self.command = command or [sys.executable, "-m", "app.services.runner"]
        self.process = None
        self._stopping = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="runner-supervisor", daemon=True)

    def start(self):
        self._thread.start()

    def _loop(self):
        failures = 0
        while not self._stopping.is_set():
            started = time.monotonic()
            self.process = subprocess.Popen(self.command, cwd=Path(__file__).resolve().parent.parent)
            code = self.process.wait()
            if self._stopping.is_set():
                return
            quick = time.monotonic() - started < 60  # crashing again soon after a start: wait longer
            failures = failures + 1 if quick else 0
            delay = RESTART_DELAYS_S[min(failures, len(RESTART_DELAYS_S) - 1)]
            log.warning("serve: the Runner exited (code %s); starting it again in %ss", code, delay)
            self._stopping.wait(delay)

    def stop(self, grace_s=STOP_GRACE_S):
        self._stopping.set()
        process = self.process
        if process is not None and process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(grace_s)
            except subprocess.TimeoutExpired:
                log.warning("serve: the Runner did not stop in %ss; stopping it now (it will be reconciled)", grace_s)
                process.kill()
                process.wait()
        self._thread.join(timeout=5)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    settings = Settings.from_env()
    prepare_data_folders(settings)
    if drop_privileges(settings.data_dir):
        log.info("serve: running as the '%s' user", RUN_AS)
    store = QueueStore(settings.queue_db)
    store.migrate()
    sentry_active = init_sentry()
    tracing = Tracing.from_env("api")
    if tracing.enabled:
        log.info("serve: tracing on: spans go to %s as service %s", tracing.destination, tracing.service_name)
    elif tracing.problem != "not_configured":
        log.warning("serve: tracing is off (%s)", tracing.problem)
    if settings.access_key is None:
        log.warning("serve: NEURON_FLOW_ACCESS_KEY is %s; the API refuses every /v1 request until it is set",
                    settings.access_key_problem)
    if not settings.persistent:
        log.warning("serve: no persistent storage configured; jobs are lost when the container restarts")
    supervisor = RunnerSupervisor()
    supervisor.start()
    server = make_server(settings, ApiApp(settings, store, reporter=SentryReporter() if sentry_active else None,
                                          tracing=tracing))

    def shutdown(signum, _frame):
        log.info("serve: stopping (signal %d)", signum)
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    log.info("serve: listening on %s:%d (storage=%s)", settings.host, settings.port, settings.storage)
    try:
        server.serve_forever()
    finally:
        supervisor.stop()
        server.server_close()
        tracing.shutdown()  # at most two seconds, inside the host's stop window (render.yaml)
    return 0


if __name__ == "__main__":
    sys.exit(main())
