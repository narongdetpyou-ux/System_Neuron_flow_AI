# Neuron Flow intake service: HTTP API + web page + the single Runner, in one container.
# Render builds this file (render.yaml); Railway can too (railway.json). Data lives on an attached
# disk found through NEURON_FLOW_DATA_DIR (or Railway's RAILWAY_VOLUME_MOUNT_PATH); without one,
# jobs are lost on restart.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

# tini passes stop signals on to the service and cleans up exited child processes (see ENTRYPOINT).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

# The container starts as root only to take ownership of the mounted disk (hosts such as Railway mount
# volumes as root), then switches to this user before tini and the service start (app/boot.py).
RUN useradd --system --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin neuron

# Optional error reporting; it does nothing unless SENTRY_DSN is set.
RUN pip install "sentry-sdk>=2.0,<3"

# A bytecode cache for the standard library and the installed packages (effectiveness plan E1). The base
# image ships without one, and the service can never write one: PYTHONDONTWRITEBYTECODE is set above and
# the service user cannot write here. Without a cache every new process (the launcher, the Runner, each
# worker) compiles every module it imports. unchecked-hash: valid by the source's content, never by file
# times, and used without reading the source again.
RUN python -m compileall -q -f -j 0 --invalidation-mode unchecked-hash \
    "$(python -c 'import sysconfig; print(sysconfig.get_path("stdlib"))')"

WORKDIR /srv/neuron-flow
COPY neuron_flow ./neuron_flow
COPY app ./app
COPY LICENSE README.md ./
# The same for the project's own code. Keep this after the last step that changes a file under
# neuron_flow/ or app/: an unchecked cache of older source would run the older code. The Service
# container check compares every cache file with its source and fails on a missing or stale one.
RUN python -m compileall -q -f --invalidation-mode unchecked-hash neuron_flow app

EXPOSE 8000
# Process 1 is app.boot: as root it prepares the data folder, switches to the neuron user, then replaces
# itself with tini, which runs CMD. tini must run as the same user as the service: on Render, root may
# not signal another user's processes, so a root tini could not pass SIGTERM on (app/boot.py explains).
ENTRYPOINT ["python", "-m", "app.boot"]
CMD ["python", "-m", "app.serve"]
