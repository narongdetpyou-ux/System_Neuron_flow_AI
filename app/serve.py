"""Start the whole service in one container: the HTTP API in this process, and the single Runner as
a supervised child process. Railway (and the Dockerfile) run ``python -m app.serve``.

Steps:
1. read the settings (data folder, port, access key) from the environment;
2. when started as root (Railway mounts volumes as root), give the data folder to the unprivileged
   ``neuron`` user from the image and drop root before anything else runs;
3. create the queue database;
4. start the Runner; if it stops unexpectedly, start it again after a short pause (its
   reconciliation then finishes any interrupted job);
5. serve HTTP until SIGTERM, then ask the Runner to stop after its current job.
"""

import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from app.api import ApiApp, make_server
from app.observability import SentryReporter, init_sentry
from app.persistence import QueueStore
from app.settings import Settings

RUN_AS = "neuron"
RESTART_DELAYS_S = (1, 2, 5, 10, 30)
STOP_GRACE_S = 25
log = logging.getLogger("neuron_flow.serve")


def drop_privileges(data_dir, user=RUN_AS):
    """If running as root and the image's service user exists, hand it the data folder and switch to it."""
    if os.name != "posix" or os.geteuid() != 0:
        return False
    import pwd
    try:
        entry = pwd.getpwnam(user)
    except KeyError:
        return False  # root outside our image (for example a developer machine): leave it alone
    for folder, directories, files in os.walk(data_dir):
        for name in [folder, *(os.path.join(folder, item) for item in directories + files)]:
            os.chown(name, entry.pw_uid, entry.pw_gid, follow_symlinks=False)
    os.setgroups([])
    os.setgid(entry.pw_gid)
    os.setuid(entry.pw_uid)
    os.environ["HOME"] = "/tmp"
    return True


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
    for folder in (settings.core_dir, settings.queue_db.parent):
        folder.mkdir(parents=True, exist_ok=True)
    if drop_privileges(settings.data_dir):
        log.info("serve: running as the '%s' user", RUN_AS)
    store = QueueStore(settings.queue_db)
    store.migrate()
    sentry_active = init_sentry()
    if settings.access_key is None:
        log.warning("serve: NEURON_FLOW_ACCESS_KEY is %s; the API refuses every /v1 request until it is set",
                    settings.access_key_problem)
    if not settings.persistent:
        log.warning("serve: no persistent storage configured; jobs are lost when the container restarts")
    supervisor = RunnerSupervisor()
    supervisor.start()
    server = make_server(settings, ApiApp(settings, store, reporter=SentryReporter() if sentry_active else None))

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
    return 0


if __name__ == "__main__":
    sys.exit(main())
