"""Sentry adapter tests with an in-memory stub SDK (no network, no sentry-sdk needed)."""
from contextlib import contextmanager
import json
import tempfile
import unittest

from neuron_flow import AgentDefinition, Runtime
from app.observability.sentry import SentryReporter, _before_send, run_job
from tests import core_agents


SECRET_INPUT = "customer-email@example.com"


class _Scope:
    def __init__(self):
        self.tags, self.contexts, self.fingerprint = {}, {}, None

    def set_tag(self, key, value):
        self.tags[key] = value

    def set_context(self, key, value):
        self.contexts[key] = value


class StubSdk:
    def __init__(self, active=True):
        self.events, self._active, self._scope = [], active, None

    def get_client(self):
        sdk = self

        class _Client:
            def is_active(self):
                return sdk._active
        return _Client()

    @contextmanager
    def new_scope(self):
        self._scope = _Scope()
        yield self._scope

    def capture_message(self, message, level=None):
        scope = self._scope
        self.events.append({"message": message, "level": level, "tags": scope.tags,
                            "context": scope.contexts["neuron_flow"], "fingerprint": scope.fingerprint})
        return f"evt{len(self.events)}"

    def capture_exception(self, exc):
        self.events.append({"exception": type(exc).__name__, "tags": self._scope.tags})
        return f"evt{len(self.events)}"


def _agents():
    return [
        AgentDefinition("echo", "tests.core_agents:echo", core_agents.validate_echo),
        AgentDefinition("permanent", "tests.core_agents:permanent", core_agents.validate_ok, version="2"),
        AgentDefinition("copy", "tests.core_agents:copy_dependency", core_agents.validate_copy),
    ]


def _failing_spec(job_id):
    return {"job_id": job_id, "input": {"value": SECRET_INPUT}, "steps": [
        {"id": "first", "agent": "echo"},
        {"id": "broken", "agent": "permanent", "max_attempts": 1},
        {"id": "after", "agent": "copy", "depends_on": ["broken"]},
    ]}


class SentryReportingTests(unittest.TestCase):
    def _run(self, spec, reporter):
        with tempfile.TemporaryDirectory() as work, Runtime(work, agents=_agents()) as rt:
            rt.submit(spec)
            return run_job(rt, spec["job_id"], reporter)

    def test_failed_step_becomes_one_privacy_safe_event(self):
        sdk = StubSdk()
        result = self._run(_failing_spec("fail_job"), SentryReporter(sdk=sdk))
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(len(sdk.events), 1)  # BLOCKED dependent is context, not a second event
        event = sdk.events[0]
        self.assertEqual(event["level"], "error")
        self.assertEqual(event["tags"]["neuron_flow.agent"], "permanent")
        self.assertEqual(event["tags"]["neuron_flow.error_type"], "PermanentAgentError")
        self.assertEqual(event["tags"]["neuron_flow.agent_version"], "2")
        self.assertEqual(event["tags"]["neuron_flow.retries_exhausted"], "true")
        self.assertEqual(event["fingerprint"], ["neuron-flow", "step-failed", "permanent", "PermanentAgentError"])
        self.assertEqual(event["context"]["blocked_dependents"], ["after"])
        self.assertNotIn("error_message", event["context"])
        self.assertNotIn(SECRET_INPUT, json.dumps(event))

    def test_error_messages_are_opt_in_and_truncated(self):
        sdk = StubSdk()
        self._run(_failing_spec("fail_msg"), SentryReporter(sdk=sdk, include_error_messages=True))
        self.assertEqual(sdk.events[0]["context"]["error_message"], "Cannot recover this input")

    def test_successful_job_sends_nothing(self):
        sdk = StubSdk()
        spec = {"job_id": "ok_job", "input": {"value": "x"}, "steps": [{"id": "first", "agent": "echo"}]}
        self.assertEqual(self._run(spec, SentryReporter(sdk=sdk))["status"], "SUCCEEDED")
        self.assertEqual(sdk.events, [])

    def test_inactive_or_missing_sdk_is_a_noop(self):
        missing = SentryReporter(sdk=StubSdk())
        missing.sdk = None  # same state as when sentry-sdk is not installed
        for reporter in (SentryReporter(sdk=StubSdk(active=False)), missing):
            self.assertFalse(reporter.active)
            self.assertEqual(self._run(_failing_spec("noop_job"), reporter)["status"], "FAILED")

    def test_runtime_exception_is_captured_and_reraised(self):
        sdk = StubSdk()
        with tempfile.TemporaryDirectory() as work:
            with Runtime(work, agents=_agents()) as rt:
                rt.submit({"job_id": "drift", "input": {"value": "x"}, "steps": [{"id": "s", "agent": "echo"}]})
            changed = [AgentDefinition("echo", "tests.core_agents:echo", core_agents.validate_echo, version="9")]
            with Runtime(work, agents=changed) as rt:
                with self.assertRaises(Exception):
                    run_job(rt, "drift", SentryReporter(sdk=sdk))
        self.assertEqual(sdk.events[0]["exception"], "SpecError")
        self.assertEqual(sdk.events[0]["tags"]["neuron_flow.event"], "runtime_exception")

    def test_before_send_strips_locals_and_user_data(self):
        event = {"user": {"email": SECRET_INPUT}, "request": {"data": SECRET_INPUT},
                 "exception": {"values": [{"stacktrace": {"frames": [{"vars": {"x": SECRET_INPUT}}]}}]}}
        self.assertNotIn(SECRET_INPUT, json.dumps(_before_send(event, None)))


if __name__ == "__main__":
    unittest.main()
