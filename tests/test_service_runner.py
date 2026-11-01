"""The single Runner: queue order, the workspace lock, crash reconciliation and honest failures.

Each test maps to a P0 gate in docs/architecture.md (section 9).
"""

import json
import multiprocessing
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from neuron_flow import Runtime
from neuron_flow.storage import WorkspaceBusy

from app.api.routes import ApiApp, Request
from app.llm import LLMConfig
from app.observability import SentryReporter
from app.persistence import QueueStore
from app.services.admission import admit
from app.services.runner import Runner
from app.services.workflows import CATALOG, agents_for
from tests import service_fixtures
from tests.service_fixtures import KEY, case_body, settings, wait_for
from tests.test_sentry_reporting import StubSdk


class RunnerTestCase(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._temp.name)
        self.settings = settings(self.data_dir)
        self.store = QueueStore(self.settings.queue_db)
        self.store.migrate()
        self.markers = self.data_dir / "markers"
        self.processes = []

    def tearDown(self):
        for process in self.processes:
            if process.is_alive():
                process.kill()
            process.join(10)
        self._temp.cleanup()

    def admit(self, key, catalog=CATALOG, **kwargs):
        job, _created = admit(self.store, case_body(key, **kwargs), max_queued=100, catalog=catalog)
        return job

    def start_runner_process(self, *, sleep_s=60.0, slow_attempts=(1,), max_attempts=2):
        # Not a daemon: the Runner starts Core worker processes of its own. tearDown kills it.
        process = multiprocessing.get_context("spawn").Process(
            target=service_fixtures.run_runner,
            args=(str(self.data_dir), str(self.markers), sleep_s, list(slow_attempts), max_attempts))
        process.start()
        self.processes.append(process)
        return process

    def marker(self, job_id, attempt):
        return self.markers / f"{job_id}.attempt{attempt}"


class QueueProcessingTests(RunnerTestCase):
    def test_jobs_run_in_arrival_order_and_end_waiting_for_a_person(self):
        texts = ["I cannot upload an attachment", "อัปโหลดไฟล์แนบไม่ได้ ค้างที่ 99%", "My invoice shows a double payment"]
        ids = [self.admit(f"key-order-{n}", summary=text, case_id=f"C-{n}")["job_id"] for n, text in enumerate(texts)]
        self.assertEqual(Runner(self.settings, store=self.store).drain(), 3)
        jobs = [self.store.get(job_id) for job_id in ids]
        self.assertEqual([job["status"] for job in jobs], ["REVIEW_REQUIRED"] * 3)
        started = [job["started_at"] for job in jobs]
        self.assertEqual(started, sorted(started))
        for job in jobs:
            review = job["result"]["review"]
            self.assertEqual((review["decision"], review["review_required"], review["mode"]),
                             ("PENDING_HUMAN_REVIEW", True, "shadow"))
            self.assertEqual(job["claims"], 1)
            self.assertIsNotNone(job["spec"])
        self.assertEqual(jobs[1]["result"]["review"]["review_reasons"], ["rules_llm_disagree", "rules_no_keyword_match"])

    def test_rules_only_workflow(self):
        job = self.admit("key-v1-0001", workflow_type="case_triage.v1")
        Runner(self.settings, store=self.store).drain()
        stored = self.store.get(job["job_id"])
        self.assertEqual(stored["status"], "REVIEW_REQUIRED")
        self.assertEqual(stored["result"]["review"]["mode"], "rules_only")
        self.assertEqual(stored["result"]["review"]["suggested_queue"], "upload_review")
        self.assertIsNone(stored["result"]["ai"])

    def test_the_queue_survives_a_restart(self):
        first = self.admit("key-restart-1")
        second = self.admit("key-restart-2", summary="I forgot my password again")
        restarted = QueueStore(self.settings.queue_db)  # a new process would open the same file
        self.assertEqual(Runner(self.settings, store=restarted).drain(), 2)
        self.assertEqual({restarted.get(first["job_id"])["status"], restarted.get(second["job_id"])["status"]},
                         {"REVIEW_REQUIRED"})

    def test_a_failed_validator_blocks_only_the_steps_that_depend_on_it(self):
        catalog = service_fixtures.branches_catalog()
        job = self.admit("key-branches-1", catalog=catalog, workflow_type="test.branches")
        Runner(self.settings, store=self.store, catalog=catalog).drain()
        stored = self.store.get(job["job_id"])
        steps = {step["id"]: (step["status"], step["error_type"]) for step in stored["result"]["steps"]}
        self.assertEqual(steps, {"bad": ("FAILED", "OutputValidationError"), "after_bad": ("BLOCKED", "DependencyFailed"),
                                 "good": ("SUCCEEDED", None), "after_good": ("SUCCEEDED", None)})
        self.assertEqual(stored["status"], "FAILED")
        self.assertEqual(stored["failure"], {"reason": "step_failed", "failed_steps": ["bad"],
                                             "error_types": ["OutputValidationError"]})

    def test_a_delivery_conflict_gets_its_own_status(self):
        job = self.admit("key-delivery-1")
        reports = self.settings.core_dir / "reports"
        reports.mkdir(parents=True)
        (reports / f"{job['job_id']}.json").write_text('{"someone": "else"}\n', encoding="utf-8")
        Runner(self.settings, store=self.store).drain()
        stored = self.store.get(job["job_id"])
        self.assertEqual((stored["status"], stored["failure"]), ("DELIVERY_FAILED", {"reason": "delivery_failed"}))
        self.assertEqual({step["status"] for step in stored["result"]["steps"]}, {"SUCCEEDED"})

    def test_ai_settings_that_cannot_work_keep_jobs_queued(self):
        job = self.admit("key-blocked-1")
        config = LLMConfig(provider="anthropic", model="claude-haiku-5-5")
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            runner = Runner(self.settings, store=self.store, llm_config=config)
            thread = threading.Thread(target=runner.serve)
            thread.start()
            try:
                info = wait_for(lambda: (self.store.runner() or {}).get("state") == "blocked_config" and self.store.runner())
                self.assertIn("ANTHROPIC_API_KEY", info["detail"])
                time.sleep(0.3)
                self.assertEqual(self.store.get(job["job_id"])["status"], "QUEUED")
            finally:
                runner.stop_event.set()
                thread.join(10)
        self.assertEqual(self.store.runner()["state"], "stopped")


