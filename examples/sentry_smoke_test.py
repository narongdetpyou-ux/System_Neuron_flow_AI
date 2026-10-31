"""Send one deliberate, synthetic step failure to Sentry to verify the setup.

    pip install -e ".[observability]"
    export SENTRY_DSN="https://...ingest.us.sentry.io/..."   # never commit it
    python -m examples.sentry_smoke_test

Expect one issue titled "Neuron Flow step failed: smoke.permanent (PermanentAgentError)".
"""
import tempfile

from neuron_flow import AgentDefinition, Runtime
from app.observability import SentryReporter, init_sentry, run_job
from tests import core_agents


def main():
    if not init_sentry(environment="smoke-test"):
        raise SystemExit("Set SENTRY_DSN and install the 'observability' extra first")
    agents = [AgentDefinition("smoke.permanent", "tests.core_agents:permanent", core_agents.validate_ok)]
    with tempfile.TemporaryDirectory(prefix="neuron-sentry-smoke-") as workspace:
        with Runtime(workspace, agents=agents) as runtime:
            runtime.submit({"job_id": "sentry_smoke_001", "input": {"note": "synthetic"},
                            "steps": [{"id": "fail", "agent": "smoke.permanent", "max_attempts": 1}]})
            result = run_job(runtime, "sentry_smoke_001", SentryReporter())
    import sentry_sdk  # present, because init_sentry succeeded
    sentry_sdk.flush(timeout=10)
    print(f"job status: {result['status']} — check the neuron-flow-runtime project in Sentry")


if __name__ == "__main__":
    main()
