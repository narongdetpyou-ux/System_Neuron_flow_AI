"""Intake API: admission rules, access control, limits and the read routes (no sockets needed)."""

import json
import tempfile
import threading
import unittest
from pathlib import Path

from neuron_flow import Runtime
from neuron_flow.model import normalize_spec

from app.api.routes import MAX_BODY_BYTES, ApiApp, Request
from app.llm import LLMConfig
from app.persistence import QueueStore, StateError
from app.services.admission import admit
from app.services.results import plan_view
from app.services.runner import Runner
from app.services.workflows import CATALOG, WorkflowType, agents_for, check_case, preview_spec
from tests.service_fixtures import KEY, case_body, settings, slow_catalog

AUTH = {"authorization": f"Bearer {KEY}"}
JSON = {"content-type": "application/json", **AUTH}


def post(app, body, *, headers=None, client="tester", raw=None):
    data = raw if raw is not None else json.dumps(body).encode("utf-8")
    return app.handle(Request("POST", "/v1/jobs", {}, dict(JSON if headers is None else headers), data, client))


def get(app, path, query=None, *, headers=None, client="tester", method="GET"):
    return app.handle(Request(method, path, query or {}, dict(AUTH if headers is None else headers), b"", client))


def body_of(response):
    return json.loads(response.body)


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._temp.name)
        self.settings = settings(self.data_dir)
        self.store = QueueStore(self.settings.queue_db)
        self.store.migrate()
        self.app = ApiApp(self.settings, self.store)

    def tearDown(self):
        self._temp.cleanup()

    def jobs_in_store(self):
        return self.store.list_jobs(limit=100)[0]


