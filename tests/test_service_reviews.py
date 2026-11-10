"""People decide (roadmap 2.2, ADR-027; the independent review of 2026-11-10, point 4), and the service says how long
what it stores will last (point 3).

Reviews: the Runner's REVIEW_REQUIRED creates a PENDING review in the same transaction; the inbox lists elevated
cases first; a decision applies once per version, is idempotent, records who decided from the credential, moves the
job to APPROVED or REJECTED, and never writes the person's reason into events or logs; a version-1 queue is upgraded
with a review for every waiting job.

Retention: ``/v1/status``, a new job's reply and a decision's reply say whether storage survives a restart and carry
the queue database's ``store_id``, which changes when the queue starts empty again.
"""

from contextlib import contextmanager
import hashlib
import json
import logging
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from app.api.routes import ApiApp, Request, route_label, route_template
from app.persistence import QueueStore, StateError, review_id_for
from app.persistence import queue_store
from app.services.metrics import queue_metrics
from app.services.runner import Runner
from tests.service_fixtures import KEY, case_body, settings
from tests.test_service_api import AUTH, JSON, ApiTestCase, body_of, get, post

PROPOSAL = {"case_id": "C-1", "suggested_category": "upload", "suggested_queue": "upload_review",
            "suggestion_source": "rules:keywords-v1", "second_opinion": None, "agreement": None,
            "review_required": True, "review_priority": "normal", "review_reasons": [],
            "decision": "PENDING_HUMAN_REVIEW", "mode": "shadow"}
REASON = "ตรวจแล้ว ข้อเสนอถูกต้อง ส่งต่อได้"


@contextmanager
def raw_db(path):
    """A plain connection that commits and closes (``sqlite3.connect`` as a context manager does not close)."""
    db = sqlite3.connect(path)
    try:
        with db:
            yield db
    finally:
        db.close()


def waiting_job(store, key, *, priority="normal", category="upload", summary="I cannot upload an attachment"):
    """A job the Runner finished as REVIEW_REQUIRED, without running Core (the Runner test does that once).

    It claims this job by id: since ADR-030 an approval queues its follow-up job, which ``claim_next`` would take
    first."""
    job, _ = store.admit(job_id="job_" + hashlib.sha256(key.encode()).hexdigest()[:24], idempotency_key=key,
                         request_fingerprint=key, workflow_type="case_triage.v2",
                         input={"case_id": key[-12:], "summary": summary}, max_queued=1000)
    with raw_db(store.path) as db:
        claimed = db.execute("UPDATE jobs SET status='RUNNING', claims=claims+1, runner_id='runner-test'"
                             " WHERE job_id=? AND status='QUEUED'", (job["job_id"],)).rowcount
    assert claimed == 1
    review = dict(PROPOSAL, case_id=key[-12:], review_priority=priority, suggested_category=category,
                  suggested_queue=f"{category}_review")
    store.finish(job["job_id"], "REVIEW_REQUIRED", result={"review": review, "steps": [], "ai": None})
    return job["job_id"]


def decide(app, review_id, body=None, *, headers=None, raw=None, client="tester", **fields):
    payload = {"decision": "APPROVE", "reason": REASON, "expected_version": 1, "idempotency_key": "web-decide-0001"}
    payload.update(fields)
    if body is not None:
        payload = body
    data = raw if raw is not None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return app.handle(Request("POST", f"/v1/reviews/{review_id}/decisions", {}, dict(JSON if headers is None else headers),
                              data, client))


