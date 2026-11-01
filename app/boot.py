"""Process 1 of the container: prepare the data folder as root, drop root, then become tini.

The Dockerfile runs ``python -m app.boot python -m app.serve``. In order:
1. read the settings and create the data folders;
2. when started as root (hosts may mount disks as root), give the data folder to the unprivileged
   ``neuron`` user from the image and switch to that user;
3. replace this process with tini. tini starts the command, passes stop signals on to it and cleans up
   exited child processes.

Why tini must not stay root: on Render, root in the container may not signal another user's processes
(the container has no CAP_KILL). A root tini could not pass SIGTERM on to the service once the service
had switched to ``neuron``. It logged "[FATAL tini (1)] Unexpected error when forwarding signal:
'Operation not permitted'" and exited, so every deploy or restart killed the service and the Runner
instead of stopping them (seen on 2026-11-01). With tini and the service under the same user, passing a
signal on needs no capability. The *Service container* check runs the image with ``--cap-drop KILL`` and
fails if process 1 still runs as root or a stop is not graceful.
"""

import logging
import os
import sys

from app.settings import Settings

RUN_AS = "neuron"
TINI = "/usr/bin/tini"
DEFAULT_COMMAND = ("python", "-m", "app.serve")
log = logging.getLogger("neuron_flow.boot")


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


def prepare_data_folders(settings):
    for folder in (settings.core_dir, settings.queue_db.parent):
        folder.mkdir(parents=True, exist_ok=True)


def main(argv=None, *, environ=None, user=RUN_AS, execv=os.execv):
    """Prepare, drop root, then exec tini with ``argv`` (default: ``python -m app.serve``).

    Returns only when tini cannot be started (outside the image); ``execv`` is replaceable for tests.
    """
    command = list(sys.argv[1:] if argv is None else argv) or list(DEFAULT_COMMAND)
    settings = Settings.from_env(environ)
    prepare_data_folders(settings)
    if drop_privileges(settings.data_dir, user):
        log.info("boot: gave the data folder to the '%s' user and switched to it; starting tini", user)
    try:
        execv(TINI, [TINI, "--", *command])
    except FileNotFoundError:
        log.error("boot: %s is missing. app.boot is the container's entry point; outside the image, run "
                  "'python -m app.serve' instead", TINI)
        return 1
    return 0  # only reached when execv is replaced (tests)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    sys.exit(main())
