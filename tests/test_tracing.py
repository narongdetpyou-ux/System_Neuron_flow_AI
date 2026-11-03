"""Tracing to Honeycomb (roadmap 5.1): settings, the OTLP/JSON encoding, the exporter's failure paths, the
spans of one job, one trace per job across the API and the Runner, the privacy scan of everything sent, and
the proof that turning tracing off changes no result.

A local receiver stands in for Honeycomb; CI also checks the same requests against the OpenTelemetry
Collector (.github/workflows/tracing-check.yml).
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from neuron_flow import __version__

from app.api import ApiApp, make_server
from app.domains.case_triage import build_shadow_workflow
from app.llm import LLMConfig, load_prompt
from app.observability import Tracing, job_spans
from app.observability import tracing as tracing_module
from app.observability.job_spans import step_attempts
from app.observability.tracing import (KIND_CLIENT, KIND_INTERNAL, KIND_SERVER, SPAN_ATTRIBUTES, STATUS_ERROR,
                                       STATUS_UNSET, Exporter, Span, encode_request, format_traceparent,
                                       new_span_id, new_trace_id, parse_traceparent, traces_url)
from app.persistence import QueueStore
from app.services.admission import admit
from app.services.results import AI_STEP
from app.services.runner import Runner
from app.services.workflows import CATALOG, WorkflowType
from tests.service_fixtures import KEY, case_body, settings

# Built from pieces, so no file holds a string that looks like a key (tests/test_no_secrets.py, gitleaks).
HONEYCOMB_KEY = "-".join(["fake", "honeycomb", "ingest", "key", "for", "tests"])
RESOURCE = {"service.name": "neuron-flow", "service.version": "test", "service.instance.id": "instance-1",
            "deployment.environment.name": "test", "neuron_flow.process": "test",
            "telemetry.sdk.name": "neuron-flow", "telemetry.sdk.language": "python", "telemetry.sdk.version": "0"}


class Receiver:
    """A local OTLP/HTTP receiver. ``replies`` scripts the answers (a status, or ``(status, body, headers)``);
    after they run out every request gets 200 ``{}``."""

    def __init__(self, replies=()):
        self.requests = []
        self.replies = list(replies)
        self._lock = threading.Lock()
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                with receiver._lock:
                    receiver.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()},
                                              "body": body})
                    reply = receiver.replies.pop(0) if receiver.replies else 200
                status, payload, headers = reply if isinstance(reply, tuple) else (reply, b"{}", {})
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def endpoint(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def bodies(self):
        with self._lock:
            return [request["body"] for request in self.requests]

    def spans(self):
        """``[(resource attributes, span), ...]`` from every request received."""
        found = []
        for body in self.bodies():
            for resource_spans in json.loads(body)["resourceSpans"]:
                resource = attributes_of(resource_spans["resource"])
                for scope in resource_spans["scopeSpans"]:
                    found += [(resource, span) for span in scope["spans"]]
        return found


def attributes_of(item):
    values = {}
    for attribute in item.get("attributes", []):
        (kind, value), = attribute["value"].items()
        values[attribute["key"]] = int(value) if kind == "intValue" else value
    return values


def closed_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def env_for(receiver, **extra):
    return {"HONEYCOMB_API_KEY": HONEYCOMB_KEY, "HONEYCOMB_API_ENDPOINT": receiver.endpoint, **extra}


def span(name="step x", *, trace_id=None, parent_id=None, start=1_000, end=2_000, attributes=None, **kwargs):
    return Span(name, trace_id or new_trace_id(), new_span_id(), parent_id, kwargs.pop("kind", KIND_INTERNAL),
                start, end, attributes or {"neuron_flow.step.id": "x"}, **kwargs)


# -- settings ---------------------------------------------------------------------------------------

class TracingSettingsTests(unittest.TestCase):
    def test_off_without_a_key_and_on_with_one(self):
        off = Tracing.from_env("api", {})
        self.assertFalse(off.enabled)
        self.assertEqual(off.status(), {"enabled": False, "problem": "not_configured", "destination": None,
                                        "service_name": None})
        self.assertIsNone(off.start_request())
        off.export([span()])  # harmless when off
        on = Tracing.from_env("api", {"HONEYCOMB_API_KEY": HONEYCOMB_KEY})
        self.addCleanup(on.shutdown, 0)
        self.assertTrue(on.enabled)
        self.assertEqual((on.destination, on.service_name), ("api.honeycomb.io", "neuron-flow"))
        self.assertEqual(on.exporter.url, "https://api.honeycomb.io/v1/traces")
        status = on.status()
        self.assertEqual((status["enabled"], status["exported_spans"], status["last_error"]), (True, 0, None))
        # The key is read again at every export: it is not copied into the settings, the status or the resource.
        self.assertNotIn(HONEYCOMB_KEY, json.dumps([status, on.exporter.resource, on.exporter.url]))

    def test_endpoints_and_the_ones_that_are_refused(self):
        self.assertEqual(traces_url("https://api.eu1.honeycomb.io"), "https://api.eu1.honeycomb.io/v1/traces")
        self.assertEqual(traces_url("https://api.honeycomb.io/"), "https://api.honeycomb.io/v1/traces")
        self.assertEqual(traces_url("https://api.honeycomb.io/v1/traces"), "https://api.honeycomb.io/v1/traces")
        self.assertEqual(traces_url("http://127.0.0.1:4318"), "http://127.0.0.1:4318/v1/traces")
        for bad in ("http://api.honeycomb.io", "https://user:pw@api.honeycomb.io", "ftp://api.honeycomb.io",
                    "https://api.honeycomb.io/?team=x", "https://api.honeycomb.io/#x", "api.honeycomb.io",
                    "http://127.0.0.1:99999", "https://" + "a" * 200):
            tracing = Tracing.from_env("api", {"HONEYCOMB_API_KEY": HONEYCOMB_KEY, "HONEYCOMB_API_ENDPOINT": bad})
            self.assertEqual((tracing.enabled, tracing.problem), (False, "invalid_endpoint"), bad)

    def test_switch_service_name_and_environment(self):
        key = {"HONEYCOMB_API_KEY": HONEYCOMB_KEY}
        for value, problem in (("off", "switched_off"), ("OFF", "switched_off"), ("0", "switched_off"),
                               ("maybe", "invalid_switch")):
            self.assertEqual(Tracing.from_env("api", {**key, "NEURON_FLOW_TRACING": value}).problem, problem)
        self.assertEqual(Tracing.from_env("api", {**key, "OTEL_SERVICE_NAME": "bad name"}).problem,
                         "invalid_service_name")
        self.assertEqual(Tracing.from_env("api", {**key, "NEURON_FLOW_ENVIRONMENT": "ไทย"}).problem,
                         "invalid_environment")
        cases = (({"RENDER": "true", "RENDER_GIT_COMMIT": "3aa76a13f00dfeedbeef"}, "render", "+3aa76a13f00d"),
                 ({"GITHUB_ACTIONS": "true", "GITHUB_SHA": "abcdef1"}, "ci", "+abcdef1"),
                 ({"NEURON_FLOW_ENVIRONMENT": "smoke", "RENDER_GIT_COMMIT": "not-a-sha"}, "smoke", ""),
                 ({}, "local", ""))
        for extra, environment, suffix in cases:
            tracing = Tracing.from_env("runner", {**key, "NEURON_FLOW_TRACING": "on", **extra})
            self.addCleanup(tracing.shutdown, 0)
            resource = tracing.exporter.resource
            self.assertEqual(resource["deployment.environment.name"], environment)
            # The version names the deployed commit when the host says which one it is.
            self.assertEqual(resource["service.version"], __version__ + suffix)
            self.assertEqual(resource["neuron_flow.process"], "runner")


# -- spans and their encoding -----------------------------------------------------------------------

class EncodingTests(unittest.TestCase):
    def test_a_span_in_otlp_json(self):
        trace_id, parent = new_trace_id(), new_span_id()
        child = Span("chat mock-keyword-1", trace_id, new_span_id(), parent, KIND_CLIENT, 1_700_000_000_123_456_789,
                     1_700_000_000_223_456_789, {"gen_ai.usage.input_tokens": 314, "neuron_flow.ai.latency_ms": 12,
                                                 "neuron_flow.ai.usage_estimated": True, "gen_ai.request.model": "m-1"},
                     STATUS_ERROR)
        root = span(trace_id=trace_id)
        body = json.loads(encode_request(RESOURCE, [root, child]))
        (resource_spans,) = body["resourceSpans"]
        self.assertEqual(attributes_of(resource_spans["resource"])["service.name"], "neuron-flow")
        (scope,) = resource_spans["scopeSpans"]
        self.assertEqual(scope["scope"]["name"], "neuron_flow.app")
        first, second = scope["spans"]
        self.assertNotIn("parentSpanId", first)
        self.assertNotIn("status", first)  # unset is left out
        self.assertEqual((second["traceId"], second["parentSpanId"], second["kind"], second["status"]),
                         (trace_id, parent, 3, {"code": 2}))
        # OTLP/JSON: hex ids, 64-bit integers as decimal strings, attributes typed and in name order.
        self.assertEqual((len(second["traceId"]), len(second["spanId"])), (32, 16))
        self.assertEqual((second["startTimeUnixNano"], second["endTimeUnixNano"]),
                         ("1700000000123456789", "1700000000223456789"))
        self.assertEqual(second["attributes"], [
            {"key": "gen_ai.request.model", "value": {"stringValue": "m-1"}},
            {"key": "gen_ai.usage.input_tokens", "value": {"intValue": "314"}},
            {"key": "neuron_flow.ai.latency_ms", "value": {"doubleValue": 12.0}},
            {"key": "neuron_flow.ai.usage_estimated", "value": {"boolValue": True}}])

    def test_only_listed_short_ascii_attributes_are_accepted(self):
        for attributes in ({"case_text": "anything"}, {"neuron_flow.step.id": "ขั้นตอน"},
                           {"neuron_flow.step.attempt": True}, {"neuron_flow.ai.latency_ms": float("nan")},
                           {"neuron_flow.step.id": ""}, {"neuron_flow.step.id": "line\nbreak"},
                           {"neuron_flow.step.attempt": 2 ** 63}, {"neuron_flow.ai.usage_estimated": 1}):
            with self.assertRaises(ValueError, msg=attributes):
                span(attributes=attributes)
        long = span(attributes={"neuron_flow.agent.version": "v" * 400})
        self.assertEqual(len(long.attributes["neuron_flow.agent.version"]), 256)
        self.assertEqual(span(attributes={"neuron_flow.step.id": "x", "error.type": None}).attributes,
                         {"neuron_flow.step.id": "x"})  # None means "not known": left out

    def test_ids_times_and_the_trace_context(self):
        with self.assertRaises(ValueError):
            Span("x", "A" * 32, new_span_id(), None, KIND_INTERNAL, 1, 2, {})
        with self.assertRaises(ValueError):
            Span("x", new_trace_id(), new_span_id(), "nope", KIND_INTERNAL, 1, 2, {})
        with self.assertRaises(ValueError):
            Span("x", new_trace_id(), new_span_id(), None, KIND_INTERNAL, 5, 4, {})
        with self.assertRaises(ValueError):
            Span("ชื่อ", new_trace_id(), new_span_id(), None, KIND_INTERNAL, 1, 2, {})
        trace_id, span_id = new_trace_id(), new_span_id()
        self.assertEqual(parse_traceparent(format_traceparent(trace_id, span_id)), (trace_id, span_id))
        for bad in (None, "", "garbage", f"01-{trace_id}-{span_id}-01", f"00-{'0' * 32}-{span_id}-01",
                    f"00-{trace_id}-{'0' * 16}-01", f"00-{trace_id.upper()}-{span_id}-01"):
            self.assertIsNone(parse_traceparent(bad), bad)


# -- the exporter -----------------------------------------------------------------------------------

class ExporterTests(unittest.TestCase):
    def exporter(self, receiver=None, *, endpoint=None, environ=None, **options):
        url = traces_url(endpoint or receiver.endpoint)
        options = {"interval_s": 0.05, "timeout_s": 2.0, "retry_delays_s": (0.01, 0.01), **options}
        exporter = Exporter(url, RESOURCE, environ={"HONEYCOMB_API_KEY": HONEYCOMB_KEY} if environ is None else environ,
                            **options)
        self.addCleanup(exporter.shutdown, 0)
        return exporter

    def receiver(self, replies=()):
        receiver = Receiver(replies)
        self.addCleanup(receiver.close)
        return receiver

    def test_spans_arrive_with_the_key_only_in_its_header(self):
        receiver = self.receiver()
        exporter = self.exporter(receiver)
        exporter.submit([span(), span()])
        exporter.submit([span()])
        self.assertTrue(exporter.flush())
        self.assertEqual(len(receiver.spans()), 3)
        request = receiver.requests[0]
        self.assertEqual(request["path"], "/v1/traces")
        self.assertEqual(request["headers"]["content-type"], "application/json")
        self.assertEqual(request["headers"]["x-honeycomb-team"], HONEYCOMB_KEY)
        self.assertNotIn(HONEYCOMB_KEY.encode(), b"".join(receiver.bodies()))
        status = exporter.status()
        self.assertEqual((status["exported_spans"], status["dropped_spans"], status["last_error"]), (3, 0, None))
        self.assertIsNotNone(status["last_ok_at"])

    def test_a_wrong_key_is_not_retried_and_never_logged(self):
        receiver = self.receiver([401])
        exporter = self.exporter(receiver)
        with self.assertLogs("neuron_flow.tracing", "WARNING") as logs:
            exporter.submit([span(), span()])
            exporter.flush()
        self.assertEqual(len(receiver.requests), 1)
        status = exporter.status()
        self.assertEqual((status["dropped_spans"], status["failed_exports"], status["last_error"]), (2, 1, "http_401"))
        self.assertIn("http_401", "\n".join(logs.output))
        self.assertNotIn(HONEYCOMB_KEY, "\n".join(logs.output))

    def test_busy_receivers_are_retried(self):
        receiver = self.receiver([503, 429])
        exporter = self.exporter(receiver)
        exporter.submit([span()])
        exporter.flush()
        self.assertEqual(len(receiver.requests), 3)
        self.assertEqual((exporter.status()["exported_spans"], exporter.status()["last_error"]), (1, None))

    def test_an_unreachable_receiver_drops_the_spans_and_the_work_goes_on(self):
        exporter = self.exporter(endpoint=f"http://127.0.0.1:{closed_port()}")
        started = time.monotonic()
        exporter.submit([span()])  # returns at once
        self.assertLess(time.monotonic() - started, 0.5)
        exporter.flush()
        self.assertEqual((exporter.status()["dropped_spans"], exporter.status()["last_error"]), (1, "network"))

    def test_redirects_are_refused_so_the_key_stays_with_the_receiver(self):
        elsewhere = self.receiver()
        receiver = self.receiver([(307, b"", {"Location": elsewhere.endpoint + "/v1/traces"})])
        exporter = self.exporter(receiver)
        exporter.submit([span()])
        exporter.flush()
        self.assertEqual((len(receiver.requests), len(elsewhere.requests)), (1, 0))
        self.assertEqual(exporter.status()["last_error"], "http_307")

    def test_the_queue_is_bounded_and_a_trace_is_kept_whole_or_dropped_whole(self):
        receiver = self.receiver()
        exporter = self.exporter(receiver, max_queue=3, interval_s=60)
        exporter.submit([span(), span()])
        exporter.submit([span(), span()])  # no room for both: neither is queued
        self.assertEqual(exporter.status()["queued_spans"], 2)
        self.assertEqual(exporter.status()["dropped_spans"], 2)
        exporter.flush()
        self.assertEqual(len(receiver.spans()), 2)

    def test_the_key_is_read_at_every_export(self):
        receiver = self.receiver()
        environ = {"HONEYCOMB_API_KEY": HONEYCOMB_KEY}
        exporter = self.exporter(receiver, environ=environ)
        environ.pop("HONEYCOMB_API_KEY")
        exporter.submit([span()])
        exporter.flush()
        self.assertEqual((len(receiver.requests), exporter.status()["last_error"]), (0, "key_missing"))
        environ["HONEYCOMB_API_KEY"] = "a-rotated-key"
        exporter.submit([span()])
        exporter.flush()
        self.assertEqual(receiver.requests[-1]["headers"]["x-honeycomb-team"], "a-rotated-key")

    def test_shutdown_sends_what_is_queued_within_its_time_limit(self):
        receiver = self.receiver()
        exporter = self.exporter(receiver, interval_s=60)
        exporter.submit([span(), span()])
        exporter.shutdown(2)
        self.assertEqual(len(receiver.spans()), 2)
        exporter.submit([span()])  # after shutdown: dropped, no error
        self.assertEqual(exporter.status()["dropped_spans"], 1)

        stuck = self.exporter(endpoint=f"http://127.0.0.1:{closed_port()}", interval_s=60, retry_delays_s=(5, 5))
        stuck.submit([span()])
        started = time.monotonic()
        stuck.shutdown(1)
        self.assertLess(time.monotonic() - started, 3)  # no waiting between retries while stopping
        self.assertEqual(stuck.status()["dropped_spans"], 1)

    def test_partly_rejected_batches_are_counted(self):
        receiver = self.receiver([(200, b'{"partialSuccess":{"rejectedSpans":"1","errorMessage":"x"}}', {})])
        exporter = self.exporter(receiver)
        exporter.submit([span(), span(), span()])
        exporter.flush()
        status = exporter.status()
        self.assertEqual((status["exported_spans"], status["dropped_spans"], status["last_error"]),
                         (2, 1, "spans_rejected"))

    def test_an_internal_error_loses_one_batch_but_not_the_exporter(self):
        receiver = self.receiver()
        exporter = self.exporter(receiver)
        with mock.patch.object(tracing_module, "encode_request", side_effect=RuntimeError("boom")):
            exporter.submit([span()])
            exporter.flush()
        self.assertEqual(exporter.status()["last_error"], "internal_RuntimeError")
        exporter.submit([span()])
        exporter.flush()
        self.assertEqual((len(receiver.spans()), exporter.status()["last_error"]), (1, None))


# -- the spans of one job ---------------------------------------------------------------------------

T0 = 1_762_160_000.0  # a Unix time in seconds, as the queue and Core store times


def a_job(*, status="REVIEW_REQUIRED", claims=1, failure=None, ai=None, spec=True, started=T0 + 0.5,
          core_status="SUCCEEDED"):
    steps = [{"id": "classify_rules", "agent": "triage.classify", "max_attempts": 1},
             {"id": "classify_llm", "agent": "triage.classify_llm", "max_attempts": 2,
              "params": {"llm": {"max_tokens": 2048}}},
             {"id": "compare", "agent": "triage.compare", "max_attempts": 2, "depends_on": ["classify_rules", "classify_llm"]}]
    return {"job_id": "job_" + "a" * 24, "workflow_type": "case_triage.v2", "status": status, "claims": claims,
            "created_at": T0, "started_at": started, "finished_at": T0 + 3.0, "failure": failure,
            "spec": {"steps": steps, "agent_versions": {"triage.classify_llm": {"version": "llm=mock/mock-keyword-1"}}}
            if spec else None,
            "result": {"core_status": core_status, "ai": ai}}


def ai_view(**overrides):
    view = {"status": "ok", "provider": "mock", "model": "mock-keyword-1", "served_model": "mock-keyword-1",
            "prompt_id": "triage_classify_v1", "prompt_sha256": "ab" * 32, "redaction": "redact-v1", "attempt": 1,
            "masked": {"email": 1, "phone": 2}, "usage": {"input_tokens": 314, "output_tokens": 31, "estimated": True},
            "latency_ms": 250.0}
    view.update(overrides)
    return view


def event(kind, at, step_id=None, attempt=None, error=None):
    return {"kind": kind, "timestamp": T0 + at, "step_id": step_id,
            "payload": {"attempt": attempt, "error": error} if step_id else {}}


def happy_events():
    return [event("job.submitted", 0.6), event("job.running", 0.6),
            event("step.running", 0.7, "classify_rules", 1), event("step.running", 0.8, "classify_llm", 1),
            event("step.succeeded", 1.0, "classify_rules", 1), event("step.succeeded", 2.0, "classify_llm", 1),
            event("step.running", 2.1, "compare", 1), event("step.succeeded", 2.5, "compare", 1),
            event("job.succeeded", 2.9)]


def by_name(spans):
    found = {}
    for item in spans:
        found.setdefault(item.name, []).append(item)
    return found


class JobSpanTests(unittest.TestCase):
    def test_a_job_becomes_one_trace_under_the_request_that_admitted_it(self):
        trace_id, request_span = new_trace_id(), new_span_id()
        admission = {"workflow_type": "case_triage.v2", "request_id": "req_0123456789abcdef",
                     "trace_parent": format_traceparent(trace_id, request_span)}
        spans = job_spans(a_job(ai=ai_view()), admission, happy_events(), ai_step=AI_STEP)
        names = by_name(spans)
        self.assertEqual(sorted(names), ["chat mock-keyword-1", "job case_triage.v2", "queue wait", "run",
                                         "step classify_llm", "step classify_rules", "step compare"])
        self.assertEqual({item.trace_id for item in spans}, {trace_id})
        (job,), (wait,), (run,) = names["job case_triage.v2"], names["queue wait"], names["run"]
        self.assertEqual((job.parent_id, wait.parent_id, run.parent_id), (request_span, job.span_id, job.span_id))
        self.assertEqual((job.start_ns, wait.end_ns, run.start_ns, job.end_ns),
                         (int(T0 * 1e9), int((T0 + 0.5) * 1e9), int((T0 + 0.5) * 1e9), int((T0 + 3) * 1e9)))
        self.assertEqual(job.attributes["neuron_flow.request_id"], "req_0123456789abcdef")
        self.assertEqual((job.attributes["neuron_flow.queue.wait_ms"], job.attributes["neuron_flow.job.run_ms"]),
                         (500.0, 2500.0))
        self.assertEqual(job.status, STATUS_UNSET)
        (llm,), (chat,) = names["step classify_llm"], names["chat mock-keyword-1"]
        self.assertEqual({item.parent_id for name, items in names.items() if name.startswith("step ") for item in items},
                         {run.span_id})
        self.assertEqual((llm.attributes["neuron_flow.step.outcome"], llm.attributes["neuron_flow.ai.status"],
                          llm.attributes["neuron_flow.agent.version"]), ("SUCCEEDED", "ok", "llm=mock/mock-keyword-1"))
        # The AI call: its measured length, ending with its step attempt; GenAI semantic conventions.
        self.assertEqual((chat.parent_id, chat.kind, chat.end_ns, chat.end_ns - chat.start_ns),
                         (llm.span_id, KIND_CLIENT, llm.end_ns, 250_000_000))
        self.assertEqual({key: chat.attributes[key] for key in (
            "gen_ai.operation.name", "gen_ai.provider.name", "gen_ai.request.model", "gen_ai.response.model",
            "gen_ai.request.max_tokens", "gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens",
            "neuron_flow.ai.usage_estimated", "neuron_flow.ai.masked_items")},
            {"gen_ai.operation.name": "chat", "gen_ai.provider.name": "mock", "gen_ai.request.model": "mock-keyword-1",
             "gen_ai.response.model": "mock-keyword-1", "gen_ai.request.max_tokens": 2048,
             "gen_ai.usage.input_tokens": 314, "gen_ai.usage.output_tokens": 31,
             "neuron_flow.ai.usage_estimated": True, "neuron_flow.ai.masked_items": 3})

    def test_a_retried_ai_attempt_is_its_own_failed_span(self):
        events = [event("step.running", 0.7, "classify_llm", 1),
                  event("step.retry_wait", 1.0, "classify_llm", 1,
                        {"type": "LLMTransientError", "message": "provider said: Somchai cannot log in"}),
                  event("step.running", 1.2, "classify_llm", 2), event("step.succeeded", 1.9, "classify_llm", 2)]
        spans = job_spans(a_job(ai=ai_view(attempt=2)), {}, events, ai_step=AI_STEP)
        first, second = by_name(spans)["step classify_llm"]
        self.assertEqual((first.attributes["neuron_flow.step.attempt"], first.attributes["neuron_flow.step.outcome"],
                          first.attributes["error.type"], first.status), (1, "RETRY_WAIT", "LLMTransientError", STATUS_ERROR))
        self.assertEqual((second.attributes["neuron_flow.step.attempt"], second.status), (2, STATUS_UNSET))
        (chat,) = by_name(spans)["chat mock-keyword-1"]
        self.assertEqual(chat.parent_id, second.span_id)
        self.assertNotIn("Somchai", json.dumps([item.attributes for item in spans]))  # messages are never read

    def test_an_unavailable_ai_has_no_call_span(self):
        spans = job_spans(a_job(ai={"status": "unavailable", "reason": "model_declined", "error_type": "ModelDeclined",
                                    "attempt": 1, "provider": "mock", "model": "mock-keyword-1"}),
                          {}, happy_events(), ai_step=AI_STEP)
        self.assertNotIn("chat mock-keyword-1", by_name(spans))
        (llm,) = by_name(spans)["step classify_llm"]
        self.assertEqual((llm.attributes["neuron_flow.ai.status"], llm.attributes["neuron_flow.ai.reason"], llm.status),
                         ("unavailable", "model_declined", STATUS_UNSET))

    def test_failed_and_blocked_steps(self):
        events = [event("step.running", 0.7, "classify_rules", 1),
                  event("step.failed", 0.9, "classify_rules", 1, {"type": "OutputValidationError", "message": "x"}),
                  event("step.blocked", 1.0, "compare", 0, {"type": "DependencyFailed", "message": "y"}),
                  event("step.running", 1.1, "classify_llm", 1),
                  event("step.failed", 1.2, "classify_llm", 1, {"type": "not a class name!", "message": "z"})]
        spans = job_spans(a_job(status="FAILED", core_status="FAILED",
                                failure={"reason": "step_failed", "failed_steps": ["classify_rules"]}),
                          {}, events, ai_step=AI_STEP)
        names = by_name(spans)
        (job,), (rules,), (blocked,), (llm,) = (names["job case_triage.v2"], names["step classify_rules"],
                                               names["step compare"], names["step classify_llm"])
        self.assertEqual((job.status, job.attributes["error.type"], job.attributes["neuron_flow.failure.reason"]),
                         (STATUS_ERROR, "step_failed", "step_failed"))
        self.assertEqual((rules.status, rules.attributes["error.type"]), (STATUS_ERROR, "OutputValidationError"))
        self.assertEqual((blocked.start_ns == blocked.end_ns, blocked.status, blocked.attributes["neuron_flow.step.outcome"]),
                         (True, STATUS_UNSET, "BLOCKED"))
        self.assertEqual(llm.attributes["error.type"], "Unknown")  # an unexpected type string is not copied

    def test_a_job_core_never_ran_and_a_job_without_a_trace_parent(self):
        spans = job_spans(a_job(status="FAILED", spec=False, core_status=None,
                                failure={"reason": "configuration_changed", "error_type": "SpecChanged"}),
                          {"workflow_type": "case_triage.v2"}, [], ai_step=AI_STEP)
        self.assertEqual(sorted(by_name(spans)), ["job case_triage.v2", "queue wait", "run"])
        (job,) = by_name(spans)["job case_triage.v2"]
        self.assertIsNone(job.parent_id)  # admitted while tracing was off: the job starts its own trace
        self.assertEqual((job.status, job.attributes["error.type"]), (STATUS_ERROR, "configuration_changed"))
        with self.assertRaises(ValueError):
            job_spans({**a_job(), "finished_at": None}, {}, [], ai_step=AI_STEP)

    def test_a_job_finished_after_a_runner_restart(self):
        events = [event("step.running", 0.7, "classify_llm", 1),
                  event("step.retry_wait", 1.5, "classify_llm", 1, {"type": "ControllerInterrupted", "message": "m"}),
                  event("step.running", 1.6, "classify_llm", 2)]
        attempts = step_attempts(events, end_ns=int((T0 + 3) * 1e9))
        self.assertEqual([(a["attempt"], a["outcome"], a["error_type"]) for a in attempts],
                         [(1, "RETRY_WAIT", "ControllerInterrupted"), (2, "UNFINISHED", None)])
        self.assertEqual(attempts[1]["end_ns"], int((T0 + 3) * 1e9))
        spans = job_spans(a_job(claims=2), {}, events, ai_step=AI_STEP)
        (job,), (run,) = by_name(spans)["job case_triage.v2"], by_name(spans)["run"]
        self.assertEqual((job.attributes["neuron_flow.job.claims"], run.attributes["neuron_flow.job.claims"]), (2, 2))
        self.assertEqual([item.status for item in by_name(spans)["step classify_llm"]], [STATUS_ERROR, STATUS_ERROR])


# -- the service, end to end ------------------------------------------------------------------------

SENTINELS = ("ZEBRA-SENTINEL-7781", "somchai.sentinel@example.com", "081-234-5678", "1-1037-02071-81-1",
             "อัปโหลดไฟล์แนบไม่ได้")
SECRET_SUMMARY = ("อัปโหลดไฟล์แนบไม่ได้ ZEBRA-SENTINEL-7781 contact somchai.sentinel@example.com "
                  "or 081-234-5678, ID 1-1037-02071-81-1")


def transient_once_catalog():
    """case_triage.v2 whose mock AI fails its first attempt (Core then retries the step)."""
    workflow = CATALOG["case_triage.v2"]
    flaky = WorkflowType("test.flaky_ai", "test only: the AI fails once", workflow.final_step, workflow.check_input,
                         lambda job_id, case, config: build_shadow_workflow(
                             job_id, case, config, mock_scenario={"kind": "transient", "attempts": [1]}),
                         workflow.agents)
    return {**CATALOG, "test.flaky_ai": flaky}


class TracedServiceTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.receiver = Receiver()
        self.addCleanup(self.receiver.close)
        self.catalog = transient_once_catalog()

    def start(self, name, *, traced=True):
        """An API server and a Runner on their own data folder; both trace to the receiver when ``traced``."""
        config = settings(Path(self._temp.name) / name, host="127.0.0.1", port=0)
        store = QueueStore(config.queue_db)
        store.migrate()
        environ = env_for(self.receiver) if traced else {}
        api_tracing = Tracing.from_env("api", environ, interval_s=0.05)
        runner_tracing = Tracing.from_env("runner", environ, interval_s=0.05)
        for tracing in (api_tracing, runner_tracing):
            self.addCleanup(tracing.shutdown, 0)
        server = make_server(config, ApiApp(config, store, catalog=self.catalog, tracing=api_tracing))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        runner = Runner(config, store=store, catalog=self.catalog, llm_config=LLMConfig(), tracing=runner_tracing)
        return {"base": f"http://127.0.0.1:{server.server_address[1]}", "store": store, "runner": runner,
                "tracing": (api_tracing, runner_tracing)}

    def call(self, service, method, path, body=None, *, key=KEY):
        data = None if body is None else json.dumps(body).encode()
        headers = {**({"Authorization": f"Bearer {key}"} if key else {}),
                   **({"Content-Type": "application/json"} if data else {})}
        request = urllib.request.Request(service["base"] + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read() or b"null")

    def flush(self, service):
        for tracing in service["tracing"]:
            self.assertTrue(tracing.flush(10))

    def traces(self):
        found = {}
        for _resource, item in self.receiver.spans():
            found.setdefault(item["traceId"], []).append(item)
        return found

    def test_one_job_is_one_trace_with_its_steps_and_the_ai_call(self):
        service = self.start("one")
        status, job = self.call(service, "POST", "/v1/jobs", case_body("key-trace-0001", summary=SECRET_SUMMARY))
        self.assertEqual(status, 202)
        self.assertEqual(service["runner"].drain(), 1)
        status, view = self.call(service, "GET", f"/v1/jobs/{job['job_id']}")
        self.assertEqual((status, view["status"]), (200, "REVIEW_REQUIRED"))
        self.flush(service)
        trace = self.traces()[view["trace_id"]]
        named = {}
        for item in trace:
            named.setdefault(item["name"], []).append(item)
        self.assertEqual(sorted(named), ["POST /v1/jobs", "chat mock-keyword-1", "job case_triage.v2", "queue wait",
                                         "run", "step classify_llm", "step classify_rules", "step compare",
                                         "step prepare"])
        (request,), (job_span,), (run,), (chat,) = (named["POST /v1/jobs"], named["job case_triage.v2"], named["run"],
                                                  named["chat mock-keyword-1"])
        self.assertNotIn("parentSpanId", request)  # the request is the root of the job's trace
        self.assertEqual((request["kind"], attributes_of(request)["http.route"],
                          attributes_of(request)["http.response.status_code"]), (KIND_SERVER, "/v1/jobs", 202))
        self.assertEqual(job_span["parentSpanId"], request["spanId"])
        self.assertEqual(attributes_of(job_span)["neuron_flow.job.id"], job["job_id"])
        for step in ("step classify_rules", "step classify_llm", "step compare", "step prepare"):
            self.assertEqual({item["parentSpanId"] for item in named[step]}, {run["spanId"]}, step)
        self.assertEqual(chat["parentSpanId"], named["step classify_llm"][0]["spanId"])
        self.assertEqual(attributes_of(chat)["gen_ai.usage.input_tokens"],
                         view["result"]["ai"]["usage"]["input_tokens"])
        # Reading the job was a request of its own: its own trace, with the route template, not the path.
        reads = [item for spans in self.traces().values() for item in spans if item["name"] == "GET /v1/jobs/{job_id}"]
        self.assertEqual(len(reads), 1)
        self.assertNotEqual(reads[0]["traceId"], view["trace_id"])
        self.assertNotIn(job["job_id"], json.dumps(reads[0]))

    def test_a_retried_step_shows_both_attempts(self):
        service = self.start("retry")
        body = dict(case_body("key-trace-0002"), workflow_type="test.flaky_ai")
        status, job = self.call(service, "POST", "/v1/jobs", body)
        self.assertEqual(status, 202)
        service["runner"].drain()
        _status, view = self.call(service, "GET", f"/v1/jobs/{job['job_id']}")
        self.flush(service)
        attempts = sorted((item for item in self.traces()[view["trace_id"]] if item["name"] == "step classify_llm"),
                          key=lambda item: int(item["startTimeUnixNano"]))
        self.assertEqual([(attributes_of(item)["neuron_flow.step.attempt"], attributes_of(item).get("error.type"),
                           item.get("status", {}).get("code", 0)) for item in attempts],
                         [(1, "LLMTransientError", STATUS_ERROR), (2, None, STATUS_UNSET)])

    def test_what_is_traced_and_what_is_not(self):
        service = self.start("routes")
        self.assertEqual(self.call(service, "GET", "/healthz", key=None)[0], 200)
        with urllib.request.urlopen(service["base"] + "/", timeout=10) as page:  # the page itself
            self.assertEqual(page.status, 200)
        self.assertEqual(self.call(service, "GET", "/v1/status", key="wrong-key-but-long-enough")[0], 401)
        self.assertEqual(self.call(service, "GET", "/v1/nowhere/ZEBRA-SENTINEL-7781")[0], 404)
        body = case_body("key-trace-0003")
        self.assertEqual(self.call(service, "POST", "/v1/jobs", body)[0], 202)
        status, again = self.call(service, "POST", "/v1/jobs", body)
        self.assertEqual(status, 200)
        status, info = self.call(service, "GET", "/v1/status")
        self.flush(service)
        spans = [item for _resource, item in self.receiver.spans()]
        summary = sorted((item["name"], attributes_of(item).get("http.response.status_code")) for item in spans)
        self.assertEqual(summary, [("GET", 404), ("GET /v1/status", 200), ("GET /v1/status", 401),
                                   ("POST /v1/jobs", 200), ("POST /v1/jobs", 202)])
        unknown = next(item for item in spans if item["name"] == "GET")
        self.assertNotIn("http.route", attributes_of(unknown))
        self.assertNotIn(b"ZEBRA-SENTINEL", b"".join(self.receiver.bodies()))
        # The repeated request did not re-parent the job: the job keeps the first request's span.
        first = next(item for item in spans if attributes_of(item).get("http.response.status_code") == 202)
        admission = service["store"].admission(again["job_id"])
        self.assertEqual(parse_traceparent(admission["trace_parent"]), (first["traceId"], first["spanId"]))
        # /v1/status says tracing is on and where it sends, never the key.
        tracing = info["tracing"]
        self.assertEqual((tracing["enabled"], tracing["destination"], tracing["service_name"]),
                         (True, "127.0.0.1", "neuron-flow"))
        self.assertNotIn(HONEYCOMB_KEY, json.dumps(info))
        _status, later = self.call(service, "GET", "/v1/status")
        self.assertGreaterEqual(later["tracing"]["exported_spans"], 4)
        self.assertIsNotNone(later["tracing"]["last_ok_at"])

    def test_nothing_private_is_ever_sent(self):
        service = self.start("privacy")
        status, job = self.call(service, "POST", "/v1/jobs", case_body("key-trace-0004", summary=SECRET_SUMMARY,
                                                                       case_id="CASE-SENTINEL-42"))
        self.assertEqual(status, 202)
        service["runner"].drain()
        _status, view = self.call(service, "GET", f"/v1/jobs/{job['job_id']}")
        _status, events = self.call(service, "GET", f"/v1/jobs/{job['job_id']}/events?limit=100")
        self.flush(service)
        self.assertEqual(len(self.traces()[view["trace_id"]]), 9)  # the scan below has the whole trace to read
        sent = b"".join(self.receiver.bodies()).decode("ascii")  # the encoder only ever writes ASCII
        second = view["result"]["review"]["second_opinion"]
        private = [*SENTINELS, SECRET_SUMMARY, "CASE-SENTINEL-42", second["rationale"],
                   load_prompt("triage_classify_v1").system[:60], KEY, HONEYCOMB_KEY]
        for text in private:
            self.assertNotIn(json.dumps(text)[1:-1], sent, text)  # also as JSON-escaped text
            self.assertNotIn(text, sent, text)
        for _resource, item in self.receiver.spans():
            self.assertLessEqual(set(attributes_of(item)), set(SPAN_ATTRIBUTES), item["name"])
        self.assertTrue(all(request["headers"]["x-honeycomb-team"] == HONEYCOMB_KEY
                            for request in self.receiver.requests))
        self.assertIn("job.queued", [event["kind"] for event in events["events"]])

    def test_turning_tracing_off_changes_no_result(self):
        traced, plain = self.start("traced"), self.start("plain", traced=False)
        results = []
        for service in (traced, plain):
            ids = [self.call(service, "POST", "/v1/jobs", dict(case_body(f"key-same-{n:04d}", summary=summary),
                                                                workflow_type=workflow))[1]["job_id"]
                   for n, (summary, workflow) in enumerate((
                       (SECRET_SUMMARY, "case_triage.v2"), ("My invoice shows a double payment", "case_triage.v2"),
                       ("I cannot sign in to my account", "test.flaky_ai"), ("Need help with something", "case_triage.v1")))]
            service["runner"].drain()
            jobs = [self.call(service, "GET", f"/v1/jobs/{job_id}")[1] for job_id in ids]
            for job in jobs:
                ai = job["result"]["ai"]
                if ai:
                    ai.pop("latency_ms", None)  # measured time differs between any two runs
                job["result"].pop("receipt")   # the receipt holds the job id and that latency
            results.append([(job["status"], job["failure"], job["result"]) for job in jobs])
            events = [self.call(service, "GET", f"/v1/jobs/{job_id}/events?limit=100")[1]["events"] for job_id in ids]
            results[-1].append([[event["kind"] for event in history] for history in events])
        self.assertEqual([status for status, _failure, _result in results[0][:4]], ["REVIEW_REQUIRED"] * 4)
        self.assertEqual(results[0], results[1])
        self.flush(traced)
        self.flush(plain)
        traced_ids = {view["trace_id"] for view in [self.call(traced, "GET", f"/v1/jobs/{job['job_id']}")[1]
                                                    for job in self.call(traced, "GET", "/v1/jobs")[1]["jobs"]]}
        self.assertEqual(len(traced_ids), 4)
        self.assertTrue(traced_ids <= set(self.traces()))
        _status, plain_jobs = self.call(plain, "GET", "/v1/jobs")
        plain_views = [self.call(plain, "GET", f"/v1/jobs/{job['job_id']}")[1] for job in plain_jobs["jobs"]]
        self.assertEqual({view["trace_id"] for view in plain_views}, {None})
        self.assertTrue(all("trace_parent" not in plain["store"].admission(view["job_id"]) for view in plain_views))
        self.assertEqual(self.call(plain, "GET", "/v1/status")[1]["tracing"]["problem"], "not_configured")

    def test_a_trace_that_cannot_be_built_never_touches_the_job(self):
        service = self.start("broken")
        self.assertEqual(self.call(service, "POST", "/v1/jobs", case_body("key-trace-0005"))[0], 202)
        with mock.patch("app.services.runner.job_spans", side_effect=ValueError("case text could be here")), \
                self.assertLogs("neuron_flow.runner", "WARNING") as logs:
            self.assertEqual(service["runner"].drain(), 1)
        (job,) = self.call(service, "GET", "/v1/jobs")[1]["jobs"]
        self.assertEqual(job["status"], "REVIEW_REQUIRED")
        self.assertIn("could not build the trace", "\n".join(logs.output))
        self.assertNotIn("case text could be here", "\n".join(logs.output))  # only the error type is logged


if __name__ == "__main__":
    unittest.main()