class ReviewCreationTests(ApiTestCase):
    def test_the_runner_creates_one_pending_review_per_case_that_waits(self):
        post(self.app, case_body("key-runner-review-01", summary="I cannot upload an attachment"))
        post(self.app, case_body("key-runner-review-02", summary="เดือนนี้ถูกหักค่าบริการสองครั้ง ขอคืนเงินด้วยครับ"))
        post(self.app, {"workflow_type": "study_guide.v1", "idempotency_key": "key-runner-study-01",
                        "input": {"message": "How do I write a good prompt?"}})
        Runner(self.settings, store=self.store).drain()
        jobs = {job["workflow_type"] + ":" + job["status"]: job for job in self.jobs_in_store()}
        self.assertIn("study_guide.v1:COMPLETED", jobs)
        reviews, _ = self.store.list_reviews(limit=10)
        self.assertEqual(len(reviews), 2)
        self.assertEqual({review["job_id"] for review in reviews},
                         {job["job_id"] for job in self.jobs_in_store() if job["status"] == "REVIEW_REQUIRED"})
        self.assertEqual({review["priority"] for review in reviews}, {"normal"})  # both English and Thai agree
        billing = next(job for job in self.jobs_in_store() if job["input"].get("summary", "").startswith("เดือนนี้"))
        self.assertEqual(billing["result"]["review"]["suggested_category"], "billing")
        study = jobs["study_guide.v1:COMPLETED"]
        self.assertIsNone(body_of(get(self.app, f"/v1/jobs/{study['job_id']}"))["human_review"])

    def test_the_review_is_written_with_the_outcome_or_not_at_all(self):
        self.store.admit(job_id="job_" + "a" * 24, idempotency_key="key-atomic-0001", request_fingerprint="x",
                         workflow_type="case_triage.v2", input={"case_id": "C", "summary": "x" * 10}, max_queued=10)
        self.store.claim_next("runner-test")
        with mock.patch.object(queue_store, "_insert_review", side_effect=sqlite3.OperationalError("disk I/O error")):
            with self.assertRaises(sqlite3.OperationalError):
                self.store.finish("job_" + "a" * 24, "REVIEW_REQUIRED", result={"review": PROPOSAL})
        self.assertEqual(self.store.get("job_" + "a" * 24)["status"], "RUNNING")  # reconciliation will retry it
        self.assertEqual(self.store.list_reviews()[0], [])
        kinds = [event["kind"] for event in self.store.events("job_" + "a" * 24)[0]]
        self.assertNotIn("job.review_required", kinds)

    def test_only_review_required_creates_a_review(self):
        self.store.admit(job_id="job_" + "b" * 24, idempotency_key="key-complete-01", request_fingerprint="x",
                         workflow_type="case_triage.v2", input={"case_id": "C", "summary": "x" * 10}, max_queued=10)
        self.store.claim_next("runner-test")
        self.store.finish("job_" + "b" * 24, "COMPLETED", result={"review": dict(PROPOSAL, review_required=False)})
        self.assertIsNone(self.store.review_of_job("job_" + "b" * 24))


class InboxTests(ApiTestCase):
    def test_elevated_first_then_the_oldest_in_pages(self):
        normal_1 = waiting_job(self.store, "key-inbox-normal-1")
        elevated_1 = waiting_job(self.store, "key-inbox-elevated-1", priority="elevated")
        normal_2 = waiting_job(self.store, "key-inbox-normal-2")
        elevated_2 = waiting_job(self.store, "key-inbox-elevated-2", priority="elevated")
        order, after = [], None
        while True:
            query = {"limit": ["1"]}
            if after:
                query["after"] = [after]
            page = body_of(get(self.app, "/v1/reviews", query))
            order += [item["job_id"] for item in page["reviews"]]
            after = page["next_after"]
            if after is None:
                break
        self.assertEqual(order, [elevated_1, elevated_2, normal_1, normal_2])
        self.assertEqual(page["counts"], {"PENDING": 4, "APPROVED": 0, "REJECTED": 0, "elevated_pending": 2})
        item = body_of(get(self.app, "/v1/reviews"))["reviews"][0]
        self.assertEqual(set(item), {"review_id", "job_id", "state", "version", "priority", "suggested_category",
                                     "workflow_type", "case_id", "summary_preview", "created_at", "decided_at"})

    def test_decided_reviews_are_listed_by_state_newest_first(self):
        first = review_id_for(waiting_job(self.store, "key-decided-0001"))
        second = review_id_for(waiting_job(self.store, "key-decided-0002"))
        decide(self.app, first, idempotency_key="web-decide-1111")
        decide(self.app, second, decision="REJECT", idempotency_key="web-decide-2222")
        approved = body_of(get(self.app, "/v1/reviews", {"state": ["APPROVED"]}))["reviews"]
        rejected = body_of(get(self.app, "/v1/reviews", {"state": ["REJECTED"]}))["reviews"]
        self.assertEqual(([r["review_id"] for r in approved], [r["review_id"] for r in rejected]), ([first], [second]))
        self.assertEqual(body_of(get(self.app, "/v1/reviews"))["reviews"], [])

    def test_bad_inbox_parameters_are_refused(self):
        for query in ({"state": ["DONE"]}, {"limit": ["0"]}, {"limit": ["101"]}, {"after": ["x"]}, {"after": ["2-1"]}):
            with self.subTest(query=query):
                self.assertEqual(get(self.app, "/v1/reviews", query).status, 400)
        self.assertEqual(get(self.app, "/v1/reviews", method="POST").status, 405)

    def test_review_detail_has_the_case_the_proposal_and_the_history(self):
        review_id = review_id_for(waiting_job(self.store, "key-detail-00001", priority="elevated", category="billing"))
        detail = body_of(get(self.app, f"/v1/reviews/{review_id}"))
        self.assertEqual((detail["state"], detail["version"], detail["priority"], detail["decidable"]),
                         ("PENDING", 1, "elevated", True))
        self.assertEqual(detail["case"]["summary"], "I cannot upload an attachment")
        self.assertEqual(detail["proposal"]["suggested_category"], "billing")
        self.assertEqual(detail["decisions"], [])
        self.assertEqual(len(detail["proposal_sha256"]), 64)
        self.assertEqual(get(self.app, "/v1/reviews/rev_" + "0" * 24).status, 404)
        self.assertEqual(get(self.app, "/v1/reviews/rev_nothex").status, 404)
        self.assertEqual(get(self.app, f"/v1/reviews/{review_id}/decisions").status, 405)


class DecisionTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.job_id = waiting_job(self.store, "key-decision-0001")
        self.review_id = review_id_for(self.job_id)

    def test_approving_as_proposed_keeps_the_rules_suggestion_and_closes_the_case(self):
        response = decide(self.app, self.review_id)
        self.assertEqual(response.status, 201)
        body = body_of(response)
        decision = body["decision"]
        self.assertEqual((decision["decision"], decision["final_category"], decision["final_queue"], decision["version"]),
                         ("APPROVE", "upload", "upload_review", 1))
        self.assertEqual(decision["reviewer"], {"token_id": "shared-access-key", "role": "owner"})
        self.assertEqual(decision["reason"], REASON)
        self.assertEqual((body["review"]["state"], body["review"]["version"], body["review"]["decidable"]),
                         ("APPROVED", 2, False))
        job = body_of(get(self.app, f"/v1/jobs/{self.job_id}"))
        self.assertEqual(job["status"], "APPROVED")
        self.assertEqual(job["human_review"]["decision"]["decision_id"], decision["decision_id"])
        self.assertEqual(self.store.counts()["APPROVED"], 1)

    def test_a_reviewer_can_choose_another_category_or_reject(self):
        response = decide(self.app, self.review_id, final_category="billing")
        self.assertEqual(body_of(response)["decision"]["final_queue"], "billing_review")
        other = review_id_for(waiting_job(self.store, "key-decision-0002"))
        rejected = body_of(decide(self.app, other, decision="REJECT", idempotency_key="web-decide-0002"))["decision"]
        self.assertEqual((rejected["decision"], rejected["final_category"], rejected["final_queue"]), ("REJECT", None, None))
        self.assertEqual(self.store.get(other.replace("rev_", "job_"))["status"], "REJECTED")

    def test_the_same_click_again_returns_the_same_decision(self):
        first = body_of(decide(self.app, self.review_id))
        again = decide(self.app, self.review_id)
        self.assertEqual(again.status, 200)
        self.assertEqual(body_of(again)["decision"]["decision_id"], first["decision"]["decision_id"])
        self.assertFalse(body_of(again)["created"])
        self.assertEqual(len(self.store.get_review(self.review_id)["decisions"]), 1)

    def test_conflicts_change_nothing(self):
        decide(self.app, self.review_id)
        cases = [
            ({"reason": "อีกเหตุผลหนึ่ง"}, "idempotency_conflict"),                      # same key, another body
            ({"idempotency_key": "web-decide-9999"}, "already_decided"),                 # a second decision
            ({"idempotency_key": "web-decide-8888", "decision": "REJECT"}, "already_decided"),
        ]
        for fields, code in cases:
            with self.subTest(code=code, fields=fields):
                response = decide(self.app, self.review_id, **fields)
                self.assertEqual((response.status, body_of(response)["error"]), (409, code))
        other = review_id_for(waiting_job(self.store, "key-decision-0003"))
        reused = decide(self.app, other)  # the first decision's key, on another review
        self.assertEqual((reused.status, body_of(reused)["error"]), (409, "idempotency_conflict"))
        stale = decide(self.app, other, expected_version=2, idempotency_key="web-decide-7777")
        self.assertEqual((stale.status, body_of(stale)["error"], body_of(stale)["version"]), (409, "version_conflict", 1))
        self.assertEqual(self.store.get_review(other)["decisions"], [])
        self.assertEqual(self.store.get(other.replace("rev_", "job_"))["status"], "REVIEW_REQUIRED")

    def test_sixteen_identical_clicks_at_once_make_one_decision(self):
        responses = []

        def click():
            responses.append(decide(self.app, self.review_id))

        threads = [threading.Thread(target=click) for _ in range(16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(r.status for r in responses), [200] * 15 + [201])
        self.assertEqual(len({body_of(r)["decision"]["decision_id"] for r in responses}), 1)
        self.assertEqual(len(self.store.get_review(self.review_id)["decisions"]), 1)

    def test_sixteen_different_decisions_at_once_only_one_wins(self):
        responses = []

        def click(index):
            responses.append(decide(self.app, self.review_id, idempotency_key=f"web-race-{index:04d}",
                                    decision="APPROVE" if index % 2 else "REJECT"))

        threads = [threading.Thread(target=click, args=(index,)) for index in range(16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(r.status for r in responses), [201] + [409] * 15)
        self.assertEqual({body_of(r)["error"] for r in responses if r.status == 409}, {"already_decided"})
        review = self.store.get_review(self.review_id)
        self.assertEqual((len(review["decisions"]), review["version"]), (1, 2))
        self.assertEqual(self.store.get(self.job_id)["status"], review["state"])

    def test_bad_decisions_are_refused_before_anything_is_written(self):
        base = {"decision": "APPROVE", "reason": REASON, "expected_version": 1, "idempotency_key": "web-decide-0001"}
        cases = {
            "missing reason": ({k: v for k, v in base.items() if k != "reason"}, "invalid_fields"),
            "extra field": (dict(base, reviewer="someone else"), "invalid_fields"),
            "not an object": ([base], "invalid_fields"),
            "unknown decision": (dict(base, decision="AUTO_APPROVE"), "invalid_decision"),
            "unknown category": (dict(base, final_category="refunds"), "invalid_category"),
            "blank reason": (dict(base, reason="   "), "invalid_reason"),
            "long reason": (dict(base, reason="ก" * 501), "invalid_reason"),
            "control character": (dict(base, reason="ok\x07"), "invalid_reason"),
            "version as text": (dict(base, expected_version="1"), "invalid_version"),
            "version as true": (dict(base, expected_version=True), "invalid_version"),
            "short key": (dict(base, idempotency_key="short"), "invalid_idempotency_key"),
        }
        for name, (body, code) in cases.items():
            with self.subTest(name):
                response = decide(self.app, self.review_id, body)
                self.assertEqual((response.status, body_of(response)["error"]), (400, code))
        raw_cases = {"invalid json": b"{", "repeated field": b'{"decision":"APPROVE","decision":"REJECT"}',
                     "half of an emoji": json.dumps(dict(base, reason="ok \ud83d")).encode("utf-8", "surrogatepass")}
        for name, raw in raw_cases.items():
            with self.subTest(name):
                self.assertEqual(decide(self.app, self.review_id, raw=raw).status, 400)
        self.assertEqual(decide(self.app, self.review_id, headers=AUTH).status, 415)
        self.assertEqual(decide(self.app, self.review_id, raw=b"{" + b" " * 20000 + b"}").status, 413)
        self.assertEqual(body_of(decide(self.app, "rev_" + "0" * 24))["error"], "review_not_found")
        self.assertEqual(self.store.get_review(self.review_id)["decisions"], [])
        self.assertEqual(decide(self.app, self.review_id, reason="  สองบรรทัด\nได้  ").status, 201)

    def test_every_review_route_needs_the_key(self):
        for headers in ({}, {"authorization": "Bearer wrong-key-000000000000"}):
            with self.subTest(headers=bool(headers)):
                self.assertEqual(get(self.app, "/v1/reviews", headers=headers).status, 401)
                self.assertEqual(get(self.app, f"/v1/reviews/{self.review_id}", headers=headers, client="other").status, 401)
                response = decide(self.app, self.review_id, headers={"content-type": "application/json", **headers},
                                  client="third")
                self.assertEqual(response.status, 401)
        self.assertEqual(self.store.get_review(self.review_id)["decisions"], [])

    def test_decisions_are_rate_limited_per_client(self):
        app = ApiApp(settings(self.data_dir, submit_per_minute=2), self.store)
        statuses = [decide(app, self.review_id, idempotency_key=f"web-limit-{i:04d}").status for i in range(4)]
        self.assertEqual(statuses[:2], [201, 409])
        self.assertEqual(statuses[2:], [429, 429])

    def test_the_reason_stays_out_of_events_and_logs(self):
        secret_reason = "ลูกค้าชื่อสมมุติ โทร 081-234-5678 ยืนยันแล้ว"
        with self.assertLogs("neuron_flow", level="INFO") as logs:
            logging.getLogger("neuron_flow.api").info("marker")
            decide(self.app, self.review_id, reason=secret_reason)
        events = self.store.events(self.job_id)[0]
        approved = [event for event in events if event["kind"] == "review.approved"]
        self.assertEqual(len(approved), 1)
        self.assertEqual(set(approved[0]["payload"]), {"review_id", "decision_id", "version", "decision",
                                                       "final_category", "reviewer_role", "request_id"})
        for event in events:
            self.assertNotIn("081-234-5678", json.dumps(event, ensure_ascii=False))
        self.assertNotIn("081-234-5678", "\n".join(logs.output))

    def test_decided_cases_still_count_in_the_run_time_figures(self):
        decide(self.app, self.review_id)
        figures = queue_metrics(self.store, now=self.store.get(self.job_id)["finished_at"] + 1)
        self.assertEqual(figures["window"]["jobs"], 1)

    def test_a_decision_cannot_move_a_job_that_is_not_waiting(self):
        with raw_db(self.settings.queue_db) as db:  # a job moved by hand, behind the review's back
            db.execute("UPDATE jobs SET status='FAILED' WHERE job_id=?", (self.job_id,))
        response = decide(self.app, self.review_id)
        self.assertEqual((response.status, body_of(response)["error"]), (409, "not_reviewable"))
        self.assertEqual(self.store.get_review(self.review_id)["state"], "PENDING")  # rolled back together
        self.assertEqual(self.store.get_review(self.review_id)["decisions"], [])


class LogPrivacyTests(unittest.TestCase):
    def test_review_ids_are_hidden_like_job_ids(self):
        review_id = "rev_" + "ab" * 12
        self.assertEqual(route_label(f"/v1/reviews/{review_id}/decisions"), "/v1/reviews/{review_id}/decisions")
        self.assertEqual(route_template(f"/v1/reviews/{review_id}"), "/v1/reviews/{review_id}")
        self.assertEqual(route_template("/v1/reviews"), "/v1/reviews")
        with tempfile.TemporaryDirectory() as folder:
            config = settings(Path(folder))
            store = QueueStore(config.queue_db)
            store.migrate()
            app = ApiApp(config, store)
            self.assertNotEqual(app.request_id({"x-request-id": f"client-{review_id}"}), f"client-{review_id}")


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.path = Path(self._temp.name) / "queue.sqlite3"

    def tearDown(self):
        self._temp.cleanup()

    def version_1_store(self, waiting=2):
        """A queue as schema version 1 left it: jobs, but no review tables and no store id."""
        store = QueueStore(self.path)
        store.migrate()
        jobs = [waiting_job(store, f"key-old-queue-{i:03d}", priority="elevated" if i == 0 else "normal")
                for i in range(waiting)]
        with raw_db(self.path) as db:
            db.executescript("DROP TABLE review_decisions; DROP TABLE reviews;"
                             " DELETE FROM meta WHERE key IN ('store_id', 'store_created_at');"
                             " UPDATE meta SET value='1' WHERE key='schema_version';")
        return jobs

    def test_version_1_is_upgraded_with_a_review_for_every_waiting_job(self):
        jobs = self.version_1_store()
        store = QueueStore(self.path)
        store.migrate()
        reviews, _ = store.list_reviews(limit=10)
        self.assertEqual([review["job_id"] for review in reviews], jobs)  # the elevated one first
        self.assertEqual(reviews[0]["priority"], "elevated")
        with raw_db(self.path) as db:
            # Upgraded step by step to the current version (3 since ADR-030 added handoffs).
            self.assertEqual(db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0],
                             str(queue_store.SCHEMA_VERSION))
        store.migrate()  # again: nothing changes
        self.assertEqual(len(store.list_reviews(limit=10)[0]), 2)

    def test_two_processes_upgrading_at_the_same_start_make_one_review_each(self):
        self.version_1_store(waiting=3)
        errors = []

        def upgrade():
            try:
                QueueStore(self.path).migrate()
            except Exception as exc:  # pragma: no cover - reported below
                errors.append(exc)

        threads = [threading.Thread(target=upgrade) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(QueueStore(self.path).review_counts()["PENDING"], 3)

    def test_an_unknown_version_is_refused(self):
        store = QueueStore(self.path)
        store.migrate()
        with raw_db(self.path) as db:
            db.execute("UPDATE meta SET value='4' WHERE key='schema_version'")
        with self.assertRaisesRegex(RuntimeError, "schema 4 is not supported"):
            store.migrate()


class RetentionTests(ApiTestCase):
    def test_the_store_id_is_stable_until_the_queue_starts_empty_again(self):
        first = self.store.store_info()
        self.assertRegex(first["id"], r"^store_[0-9a-f]{16}$")
        self.store.migrate()
        self.assertEqual(self.store.store_info(), first)  # a Runner restart on the same disk keeps it
        with tempfile.TemporaryDirectory() as other:
            fresh = QueueStore(Path(other) / "queue.sqlite3")
            fresh.migrate()
            self.assertNotEqual(fresh.store_info()["id"], first["id"])  # a new, empty disk gets a new one

    def test_temporary_storage_is_said_at_every_write(self):
        app = ApiApp(settings(self.data_dir, storage="local_default"), self.store)
        store = self.store.store_info()
        expected = {"persistent": False, "lost_on": ["sleep", "restart", "deploy"], "store_id": store["id"],
                    "store_started_at": store["created_at"]}
        review_id = review_id_for(waiting_job(self.store, "key-retention-02"))
        status = body_of(get(app, "/v1/status"))
        self.assertEqual(status["retention"], expected)
        self.assertEqual(status["storage"]["persistent"], False)
        admitted = post(app, case_body("key-retention-01"))
        self.assertEqual((admitted.status, body_of(admitted)["retention"]), (202, expected))
        self.assertEqual(body_of(post(app, case_body("key-retention-01")))["retention"], expected)  # the duplicate too
        self.assertEqual(body_of(decide(app, review_id))["retention"], expected)

    def test_persistent_storage_says_so(self):
        status = body_of(get(self.app, "/v1/status"))  # the test settings use a configured data folder
        self.assertEqual(status["retention"]["persistent"], True)
        self.assertEqual(status["retention"]["lost_on"], [])
        self.assertEqual(status["reviews"]["categories"], ["access", "upload", "billing", "other"])
        self.assertEqual(status["reviews"]["reviewer_role"], "owner")


class RunnerReviewTests(unittest.TestCase):
    def test_only_the_api_records_decisions(self):
        # Rule 4: the AI, the agents and the Runner never decide. Only app/api (a person's request) and the
        # review service it calls may reach QueueStore.decide.
        root = Path(__file__).resolve().parent.parent
        callers = sorted(str(path.relative_to(root)) for path in (root / "app").rglob("*.py")
                         if "decide(" in path.read_text(encoding="utf-8"))
        self.assertEqual(callers, ["app/api/routes.py", "app/persistence/queue_store.py", "app/services/reviews.py"])

    def test_store_errors_never_leave_half_a_decision(self):
        with tempfile.TemporaryDirectory() as folder:
            config = settings(Path(folder))
            store = QueueStore(config.queue_db)
            store.migrate()
            job_id = waiting_job(store, "key-half-decision")
            original = store._event

            def failing_event(db, job, kind, payload, now):
                if kind.startswith("review."):
                    raise sqlite3.OperationalError("disk I/O error")
                return original(db, job, kind, payload, now)

            with mock.patch.object(store, "_event", side_effect=failing_event):
                with self.assertRaises(sqlite3.OperationalError):
                    store.decide(review_id_for(job_id), decision="APPROVE", final_category="upload", reason="ok",
                                 expected_version=1, idempotency_key="web-half-0001", request_sha256="x",
                                 reviewer_token_id="shared-access-key", reviewer_role="owner")
            review = store.get_review(review_id_for(job_id))
            self.assertEqual((review["state"], review["version"], review["decisions"]), ("PENDING", 1, []))
            self.assertEqual(store.get(job_id)["status"], "REVIEW_REQUIRED")
            with self.assertRaises(StateError):
                store.finish(job_id, "COMPLETED")  # finished jobs stay as they are


if __name__ == "__main__":
    unittest.main()
