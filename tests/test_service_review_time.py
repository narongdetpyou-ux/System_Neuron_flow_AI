"""Reviewer time per case (roadmap 2.10): how long a decision card was open before the person sent the decision.

The page sends ``card_open_s`` with a decision (a number only); the queue keeps it with the decision (schema 5); the
reviewer-label scorecard reports the median and the 95th percentile per group and by priority. It is a measurement:
it never changes the decision, a retried click keeps the first value, no view of one decision shows it, and nothing
breaks it down by person.
"""

from contextlib import closing
import json
import sqlite3
import threading
import unittest

from app.api.routes import ApiApp, Request
from app.persistence import QueueStore
from app.persistence import queue_store
from app.services import review_labels
from app.services.reviews import DecisionError, check_card_open, decide
from tests.service_fixtures import KEY
from tests.test_service_review_labels import LabelsTestCase

# review_decisions as schema version 4 created it: no card_open_s.
V4_DECISIONS = """
CREATE TABLE review_decisions (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id TEXT UNIQUE NOT NULL,
    review_id TEXT NOT NULL REFERENCES reviews(review_id),
    version INTEGER NOT NULL,
    reviewer_token_id TEXT NOT NULL,
    reviewer_role TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('APPROVE', 'REJECT')),
    final_category TEXT,
    reason TEXT NOT NULL,
    idempotency_key TEXT UNIQUE NOT NULL,
    request_sha256 TEXT NOT NULL,
    request_id TEXT,
    created_at REAL NOT NULL,
    UNIQUE (review_id, version)
);
"""
V4_COLUMNS = ("seq, decision_id, review_id, version, reviewer_token_id, reviewer_role, decision, final_category, reason,"
              " idempotency_key, request_sha256, request_id, created_at")


def stored_time(store, review_id):
    with closing(sqlite3.connect(store.path)) as db:
        return db.execute("SELECT card_open_s FROM review_decisions WHERE review_id=?", (review_id,)).fetchone()[0]


def body_for(number, **extra):
    return {"decision": "APPROVE", "reason": "ตรวจแล้ว", "expected_version": 1,
            "idempotency_key": f"key-review-time-{number:04d}", **extra}


class CheckTests(unittest.TestCase):
    def test_a_number_from_0_to_a_day_is_kept_to_a_tenth_of_a_second(self):
        for given, kept in ((None, None), (0, 0.0), (12.34, 12.3), (12.35, 12.3), (7, 7.0), (-0.0, 0.0),
                            (queue_store.CARD_OPEN_MAX_S, 86400.0)):
            with self.subTest(given=given):
                self.assertEqual(check_card_open(given), kept)
                self.assertEqual(str(check_card_open(given)), str(kept))  # never "-0.0"

    def test_anything_else_is_refused_rather_than_guessed(self):
        for given in (True, False, "12", [12], {"s": 12}, -0.1, -1, 86400.1, 10 ** 6, 10 ** 400,
                      float("inf"), float("-inf"), float("nan")):
            with self.subTest(given=repr(given)[:20]):
                with self.assertRaises(DecisionError) as caught:
                    check_card_open(given)
                self.assertEqual((caught.exception.status, caught.exception.code), (400, "invalid_card_open_s"))


class StoreTests(LabelsTestCase):
    def test_a_timed_decision_keeps_its_seconds_and_an_untimed_one_keeps_none(self):
        timed = self.decided(card_open_s=42.27)
        untimed = self.decided()
        self.assertEqual(stored_time(self.store, timed), 42.3)
        self.assertIsNone(stored_time(self.store, untimed))

    def test_the_time_changes_nothing_about_the_decision(self):
        review_id = self.waiting()
        review, row, created = decide(self.store, review_id, body_for(1, card_open_s=9.5))
        self.assertTrue(created)
        self.assertEqual((review["state"], row["decision"], row["final_category"]), ("APPROVED", "APPROVE", "billing"))
        other_id = self.waiting()
        plain_review, plain_row, _ = decide(self.store, other_id, body_for(2))
        same = ("decision", "final_category", "reason", "reviewer_role")
        self.assertEqual({k: row[k] for k in same}, {k: plain_row[k] for k in same})

    def test_a_retried_click_returns_the_first_decision_and_keeps_its_first_time(self):
        review_id = self.waiting()
        _review, first, created = decide(self.store, review_id, body_for(3, card_open_s=20))
        self.assertTrue(created)
        _review, again, created = decide(self.store, review_id, body_for(3, card_open_s=31.5))  # sent later
        self.assertFalse(created)
        self.assertEqual(again["decision_id"], first["decision_id"])
        _review, bare, created = decide(self.store, review_id, body_for(3))  # or without it at all
        self.assertFalse(created)
        self.assertEqual(bare["decision_id"], first["decision_id"])
        self.assertEqual(stored_time(self.store, review_id), 20.0)

    def test_the_database_refuses_a_value_the_service_would_refuse(self):
        review_id = self.waiting()
        for bad in (-5.0, 86400.5):
            with self.subTest(bad=bad), self.assertRaises(sqlite3.IntegrityError):
                self.store.decide(review_id, decision="APPROVE", final_category="billing", reason="x",
                                  expected_version=1, idempotency_key=f"key-bad-time-{bad}", request_sha256="0" * 64,
                                  reviewer_token_id="shared-access-key", reviewer_role="owner", card_open_s=bad)
        self.assertEqual(self.store.get_review(review_id)["state"], "PENDING")  # nothing half-written


