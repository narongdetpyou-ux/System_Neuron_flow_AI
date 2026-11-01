#!/bin/bash
# SessionStart hook for Claude Code cloud sessions (claude.ai/code).
#
# The Core and the app use only the Python standard library, so the tests and demos need nothing
# installed. The one optional extra is sentry-sdk (Sentry error reporting); this hook installs it
# with the same version range as the Dockerfile, so the cloud session matches the container.
# It does nothing on a local machine.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

# Keep this range in step with the Dockerfile ("pip install sentry-sdk>=2.0,<3").
requirement='sentry-sdk>=2.0,<3'

# pip installs into the system Python, so there is no ignored folder to keep a hash in.
# Ask Python instead: if a 2.x sentry-sdk is already there, skip pip.
if python3 - <<'EOF'
import importlib.metadata as metadata
import sys

try:
    version = metadata.version("sentry-sdk")
except metadata.PackageNotFoundError:
    sys.exit(1)
sys.exit(0 if version.split(".")[0] == "2" else 1)
EOF
then
  exit 0
fi

python3 -m pip install --quiet --disable-pip-version-check --root-user-action=ignore "$requirement" >&2
echo "session-start: installed $requirement"
