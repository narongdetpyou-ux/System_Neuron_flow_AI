"""Queue and run-time figures on the status page (roadmap 5.3).

Most tests drive the queue directly with chosen timestamps, so every expected number can be worked out
by hand. One test runs a real case through the Runner and checks what the API shows.
"""

import json
import tempfile
import unittest
from pathlib import Path

from app.api.routes import ApiApp, Request
from app.persistence import QueueStore
from app.services.metrics import WINDOW, queue_metrics
from app.services.runner import Runner
from tests.service_fixtures import KEY, case_body, settings

AUTH = {"authorization": f"Bearer {KEY}"}
JSON = {"content-type": "application/json", **AUTH}


class MetricsTestCase(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.settings = settings(Path(self._temp.name))
        self.store = QueueStore(self.settings.queue_db)
        self.store.migrate()
        self.number = 0

    def tearDown(self):
        self._temp.cleanup()

    def status(self, now):
        app = ApiApp(self.settings, self.store, clock=lambda: now)
        response = app.handle(Request("GET", "/v1/status", {}, dict(AUTH), b"", "tester"))
        self.assertEqual(response.status, 200)
        return json.loads(response.body)

    def admit(self, at, workflow_type="case_triage.v2"):
        self.number += 1
        job, created = self.store.admit(
            job_id=f"job_{self.number:024x}", idempotency_key=f"key-metrics-{self.number:04d}",
            request_fingerprint=f"fingerprint-{self.number}", workflow_type=workflow_type,
            input={"case_id": f"CASE-{self.number}", "summary": "Synthetic case for the metrics tests"},
            max_queued=50, now=at)
        self.assertTrue(created)
        return job["job_id"]

    def ran(self, admitted, claimed, finished, status="REVIEW_REQUIRED", *, workflow_type="case_triage.v2",
            failure=None, reclaimed=None):
        """One job from admission to outcome, at the given times. Only one job waits at a time here, so
        ``claim_next`` always takes this one."""
        job_id = self.admit(admitted, workflow_type)
        self.assertEqual(self.store.claim_next("runner-test", now=claimed)["job_id"], job_id)
        if reclaimed is not None:  # a Runner stop: a new Runner takes the job over
            self.store.reclaim(job_id, "runner-test-2", now=reclaimed)
        self.store.finish(job_id, status, failure=failure, now=finished)
        return job_id


class WaitingTests(MetricsTestCase):
    def test_an_empty_queue_has_zero_waiting_and_no_timings(self):
        self.assertEqual(self.status(now=1000.0)["metrics"], {
            "waiting": {"count": 0, "oldest_age_s": None},
            "window": {"limit": WINDOW, "jobs": 0},
            "workflows": {},
            "failures": {},
        })

    def test_waiting_count_and_oldest_age_follow_the_queue(self):
        first = self.admit(1000.0)
        second = self.admit(1010.0)
        self.assertEqual(self.status(now=1030.0)["metrics"]["waiting"], {"count": 2, "oldest_age_s": 30.0})
        self.assertEqual(self.store.claim_next("runner-test", now=1031.0)["job_id"], first)
        # The oldest *waiting* job is now the second one; the running one no longer counts.
        self.assertEqual(self.status(now=1040.0)["metrics"]["waiting"], {"count": 1, "oldest_age_s": 30.0})
        self.store.cancel(second, now=1041.0)
        self.assertEqual(self.status(now=1050.0)["metrics"]["waiting"], {"count": 0, "oldest_age_s": None})

    def test_a_clock_that_stepped_back_never_gives_a_negative_age(self):
        self.admit(2000.0)
        self.assertEqual(self.status(now=1990.0)["metrics"]["waiting"], {"count": 1, "oldest_age_s": 0.0})


class TimingTests(MetricsTestCase):
    def test_wait_and_run_times_per_workflow_with_failures_by_reason(self):
        # case_triage.v2: waits 1, 0.25, 2, 1 and runs 0.5, 2, 16, 0.75 (seconds).
        self.ran(0.0, 1.0, 1.5)
        self.ran(2.0, 2.25, 4.25, "FAILED", failure={"reason": "step_failed", "failed_steps": ["classify_llm"]})
        self.ran(5.0, 7.0, 23.0, reclaimed=20.0)  # the Runner stopped; a new one took it over at 20
        self.ran(30.0, 31.0, 31.75, "FAILED", failure={"reason": "configuration_changed"})
        # case_triage.v1: one job, wait 0.5, run 0.125.
        self.ran(40.0, 40.5, 40.625, workflow_type="case_triage.v1")
        # Never ran, so never timed: a cancelled job, and one still waiting.
        self.store.cancel(self.admit(50.0), now=51.0)
        self.admit(60.0)

        metrics = self.status(now=70.0)["metrics"]
        self.assertEqual(metrics["waiting"], {"count": 1, "oldest_age_s": 10.0})
        self.assertEqual(metrics["window"], {"limit": WINDOW, "jobs": 5})
        self.assertEqual(metrics["workflows"], {
            "case_triage.v1": {"jobs": 1, "recovered": 0, "wait_s": {"median": 0.5, "max": 0.5},
                               "run_s": {"median": 0.125, "max": 0.125}},
            "case_triage.v2": {"jobs": 4, "recovered": 1, "wait_s": {"median": 1.0, "max": 2.0},
                               "run_s": {"median": 1.375, "max": 16.0}},
        })
        # Ties are listed in name order, so the order never changes between two requests.
        self.assertEqual(list(metrics["failures"].items()), [("configuration_changed", 1), ("step_failed", 1)])

    def test_failures_are_listed_most_frequent_first(self):
        for at in (0.0, 10.0):
            self.ran(at, at + 1, at + 2, "FAILED", failure={"reason": "step_failed"})
        self.ran(20.0, 21.0, 22.0, "DELIVERY_FAILED", failure={"reason": "delivery_failed"})
        self.ran(30.0, 31.0, 32.0, "FAILED")  # a failure without a recorded reason is still counted
        metrics = self.status(now=40.0)["metrics"]
        self.assertEqual(list(metrics["failures"].items()),
                         [("step_failed", 2), ("delivery_failed", 1), ("unknown", 1)])

    def test_only_the_newest_jobs_in_the_window_count(self):
        self.ran(0.0, 1.0, 101.0)  # the oldest: 100 s, outside a window of two
        self.ran(200.0, 201.0, 202.0)
        self.ran(300.0, 301.0, 303.0)
        metrics = queue_metrics(self.store, 400.0, window=2)
        self.assertEqual(metrics["window"], {"limit": 2, "jobs": 2})
        self.assertEqual(metrics["workflows"]["case_triage.v2"]["run_s"], {"median": 1.5, "max": 2.0})


class LiveRunTests(MetricsTestCase):
    def test_a_real_run_shows_up_without_case_text_or_job_ids(self):
        app = ApiApp(self.settings, self.store)
        summary = "Metrics check: I cannot upload an attachment"
        response = app.handle(Request("POST", "/v1/jobs", {}, dict(JSON),
                                      json.dumps(case_body("key-metrics-live", summary=summary)).encode(), "tester"))
        job_id = json.loads(response.body)["job_id"]
        Runner(self.settings, store=self.store).drain()
        status = json.loads(app.handle(Request("GET", "/v1/status", {}, dict(AUTH), b"", "tester")).body)
        metrics = status["metrics"]
        timing = metrics["workflows"]["case_triage.v2"]
        self.assertEqual((timing["jobs"], timing["recovered"], metrics["failures"]), (1, 0, {}))
        self.assertGreater(timing["run_s"]["max"], 0)
        self.assertGreaterEqual(timing["wait_s"]["max"], 0)
        text = json.dumps(metrics, ensure_ascii=False)
        for secret in (summary, "upload", job_id, "CASE-1", KEY):
            self.assertNotIn(secret, text)


if __name__ == "__main__":
    unittest.main()