class ScorecardTests(LabelsTestCase):
    def test_each_group_reports_the_median_and_95th_percentile_overall_and_by_priority(self):
        for seconds in (10, 20, 30, None):
            self.decided(card_open_s=seconds)
        self.decided(card_open_s=60, priority="elevated")
        [group] = self.report()["groups"]
        self.assertEqual(group["review_time"], {
            "timed": 4, "untimed": 1, "median_s": 25.0, "p95_s": 60.0,
            "by_priority": {"elevated": {"timed": 1, "untimed": 0, "median_s": 60.0, "p95_s": 60.0},
                            "normal": {"timed": 3, "untimed": 1, "median_s": 20.0, "p95_s": 30.0}}})

    def test_the_95th_percentile_is_a_measured_value_by_nearest_rank(self):
        for seconds in range(1, 21):  # 1 s to 20 s: the 19th of 20 is the 95th percentile
            self.decided(card_open_s=seconds)
        time = self.report()["groups"][0]["review_time"]
        self.assertEqual((time["timed"], time["median_s"], time["p95_s"]), (20, 10.5, 19.0))
        self.assertEqual(review_labels.nearest_rank([4.0], 0.95), 4.0)  # one value: that value

    def test_without_any_timed_decision_there_is_no_figure_only_the_count(self):
        self.decided()
        time = self.report()["groups"][0]["review_time"]
        self.assertEqual((time["timed"], time["untimed"], time["median_s"], time["p95_s"]), (0, 1, None, None))

    def test_times_of_two_versions_stay_in_their_own_groups(self):
        self.decided(card_open_s=5, rules_source="rules:keywords-v2:" + "a" * 64)
        self.decided(card_open_s=50, rules_source="rules:keywords-v2:" + "c" * 64)
        groups = self.report()["groups"]
        self.assertEqual(sorted(g["review_time"]["median_s"] for g in groups), [5.0, 50.0])

    def test_time_is_never_broken_down_by_person(self):
        self.decided(card_open_s=5, reviewer={"token_id": "1" * 16, "role": "reviewer"})
        self.decided(card_open_s=7, reviewer={"token_id": "2" * 16, "role": "reviewer"})
        report = self.report()
        time = report["groups"][0]["review_time"]
        self.assertEqual(set(time), {"timed", "untimed", "median_s", "p95_s", "by_priority"})
        self.assertLessEqual(set(time["by_priority"]), set(review_labels.PRIORITIES))
        text = json.dumps(report)
        self.assertNotIn("1" * 16, text)
        self.assertNotIn("2" * 16, text)


