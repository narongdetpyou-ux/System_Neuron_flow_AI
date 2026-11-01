# Neuron Flow intake service: HTTP API + web page + the single Runner, in one container.
# Railway builds this file (see railway.json). Data lives on the attached volume, found through
# RAILWAY_VOLUME_MOUNT_PATH (or NEURON_FLOW_DATA_DIR); without one, jobs are lost on restart.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

# tini runs as process 1: it passes stop signals on and cleans up exited child processes.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

# The service starts as root only to take ownership of the mounted volume (Railway mounts volumes
# as root), then switches to this user (app/serve.py, drop_privileges).
RUN useradd --system --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin neuron

# Optional error reporting; it does nothing unless SENTRY_DSN is set.
RUN pip install "sentry-sdk>=2.0,<3"

WORKDIR /srv/neuron-flow
COPY neuron_flow ./neuron_flow
COPY app ./app
COPY LICENSE README.md ./

EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "app.serve"]