class LockTests(RunnerTestCase):
    def test_only_one_runner_can_own_the_workspace(self):
        self.admit("key-lock-1")
        config = LLMConfig()
        with Runtime(self.settings.core_dir, agents=agents_for(CATALOG, config)):
            with self.assertRaises(WorkspaceBusy):
                Runner(self.settings, store=self.store, llm_config=config).serve()
        self.assertIsNone(self.store.runner())  # the refused Runner wrote no heartbeat
        self.assertEqual(self.store.counts()["QUEUED"], 1)


class ReconciliationTests(RunnerTestCase):
    def test_admission_stays_responsive_while_a_job_runs(self):
        catalog = service_fixtures.slow_catalog(self.markers, sleep_s=60)
        slow = self.admit("key-busy-1", catalog=catalog, workflow_type="test.slow")
        self.start_runner_process(sleep_s=60)
        wait_for(lambda: self.marker(slow["job_id"], 1).exists())
        app = ApiApp(self.settings, self.store, catalog=catalog)
        started = time.monotonic()
        response = app.handle(Request("POST", "/v1/jobs", {}, {"content-type": "application/json",
                                                              "authorization": f"Bearer {KEY}"},
                                      json.dumps(case_body("key-busy-2")).encode(), "tester"))
        self.assertEqual(response.status, 202)
        self.assertLess(time.monotonic() - started, 1.0)
        status = json.loads(app.handle(Request("GET", "/v1/status", {}, {"authorization": f"Bearer {KEY}"})).body)
        self.assertEqual((status["runner"]["alive"], status["runner"]["state"], status["runner"]["current_job"]),
                         (True, "running", slow["job_id"]))

    def test_a_runner_killed_mid_step_is_recovered_within_the_retry_budget(self):
        catalog = service_fixtures.slow_catalog(self.markers, sleep_s=60, max_attempts=2)
        job = self.admit("key-kill-1", catalog=catalog, workflow_type="test.slow")
        process = self.start_runner_process(sleep_s=60, max_attempts=2)
        wait_for(lambda: self.marker(job["job_id"], 1).exists())
        process.kill()  # no clean shutdown: the step is left RUNNING in Core and in the queue
        process.join(10)
        self.assertEqual(self.store.get(job["job_id"])["status"], "RUNNING")
        sdk = StubSdk()
        Runner(self.settings, store=self.store, catalog=catalog, llm_config=LLMConfig(),
               reporter=SentryReporter(sdk=sdk)).drain()
        (event,) = sdk.events
        self.assertEqual((event["level"], event["tags"]["neuron_flow.recovery_outcome"]), ("warning", "resumed"))
        self.assertEqual(event["context"], {"job_id": job["job_id"], "claims": 2, "outcome": "resumed"})
        stored = self.store.get(job["job_id"])
        self.assertEqual(stored["status"], "COMPLETED")
        self.assertEqual(stored["result"]["output"], {"ok": True, "attempt": 2})
        (step,) = stored["result"]["steps"]
        self.assertEqual((step["status"], step["attempts"], step["max_attempts"]), ("SUCCEEDED", 2, 2))
        self.assertEqual(stored["claims"], 2)
        kinds = [event["kind"] for event in self.store.events(job["job_id"], limit=100)[0]]
        self.assertIn("job.recovering", kinds)
        self.assertTrue(self.marker(job["job_id"], 2).exists())

    def test_no_retry_budget_left_means_a_clear_failure(self):
        catalog = service_fixtures.slow_catalog(self.markers, sleep_s=60, max_attempts=1)
        job = self.admit("key-kill-2", catalog=catalog, workflow_type="test.slow")
        process = self.start_runner_process(sleep_s=60, max_attempts=1)
        wait_for(lambda: self.marker(job["job_id"], 1).exists())
        process.kill()
        process.join(10)
        Runner(self.settings, store=self.store, catalog=catalog, llm_config=LLMConfig()).drain()
        stored = self.store.get(job["job_id"])
        self.assertEqual(stored["status"], "FAILED")
        self.assertEqual(stored["failure"]["error_types"], ["ControllerInterrupted"])
        self.assertEqual(stored["result"]["steps"][0]["attempts"], 1)
        self.assertFalse(self.marker(job["job_id"], 2).exists())  # never ran a second time

    def test_changed_ai_settings_never_finish_an_interrupted_job_silently(self):
        old, new = LLMConfig(model="mock-keyword-1"), LLMConfig(model="mock-keyword-2")
        for key, submitted_to_core in (("key-config-1", True), ("key-config-2", False)):
            job = self.admit(key)
            claimed = self.store.claim_next("old-runner")
            self.assertEqual(claimed["job_id"], job["job_id"])
            spec = CATALOG["case_triage.v2"].build_spec(job["job_id"], job["input"], old)
            self.store.freeze_spec(job["job_id"], spec)
            if submitted_to_core:
                with Runtime(self.settings.core_dir, agents=agents_for(CATALOG, old)) as runtime:
                    runtime.submit(spec)
            Runner(self.settings, store=self.store, llm_config=new).drain()
            stored = self.store.get(job["job_id"])
            self.assertEqual((stored["status"], stored["failure"]["reason"]), ("FAILED", "configuration_changed"), key)

    def test_a_job_that_keeps_stopping_the_runner_is_eventually_failed(self):
        job = self.admit("key-poison-1")
        self.store.claim_next("runner-a")
        self.store.reclaim(job["job_id"], "runner-b")
        self.store.reclaim(job["job_id"], "runner-c")
        sdk = StubSdk()
        Runner(settings(self.data_dir, max_claims=3), store=self.store, reporter=SentryReporter(sdk=sdk)).drain()
        stored = self.store.get(job["job_id"])
        self.assertEqual(stored["status"], "FAILED")
        self.assertEqual(stored["failure"], {"reason": "runner_attempts_exhausted", "claims": 3})
        (event,) = sdk.events
        self.assertEqual((event["level"], event["fingerprint"]),
                         ("error", ["neuron-flow", "job-recovered", "runner_attempts_exhausted"]))
        self.assertNotIn("upload", json.dumps(event))  # no case text leaves the system

    def test_a_job_finished_in_core_before_the_crash_is_not_run_again(self):
        job = self.admit("key-finished-1")
        self.store.claim_next("old-runner")
        config = LLMConfig()
        spec = CATALOG["case_triage.v2"].build_spec(job["job_id"], job["input"], config)
        self.store.freeze_spec(job["job_id"], spec)
        with Runtime(self.settings.core_dir, agents=agents_for(CATALOG, config)) as runtime:
            runtime.submit(spec)
            receipt = runtime.run(job["job_id"])["receipt"]
        # The crash happened here: Core finished, the queue still says RUNNING.
        Runner(self.settings, store=self.store, llm_config=config).drain()
        stored = self.store.get(job["job_id"])
        self.assertEqual(stored["status"], "REVIEW_REQUIRED")
        self.assertEqual(stored["result"]["receipt"]["sha256"], receipt["sha256"])
        self.assertEqual({step["attempts"] for step in stored["result"]["steps"]}, {1})


if __name__ == "__main__":
    unittest.main()