class ApiTests(LabelsTestCase):
    def setUp(self):
        super().setUp()
        self.app = ApiApp(self.settings, self.store)

    def call(self, method, path, body=None, *, raw=None):
        headers = {"authorization": f"Bearer {KEY}"}
        data = b""
        if body is not None or raw is not None:
            headers["content-type"] = "application/json"
            data = raw if raw is not None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        response = self.app.handle(Request(method, path, {}, headers, data, "tester"))
        return response.status, json.loads(response.body)

    def test_bad_times_are_refused_and_nothing_is_written(self):
        review_id = self.waiting()
        for number, value in enumerate((True, "12", -1, 86401, {"s": 1}, [3]), start=10):
            with self.subTest(value=value):
                status, reply = self.call("POST", f"/v1/reviews/{review_id}/decisions",
                                          body_for(number, card_open_s=value))
                self.assertEqual((status, reply["error"]), (400, "invalid_card_open_s"))
        # 1e400 is valid JSON that Python reads as infinity; NaN is not JSON at all.
        raw = json.dumps(body_for(20)).replace('"expected_version"', '"card_open_s": 1e400, "expected_version"')
        status, reply = self.call("POST", f"/v1/reviews/{review_id}/decisions", raw=raw.encode())
        self.assertEqual((status, reply["error"]), (400, "invalid_card_open_s"))
        raw = json.dumps(body_for(21)).replace('"expected_version"', '"card_open_s": NaN, "expected_version"')
        status, reply = self.call("POST", f"/v1/reviews/{review_id}/decisions", raw=raw.encode())
        self.assertEqual((status, reply["error"]), (400, "invalid_json"))
        self.assertEqual(self.store.get_review(review_id)["state"], "PENDING")
        self.assertEqual(self.store.get_review(review_id)["decisions"], [])

    def test_an_unknown_field_is_still_refused(self):
        review_id = self.waiting()
        status, reply = self.call("POST", f"/v1/reviews/{review_id}/decisions", body_for(30, seconds_open=4))
        self.assertEqual((status, reply["error"]), (400, "invalid_fields"))
        self.assertIn("card_open_s", reply["message"])

    def test_no_view_of_a_decision_shows_its_time(self):
        review_id = self.waiting()
        status, reply = self.call("POST", f"/v1/reviews/{review_id}/decisions", body_for(40, card_open_s=13.7))
        self.assertEqual(status, 201)
        job_id = reply["review"]["job_id"]
        views = [reply, self.call("GET", f"/v1/reviews/{review_id}")[1], self.call("GET", f"/v1/jobs/{job_id}")[1],
                 self.call("GET", f"/v1/jobs/{job_id}/events")[1], self.call("GET", "/v1/reviews?state=APPROVED")[1]]
        for view in views:
            self.assertNotIn("card_open_s", json.dumps(view))
            self.assertNotIn("13.7", json.dumps(view))
        status, card = self.call("GET", "/v1/reviews/scorecard")  # only the scorecard, as a figure of the group
        self.assertEqual(status, 200)
        self.assertEqual(card["groups"][0]["review_time"]["median_s"], 13.7)

    def test_the_status_tells_the_page_the_limit(self):
        status, reply = self.call("GET", "/v1/status")
        self.assertEqual(status, 200)
        self.assertEqual(reply["reviews"]["card_open_max_s"], queue_store.CARD_OPEN_MAX_S)


class MigrationTests(LabelsTestCase):
    def version_4_store(self):
        """A queue as schema version 4 left it, with one decision made before reviewer time existed."""
        review_id = self.decided()
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.executescript("ALTER TABLE review_decisions RENAME TO old_decisions;" + V4_DECISIONS +
                             f"INSERT INTO review_decisions ({V4_COLUMNS}) SELECT {V4_COLUMNS} FROM old_decisions;"
                             " DROP TABLE old_decisions;"
                             " CREATE INDEX review_decisions_by_review ON review_decisions(review_id, seq);"
                             " UPDATE meta SET value='4' WHERE key='schema_version';")
            columns = {row[1] for row in db.execute("PRAGMA table_info(review_decisions)")}
        self.assertNotIn("card_open_s", columns)
        return review_id

    def test_a_version_4_queue_gets_the_column_and_its_old_decisions_count_as_untimed(self):
        old = self.version_4_store()
        store = QueueStore(self.store.path)
        store.migrate()
        with closing(sqlite3.connect(store.path)) as db:
            self.assertEqual(db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], "5")
        self.assertIsNone(stored_time(store, old))
        self.store = store
        new = self.decided(card_open_s=8)
        self.assertEqual(stored_time(store, new), 8.0)
        time = review_labels.report(store)["groups"][0]["review_time"]
        self.assertEqual((time["timed"], time["untimed"], time["median_s"]), (1, 1, 8.0))
        with self.assertRaises(sqlite3.IntegrityError):  # the upgraded column has the same check as a new one
            store.decide(self.waiting(), decision="APPROVE", final_category="billing", reason="x", expected_version=1,
                         idempotency_key="key-bad-time-upgraded", request_sha256="0" * 64,
                         reviewer_token_id="shared-access-key", reviewer_role="owner", card_open_s=-1.0)
        store.migrate()  # again: nothing changes
        self.assertEqual(stored_time(store, new), 8.0)

    def test_two_processes_upgrading_at_the_same_start_add_the_column_once(self):
        self.version_4_store()
        errors = []

        def upgrade():
            try:
                QueueStore(self.store.path).migrate()
            except Exception as exc:  # pragma: no cover - reported below
                errors.append(exc)

        threads = [threading.Thread(target=upgrade) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        with closing(sqlite3.connect(self.store.path)) as db:
            columns = [row[1] for row in db.execute("PRAGMA table_info(review_decisions)")]
        self.assertEqual(columns.count("card_open_s"), 1)

    def test_an_old_queue_upgraded_from_version_1_has_the_column_too(self):
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.executescript("DROP TABLE review_decisions; DROP TABLE reviews;"
                             " UPDATE meta SET value='1' WHERE key='schema_version';")
        store = QueueStore(self.store.path)
        store.migrate()  # the decisions table is created afresh with the column; the upgrade must not add it twice
        with closing(sqlite3.connect(store.path)) as db:
            columns = [row[1] for row in db.execute("PRAGMA table_info(review_decisions)")]
            self.assertEqual(db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], "5")
        self.assertEqual(columns.count("card_open_s"), 1)


if __name__ == "__main__":
    unittest.main()