class AdmissionTests(ApiTestCase):
    def test_a_valid_request_is_stored_before_the_202_reply(self):
        response = post(self.app, case_body("key-0000001", summary="  I cannot upload an attachment  "))
        self.assertEqual(response.status, 202)
        job = body_of(response)
        self.assertEqual((job["status"], job["created"], job["queue_position"]), ("QUEUED", True, 1))
        self.assertIn(("Location", f"/v1/jobs/{job['job_id']}"), response.headers)
        stored = self.store.get(job["job_id"])
        self.assertEqual(stored["status"], "QUEUED")
        self.assertEqual(stored["input"]["summary"], "I cannot upload an attachment")  # normalized

    def test_the_same_key_and_request_returns_the_same_job(self):
        first = body_of(post(self.app, case_body("key-0000002")))
        again = post(self.app, case_body("key-0000002"))
        self.assertEqual(again.status, 200)
        self.assertEqual((body_of(again)["job_id"], body_of(again)["created"]), (first["job_id"], False))
        self.assertEqual(len(self.jobs_in_store()), 1)

    def test_the_same_key_with_a_different_request_is_a_conflict(self):
        first = body_of(post(self.app, case_body("key-0000003")))
        conflict = post(self.app, case_body("key-0000003", summary="A different problem entirely"))
        self.assertEqual(conflict.status, 409)
        self.assertEqual(body_of(conflict)["error"], "idempotency_conflict")
        self.assertEqual(body_of(conflict)["job_id"], first["job_id"])
        self.assertEqual(len(self.jobs_in_store()), 1)

    def test_concurrent_identical_requests_create_exactly_one_job(self):
        barrier = threading.Barrier(16)
        statuses, job_ids = [], set()
        lock = threading.Lock()

        def submit():
            barrier.wait()
            response = post(self.app, case_body("key-concurrent"))
            with lock:
                statuses.append(response.status)
                job_ids.add(body_of(response)["job_id"])

        threads = [threading.Thread(target=submit) for _ in range(16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(statuses), [200] * 15 + [202])
        self.assertEqual(len(job_ids), 1)
        self.assertEqual(len(self.jobs_in_store()), 1)

    def test_concurrent_mismatched_requests_get_conflicts_not_new_jobs(self):
        barrier = threading.Barrier(8)
        statuses = []
        lock = threading.Lock()

        def submit(index):
            barrier.wait()
            response = post(self.app, case_body("key-mismatch", summary=f"Problem number {index} happened"))
            with lock:
                statuses.append(response.status)

        threads = [threading.Thread(target=submit, args=(index,)) for index in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(statuses), [202] + [409] * 7)
        self.assertEqual(len(self.jobs_in_store()), 1)

    def test_invalid_requests_are_refused_before_any_job_exists(self):
        cases = {
            "invalid_input": case_body("key-0000004", summary="short"),
            "invalid_fields": {**case_body("key-0000005"), "steps": [{"id": "x", "agent": "triage.classify"}]},
            "unknown_workflow_type": case_body("key-0000006", workflow_type="shell.exec"),
            "invalid_idempotency_key": case_body("short"),
        }
        bad_case_id = case_body("key-0000007")
        bad_case_id["input"]["case_id"] = "../etc/passwd"
        cases["invalid_input_case_id"] = bad_case_id
        extra_input = case_body("key-0000008")
        extra_input["input"]["agent"] = "app.evil:run"
        cases["invalid_input_extra"] = extra_input
        for label, body in cases.items():
            response = post(self.app, body)
            self.assertEqual(response.status, 400, label)
            self.assertEqual(body_of(response)["error"], label.split("_case_id")[0].split("_extra")[0], label)
        self.assertEqual(post(self.app, None, raw=b"{not json").status, 400)
        duplicated = b'{"workflow_type":"case_triage.v2","workflow_type":"case_triage.v1"}'
        self.assertEqual(body_of(post(self.app, None, raw=duplicated))["error"], "invalid_json")
        self.assertEqual(self.jobs_in_store(), [])

    def test_wrong_content_type_and_oversized_bodies(self):
        plain = {"content-type": "text/plain", **AUTH}
        self.assertEqual(post(self.app, case_body("key-0000009"), headers=plain).status, 415)
        huge = json.dumps(case_body("key-0000010", summary="x" * (MAX_BODY_BYTES + 10))).encode()
        self.assertEqual(post(self.app, None, raw=huge).status, 413)
        self.assertEqual(self.jobs_in_store(), [])

    def test_submissions_are_rate_limited_per_client(self):
        app = ApiApp(settings(self.data_dir, submit_per_minute=3), self.store)
        statuses = [post(app, case_body(f"key-rate-{n:04d}"), client="busy").status for n in range(4)]
        self.assertEqual(statuses, [202, 202, 202, 429])
        limited = post(app, case_body("key-rate-9999"), client="busy")
        self.assertIn("Retry-After", dict(limited.headers))
        self.assertEqual(post(app, case_body("key-rate-other"), client="calm").status, 202)

    def test_a_full_queue_refuses_new_jobs_but_still_answers_duplicates(self):
        app = ApiApp(settings(self.data_dir, max_queued=2), self.store)
        self.assertEqual(post(app, case_body("key-full-0001")).status, 202)
        self.assertEqual(post(app, case_body("key-full-0002")).status, 202)
        full = post(app, case_body("key-full-0003"))
        self.assertEqual((full.status, body_of(full)["error"]), (503, "queue_full"))
        self.assertEqual(post(app, case_body("key-full-0001")).status, 200)


class AccessTests(ApiTestCase):
    def test_every_v1_route_needs_the_key(self):
        for path in ("/v1/status", "/v1/jobs", "/v1/jobs/job_000000000000000000000000", "/v1/nothing"):
            self.assertEqual(get(self.app, path, headers={}).status, 401, path)
            wrong = get(self.app, path, headers={"authorization": "Bearer wrong-key-but-long-enough"}, client=path)
            self.assertEqual(wrong.status, 401, path)
        self.assertEqual(post(self.app, case_body("key-0000011"), headers={"content-type": "application/json"}).status, 401)
        self.assertEqual(self.jobs_in_store(), [])

    def test_repeated_wrong_keys_are_slowed_down_per_client(self):
        wrong = {"authorization": "Bearer wrong-key-but-long-enough"}
        statuses = [get(self.app, "/v1/status", headers=wrong, client="guesser").status for _ in range(11)]
        self.assertEqual(statuses, [401] * 10 + [429])
        self.assertEqual(get(self.app, "/v1/status", client="guesser").status, 429)  # even the right key waits
        self.assertEqual(get(self.app, "/v1/status", client="owner").status, 200)

    def test_without_a_configured_key_the_api_explains_what_to_do(self):
        app = ApiApp(settings(self.data_dir, access_key=None, access_key_problem="missing"), self.store)
        response = get(app, "/v1/status")
        self.assertEqual(response.status, 503)
        self.assertEqual((body_of(response)["error"], body_of(response)["problem"]), ("access_key_not_configured", "missing"))
        health = get(app, "/healthz", headers={})
        self.assertEqual((health.status, body_of(health)), (200, {"ok": True, "access_key": "not_configured"}))
        self.assertEqual(body_of(get(self.app, "/healthz", headers={}))["access_key"], "configured")
        self.assertEqual(get(app, "/", headers={}).status, 200)

    def test_the_key_is_never_in_a_response_or_a_stored_file(self):
        job = body_of(post(self.app, case_body("key-0000012")))
        Runner(self.settings, store=self.store).drain()
        responses = [get(self.app, "/v1/status"), get(self.app, "/v1/jobs"), get(self.app, f"/v1/jobs/{job['job_id']}"),
                     get(self.app, f"/v1/jobs/{job['job_id']}/events"), get(self.app, "/", headers={})]
        for response in responses:
            self.assertNotIn(KEY.encode(), response.body)
        for path in self.data_dir.rglob("*"):
            if path.is_file():
                self.assertNotIn(KEY.encode(), path.read_bytes(), str(path))
        self.assertNotIn(KEY, repr(self.settings))


class ReadRouteTests(ApiTestCase):
    def test_job_detail_after_the_runner_has_no_internal_paths(self):
        job = body_of(post(self.app, case_body("key-0000013", summary="อัปโหลดไฟล์แนบไม่ได้ ค้างที่ 99%")))
        Runner(self.settings, store=self.store).drain()
        response = get(self.app, f"/v1/jobs/{job['job_id']}")
        self.assertEqual(response.status, 200)
        detail = body_of(response)
        self.assertEqual(detail["status"], "REVIEW_REQUIRED")
        review = detail["result"]["review"]
        self.assertEqual((review["decision"], review["review_required"]), ("PENDING_HUMAN_REVIEW", True))
        self.assertEqual((review["agreement"], review["review_priority"]), ("disagree", "elevated"))
        self.assertEqual(detail["result"]["ai"]["provider"], "mock")
        self.assertEqual(set(detail["result"]["receipt"]), {"sha256", "bytes"})
        self.assertNotIn(str(self.data_dir).encode(), response.body)
        self.assertNotIn(b"/reports/", response.body)

    def test_listing_is_newest_first_with_a_cursor(self):
        ids = [body_of(post(self.app, case_body(f"key-list-{n:04d}", case_id=f"C-{n}")))["job_id"] for n in range(5)]
        seen, before = [], None
        while True:
            query = {"limit": ["2"]} if before is None else {"limit": ["2"], "before": [str(before)]}
            page = body_of(get(self.app, "/v1/jobs", query))
            seen += [job["job_id"] for job in page["jobs"]]
            self.assertTrue(all("input" not in job and "summary_preview" in job for job in page["jobs"]))
            before = page["next_before"]
            if before is None:
                break
        self.assertEqual(seen, list(reversed(ids)))

    def test_events_come_in_bounded_pages(self):
        job = body_of(post(self.app, case_body("key-0000014")))
        Runner(self.settings, store=self.store).drain()
        kinds, after = [], 0
        while True:
            page = body_of(get(self.app, f"/v1/jobs/{job['job_id']}/events", {"after": [str(after)], "limit": ["2"]}))
            self.assertLessEqual(len(page["events"]), 2)
            kinds += [event["kind"] for event in page["events"]]
            after = page["next_after"]
            if not page["has_more"]:
                break
        self.assertEqual(kinds[:2], ["job.queued", "job.claimed"])
        self.assertEqual(kinds[-1], "job.review_required")
        self.assertEqual(kinds.count("step.succeeded"), 4)
        for bad in ({"limit": ["0"]}, {"limit": ["101"]}, {"after": ["-1"]}, {"limit": ["ten"]}):
            self.assertEqual(get(self.app, f"/v1/jobs/{job['job_id']}/events", bad).status, 400, bad)

    def test_unknown_jobs_routes_and_methods(self):
        self.assertEqual(get(self.app, "/v1/jobs/job_000000000000000000000000").status, 404)
        self.assertEqual(get(self.app, "/v1/jobs/../../etc/passwd").status, 404)
        self.assertEqual(get(self.app, "/nothing", headers={}).status, 404)
        not_allowed = get(self.app, "/v1/status", method="POST")
        self.assertEqual(not_allowed.status, 405)
        self.assertIn(("Allow", "GET, HEAD"), not_allowed.headers)
        self.assertEqual(get(self.app, "/v1/jobs", method="DELETE").status, 405)

    def test_status_reports_runner_queue_ai_and_storage(self):
        before = body_of(get(self.app, "/v1/status"))
        self.assertEqual((before["runner"]["alive"], before["runner"]["state"]), (False, "unknown"))
        post(self.app, case_body("key-0000015"))
        Runner(self.settings, store=self.store).drain()
        status = body_of(get(self.app, "/v1/status"))
        self.assertEqual(status["runner"]["state"], "stopped")
        self.assertFalse(status["runner"]["alive"])
        self.assertEqual(status["queue"]["REVIEW_REQUIRED"], 1)
        self.assertEqual((status["ai"]["provider"], status["ai"]["simulated"]), ("mock", True))
        self.assertEqual(status["storage"], {"kind": "configured", "persistent": True})
        self.assertEqual(status["default_workflow"], "case_triage.v2")

    def test_status_describes_each_workflows_steps_without_params(self):
        plans = {w["name"]: w["steps"] for w in body_of(get(self.app, "/v1/status"))["workflows"]}
        v2 = plans["case_triage.v2"]
        self.assertEqual([step["id"] for step in v2], ["classify_rules", "classify_llm", "compare", "prepare"])
        self.assertEqual([step["depends_on"] for step in v2],
                         [[], [], ["classify_rules", "classify_llm"], ["compare"]])
        self.assertEqual([step["max_attempts"] for step in v2], [1, 2, 1, 1])
        self.assertEqual(v2[0]["timeout_s"], 5)  # Core's default when a step names none
        self.assertGreater(v2[1]["timeout_s"], 5)  # the AI step waits longer than its HTTP timeout
        self.assertEqual([(step["id"], step["agent"]) for step in plans["case_triage.v1"]],
                         [("classify", "triage.classify"), ("prepare", "triage.prepare")])
        for steps in plans.values():
            for step in steps:
                self.assertEqual(set(step), {"id", "agent", "depends_on", "max_attempts", "timeout_s"})
        self.assertEqual(self.jobs_in_store(), [])  # describing a workflow admits nothing

    def test_job_detail_shows_the_plan_frozen_at_claim_without_params(self):
        marker_dir = self.data_dir / "markers"
        app = ApiApp(self.settings, self.store, catalog=slow_catalog(marker_dir, sleep_s=0.01))
        job = body_of(post(app, case_body("key-0000016", workflow_type="test.slow")))
        self.assertIsNone(body_of(get(app, f"/v1/jobs/{job['job_id']}"))["plan"])  # not frozen while queued
        self.assertNotIn("plan", body_of(get(app, "/v1/jobs"))["jobs"][0])  # the list stays small
        Runner(self.settings, store=self.store, catalog=slow_catalog(marker_dir, sleep_s=0.01)).drain()
        response = get(app, f"/v1/jobs/{job['job_id']}")
        self.assertEqual(body_of(response)["plan"], [{"id": "slow", "agent": "test.slow", "depends_on": [],
                                                      "max_attempts": 2, "timeout_s": 30.01}])
        # The frozen spec's params hold a folder path here; neither the params nor the path may leak.
        self.assertNotIn(b"marker_dir", response.body)
        self.assertNotIn(str(marker_dir).encode(), response.body)

    def test_status_still_answers_when_a_workflow_cannot_be_described(self):
        def broken(_job_id, _case, _config):
            raise ValueError("this workflow cannot build a spec")

        catalog = {"broken.v1": WorkflowType("broken.v1", "test only: cannot build", "x", check_case, broken,
                                             lambda _config: []), **CATALOG}
        app = ApiApp(self.settings, self.store, catalog=catalog)
        with self.assertLogs("neuron_flow.api", level="WARNING"):
            response = get(app, "/v1/status")
        self.assertEqual(response.status, 200)
        plans = {w["name"]: w["steps"] for w in body_of(response)["workflows"]}
        self.assertIsNone(plans["broken.v1"])
        self.assertEqual(len(plans["case_triage.v2"]), 4)

    def test_page_and_assets_carry_security_headers(self):
        page = get(self.app, "/", headers={})
        headers = dict(page.headers)
        self.assertEqual(page.status, 200)
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
        self.assertNotIn("unsafe-inline", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertIn(b"Neuron Flow", page.body)
        for path, kind in (("/static/app.js", "text/javascript"), ("/static/app.css", "text/css")):
            asset = get(self.app, path, headers={})
            self.assertEqual(asset.status, 200)
            self.assertTrue(dict(asset.headers)["Content-Type"].startswith(kind))
        self.assertEqual(get(self.app, "/static/../routes.py", headers={}).status, 404)
        self.assertEqual(dict(get(self.app, "/v1/status").headers)["Cache-Control"], "no-store")


def cancel(app, job_id, *, body=b"", headers=None):
    return app.handle(Request("POST", f"/v1/jobs/{job_id}/cancel", {}, dict(JSON if headers is None else headers),
                              body, "tester"))


class CancelTests(ApiTestCase):
    """Roadmap 1.3: withdraw a job before the Runner takes it."""

    def admitted(self, key, **case):
        return body_of(post(self.app, case_body(key, **case)))["job_id"]

    def test_a_queued_job_is_cancelled_once_and_the_repeat_is_a_no_op(self):
        job_id = self.admitted("key-cancel-01")
        first = cancel(self.app, job_id)
        self.assertEqual(first.status, 200)
        view = body_of(first)
        self.assertEqual((view["status"], view["changed"]), ("CANCELLED", True))
        self.assertIsNotNone(view["finished_at"])
        again = cancel(self.app, job_id, body=b"{}")
        self.assertEqual((again.status, body_of(again)["changed"], body_of(again)["status"]), (200, False, "CANCELLED"))
        self.assertEqual(body_of(again)["updated_at"], view["updated_at"])  # nothing was written the second time
        events = self.store.events(job_id)[0]
        self.assertEqual([event["kind"] for event in events], ["job.queued", "job.cancelled"])
        self.assertRegex(events[1]["payload"]["request_id"], r"^req_[0-9a-f]{16}$")  # who cancelled (roadmap 1.2)
        self.assertEqual(dict(first.headers)["X-Request-Id"], events[1]["payload"]["request_id"])
        self.assertEqual(self.store.counts()["CANCELLED"], 1)
        # The idempotency key stays taken: the same submission returns the cancelled job, never a new one.
        repeat = post(self.app, case_body("key-cancel-01"))
        self.assertEqual((repeat.status, body_of(repeat)["job_id"], body_of(repeat)["status"]),
                         (200, job_id, "CANCELLED"))
        self.assertEqual(len(self.jobs_in_store()), 1)

    def test_only_queued_jobs_can_be_cancelled(self):
        running = self.admitted("key-cancel-02")
        self.assertEqual(self.store.claim_next("runner-test")["job_id"], running)
        refused = cancel(self.app, running)
        self.assertEqual((refused.status, body_of(refused)["error"], body_of(refused)["job_status"]),
                         (409, "not_cancellable", "RUNNING"))
        self.assertEqual(self.store.get(running)["status"], "RUNNING")

    def test_a_finished_job_cannot_be_cancelled(self):
        job_id = self.admitted("key-cancel-03")
        Runner(self.settings, store=self.store).drain()
        refused = cancel(self.app, job_id)
        self.assertEqual((refused.status, body_of(refused)["job_status"]), (409, "REVIEW_REQUIRED"))

    def test_bad_cancel_requests_are_refused(self):
        job_id = self.admitted("key-cancel-04")
        self.assertEqual(cancel(self.app, "job_0123456789abcdef01234567").status, 404)
        self.assertEqual(cancel(self.app, job_id, body=b'{"reason": "x"}').status, 400)
        self.assertEqual(cancel(self.app, job_id, body=b"not json").status, 400)
        self.assertEqual(cancel(self.app, job_id, body=b"{}", headers=AUTH).status, 415)
        self.assertEqual(cancel(self.app, job_id, headers={}).status, 401)
        wrong_method = get(self.app, f"/v1/jobs/{job_id}/cancel")
        self.assertEqual((wrong_method.status, dict(wrong_method.headers)["Allow"]), (405, "POST"))
        self.assertEqual(self.store.get(job_id)["status"], "QUEUED")  # none of these changed anything

    def test_a_cancelled_job_never_reaches_core(self):
        withdrawn = self.admitted("key-cancel-05")
        kept = self.admitted("key-cancel-06", case_id="CASE-2")
        self.assertEqual(cancel(self.app, withdrawn).status, 200)
        self.assertEqual(Runner(self.settings, store=self.store).drain(), 1)
        self.assertEqual(self.store.get(kept)["status"], "REVIEW_REQUIRED")
        job = self.store.get(withdrawn)
        self.assertEqual((job["status"], job["claims"], job["spec"], job["started_at"]), ("CANCELLED", 0, None, None))
        with Runtime(self.settings.core_dir, agents=agents_for(CATALOG, LLMConfig())) as runtime:
            with self.assertRaises(KeyError):
                runtime.status(withdrawn)
            self.assertEqual(runtime.status(kept)["status"], "SUCCEEDED")

    def test_claim_and_cancel_racing_never_both_win(self):
        outcomes = {"claimed": 0, "cancelled": 0}
        for round_number in range(150):
            # Straight into the store: 150 submissions through the API would hit its rate limit.
            job_id = admit(self.store, case_body(f"key-race-{round_number:04d}"), max_queued=10)[0]["job_id"]
            barrier = threading.Barrier(2)
            claim, refusal = [], []

            def claimer():
                barrier.wait()
                claim.append(self.store.claim_next("runner-race"))

            def canceller():
                barrier.wait()
                try:
                    self.store.cancel(job_id)
                except StateError as exc:
                    refusal.append(str(exc))

            threads = [threading.Thread(target=claimer), threading.Thread(target=canceller)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            status = self.store.get(job_id)["status"]
            if claim[0] is not None:  # the claim won: the cancel must have been refused
                self.assertEqual((claim[0]["job_id"], status, refusal), (job_id, "RUNNING", ["RUNNING"]))
                outcomes["claimed"] += 1
                self.store.finish(job_id, "FAILED", failure={"reason": "test"})  # clear the way for the next round
            else:  # the cancel won: nothing was claimed
                self.assertEqual((status, refusal), ("CANCELLED", []))
                outcomes["cancelled"] += 1
            kinds = [event["kind"] for event in self.store.events(job_id)[0]]
            self.assertFalse("job.claimed" in kinds and "job.cancelled" in kinds, kinds)
        self.assertEqual(sum(outcomes.values()), 150)


class StepPlanTests(unittest.TestCase):
    def test_the_plan_fills_in_the_same_defaults_as_core(self):
        spec = {"job_id": "plan_check", "input": {}, "steps": [
            {"id": "first", "agent": "test.agent"},
            {"id": "second", "agent": "test.agent", "depends_on": ["first"], "timeout_s": 9, "max_attempts": 3,
             "params": {"model": "kept out of the plan"}},
        ]}
        core = {step["id"]: step for step in normalize_spec(spec, {"test.agent"})["steps"]}
        plan = plan_view(spec)
        self.assertEqual([step["id"] for step in plan], ["first", "second"])
        for step in plan:
            self.assertEqual((step["depends_on"], step["max_attempts"], step["timeout_s"]),
                             (core[step["id"]]["depends_on"], core[step["id"]]["max_attempts"],
                              core[step["id"]]["timeout_s"]), step["id"])
            self.assertNotIn("params", step)

    def test_catalog_step_ids_do_not_reuse_core_phase_names(self):
        # Core records each step under its step id (roadmap 1.1) next to its own phases.
        # A step with one of those names would merge two different timings into one figure.
        core_phases = {"contract_validation", "delivery"}
        for name, workflow in CATALOG.items():
            steps = {step["id"] for step in preview_spec(workflow, LLMConfig())["steps"]}
            self.assertFalse(steps & core_phases, name)


if __name__ == "__main__":
    unittest.main()
