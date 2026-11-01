"""Settings for the intake API, the job queue and the Runner, read from the environment.

Where data lives (the first one set wins):
1. ``NEURON_FLOW_DATA_DIR``: an explicit folder;
2. ``RAILWAY_VOLUME_MOUNT_PATH``: set by Railway when a volume is attached to the service;
3. ``./neuron_workspace``: local default. Inside a container this is NOT persistent.

Inside the data folder: ``core/`` is the Core workspace (only the Runner opens it) and
``app/queue.sqlite3`` is the application queue.

``NEURON_FLOW_ACCESS_KEY`` is kept in memory only, to check request headers. It is never written
to disk, a job, a log line or a response, and it is hidden from ``repr``.
"""

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Optional

MIN_ACCESS_KEY_LENGTH = 16
DEFAULT_PORT = 8000


class SettingsError(ValueError):
    """An environment variable has a value the service cannot use."""


def _bounded_int(env, name, default, low, high):
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise SettingsError(f"{name} must be a whole number") from None
    if not low <= value <= high:
        raise SettingsError(f"{name} must be between {low} and {high}")
    return value


def _bounded_float(env, name, default, low, high):
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise SettingsError(f"{name} must be a number") from None
    if not low <= value <= high:
        raise SettingsError(f"{name} must be between {low} and {high}")
    return value


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    storage: str = "configured"           # configured | railway_volume | local_default
    host: str = "0.0.0.0"
    port: int = DEFAULT_PORT
    access_key: Optional[str] = field(default=None, repr=False)
    access_key_problem: Optional[str] = None   # missing | too_short
    max_queued: int = 100                 # admission refuses new jobs above this many waiting
    submit_per_minute: int = 30           # admission rate, per client and in total
    max_connections: int = 32             # concurrent HTTP connections
    runner_workers: int = 2               # Core child processes (the v2 DAG has two parallel steps)
    runner_poll_s: float = 0.5            # how often an idle Runner looks for work
    max_claims: int = 3                   # a job that crashed the Runner this many times is failed
    runner_stale_s: float = 15.0          # heartbeat older than this means the Runner is not alive

    @property
    def core_dir(self):
        return self.data_dir / "core"

    @property
    def queue_db(self):
        return self.data_dir / "app" / "queue.sqlite3"

    @property
    def persistent(self):
        return self.storage != "local_default"

    @classmethod
    def from_env(cls, environ=None):
        env = os.environ if environ is None else environ
        explicit = env.get("NEURON_FLOW_DATA_DIR", "").strip()
        volume = env.get("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
        if explicit:
            data_dir, storage = Path(explicit), "configured"
        elif volume:
            data_dir, storage = Path(volume), "railway_volume"
        else:
            data_dir, storage = Path("neuron_workspace"), "local_default"
        key = env.get("NEURON_FLOW_ACCESS_KEY", "").strip()
        problem = None
        if not key:
            key, problem = None, "missing"
        elif len(key) < MIN_ACCESS_KEY_LENGTH:
            key, problem = None, "too_short"
        return cls(
            data_dir=data_dir.resolve(), storage=storage,
            host=env.get("NEURON_FLOW_HOST", "").strip() or "0.0.0.0",
            port=_bounded_int(env, "PORT", DEFAULT_PORT, 1, 65535),
            access_key=key, access_key_problem=problem,
            max_queued=_bounded_int(env, "NEURON_FLOW_MAX_QUEUED", 100, 1, 10000),
            submit_per_minute=_bounded_int(env, "NEURON_FLOW_SUBMIT_PER_MINUTE", 30, 1, 6000),
            max_connections=_bounded_int(env, "NEURON_FLOW_MAX_CONNECTIONS", 32, 1, 512),
            runner_workers=_bounded_int(env, "NEURON_FLOW_RUNNER_WORKERS", 2, 1, 8),
            runner_poll_s=_bounded_float(env, "NEURON_FLOW_RUNNER_POLL_S", 0.5, 0.05, 30),
            max_claims=_bounded_int(env, "NEURON_FLOW_MAX_CLAIMS", 3, 1, 10),
        )
