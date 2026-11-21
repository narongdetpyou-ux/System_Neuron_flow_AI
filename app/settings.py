"""Settings for the intake API, the job queue and the Runner, read from the environment.

Where data lives (the first one set wins):
1. ``NEURON_FLOW_DATA_DIR``: an explicit folder, such as the mount path of a Render disk;
2. ``RAILWAY_VOLUME_MOUNT_PATH``: set by Railway when a volume is attached to the service;
3. ``./neuron_workspace``: local default. Inside a container this is NOT persistent.

Whether the data outlives a restart is checked, not assumed (roadmap 1.7, ADR-036). A configured folder counts as
persistent only when the start finds it, in this process's mount table (``/proc/self/mountinfo``), on a filesystem
mounted on its own that is neither the root filesystem nor one that lives in the container's layers or in memory
(``overlay``, ``aufs``, ``tmpfs``, ``ramfs``, ``devtmpfs``). A wrong path or a disk that is not attached
therefore reads as temporary, and the page never says "ถาวร" for it. The check is conservative: a folder on the
root disk of a machine that is not a container reads as not confirmed too.

Inside the data folder: ``core/`` is the Core workspace (only the Runner opens it) and
``app/queue.sqlite3`` is the application queue.

``NEURON_FLOW_ACCESS_KEY`` is kept in memory only, to check request headers. It is never written
to disk, a job, a log line or a response, and it is hidden from ``repr``.
"""

from dataclasses import dataclass, field
import os
from pathlib import Path, PurePosixPath
import re
from typing import Optional

MIN_ACCESS_KEY_LENGTH = 16
DEFAULT_PORT = 8000
MOUNTINFO = Path("/proc/self/mountinfo")
# Filesystems that do not outlive the container: its own layers, or memory.
TEMPORARY_FILESYSTEMS = frozenset({"overlay", "aufs", "tmpfs", "ramfs", "devtmpfs"})
# Every result a storage check can give; the page has Thai words for each one that is not "confirmed".
STORAGE_CHECK_RESULTS = ("confirmed", "not_configured", "not_checked", "root_filesystem", "temporary_filesystem",
                         "mount_table_unreadable")
_OCTAL_ESCAPE = re.compile(r"\\([0-7]{3})")
_FILESYSTEM_NAME = re.compile(r"^[A-Za-z0-9._-]{1,40}$")


class SettingsError(ValueError):
    """An environment variable has a value the service cannot use."""


@dataclass(frozen=True)
class StorageCheck:
    """What the start found about the data folder (roadmap 1.7). ``result`` is one of:

    * ``confirmed``: on a filesystem mounted on its own that is not temporary; ``filesystem`` names its type;
    * ``not_configured``: the local default folder, so nothing was read;
    * ``not_checked``: no check ran (settings built by hand), so it is never called persistent;
    * ``root_filesystem``: the folder sits on the root filesystem (in a container, the container's own layer);
    * ``temporary_filesystem``: the mount that holds it lives in the container's layers or in memory;
    * ``mount_table_unreadable``: there is no mount table to read (not Linux, or no ``/proc``).
    """
    result: str
    filesystem: Optional[str] = None   # the type of the mount that holds the folder: ext4, overlay, tmpfs, ...

    @property
    def confirmed(self):
        return self.result == "confirmed"


NOT_CHECKED = StorageCheck("not_checked")
NOT_CONFIGURED = StorageCheck("not_configured")


def _unescape(text):
    """The kernel writes a space, tab, newline or backslash in a mount point as an octal escape (``\\040``)."""
    return _OCTAL_ESCAPE.sub(lambda match: chr(int(match.group(1), 8)), text)


def parse_mountinfo(text):
    """``[(mount_point, filesystem_type)]`` from the text of ``/proc/<pid>/mountinfo``, in file order.

    A line is ``id parent major:minor root mount_point options [optional fields ...] - type source super_options``
    (proc(5)); the optional fields end at a lone ``-``. A line that does not fit is skipped.
    """
    mounts = []
    for line in text.splitlines():
        fields = line.split(" ")
        try:
            separator = fields.index("-", 6)  # id, parent, device, root, mount point and options come first
        except ValueError:
            continue
        if separator + 1 < len(fields) and fields[4].startswith("/"):
            mounts.append((_unescape(fields[4]), fields[separator + 1]))
    return mounts


def check_storage(data_dir, mountinfo=None):
    """Whether ``data_dir`` sits on a filesystem of its own that outlives the container (see the module docstring).

    The mount that holds the folder is the longest mount point that contains it, compared by path components (so
    ``/var/data2`` is not inside ``/var/data``); of two equal mount points the later line wins, because it is mounted
    on top. ``mountinfo`` is the text of a mount table, for tests; ``None`` reads this process's own.
    """
    if mountinfo is None:
        try:
            mountinfo = MOUNTINFO.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return StorageCheck("mount_table_unreadable")
    parts = PurePosixPath(data_dir).parts
    best = None
    for mount_point, filesystem in parse_mountinfo(mountinfo):
        held = PurePosixPath(mount_point).parts
        if parts[:len(held)] == held and (best is None or len(held) >= len(best[0])):
            best = (held, filesystem)
    if best is None:
        return StorageCheck("mount_table_unreadable")
    held, filesystem = best
    filesystem = filesystem if _FILESYSTEM_NAME.fullmatch(filesystem) else "other"
    if len(held) == 1:  # the mount point is "/"
        return StorageCheck("root_filesystem", filesystem)
    if filesystem in TEMPORARY_FILESYSTEMS:
        return StorageCheck("temporary_filesystem", filesystem)
    return StorageCheck("confirmed", filesystem)


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
    storage_check: StorageCheck = NOT_CHECKED  # what the start found about the data folder (roadmap 1.7)

    @property
    def core_dir(self):
        return self.data_dir / "core"

    @property
    def queue_db(self):
        return self.data_dir / "app" / "queue.sqlite3"

    @property
    def persistent(self):
        """True only when the start found the data folder on a disk of its own: never from the settings alone."""
        return self.storage != "local_default" and self.storage_check.confirmed

    @classmethod
    def from_env(cls, environ=None, *, mountinfo=None):
        """The settings from ``environ`` (default ``os.environ``). ``mountinfo`` replaces this process's mount table
        in tests; it is read only for a configured data folder."""
        env = os.environ if environ is None else environ
        explicit = env.get("NEURON_FLOW_DATA_DIR", "").strip()
        volume = env.get("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
        if explicit:
            data_dir, storage = Path(explicit), "configured"
        elif volume:
            data_dir, storage = Path(volume), "railway_volume"
        else:
            data_dir, storage = Path("neuron_workspace"), "local_default"
        data_dir = data_dir.resolve()
        storage_check = NOT_CONFIGURED if storage == "local_default" else check_storage(data_dir, mountinfo)
        key = env.get("NEURON_FLOW_ACCESS_KEY", "").strip()
        problem = None
        if not key:
            key, problem = None, "missing"
        elif len(key) < MIN_ACCESS_KEY_LENGTH:
            key, problem = None, "too_short"
        return cls(
            data_dir=data_dir, storage=storage, storage_check=storage_check,
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
