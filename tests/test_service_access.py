"""Personal access tokens and roles (roadmap 2.1, ADR-034): issuing a token that is shown once, revoking it at once,
the role table on every route, the limits on wrong credentials, the 3 -> 4 upgrade, and no token or hash in a
response, a log line, an event, a stored file or a Sentry event."""

import hashlib
import json
import logging
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app.api.routes import ApiApp, Request, route_label, route_template
from app.observability.sentry import _before_send
from app.persistence import QueueStore, review_id_for
from app.services import access
from app.services.runner import Runner
from tests.service_fixtures import KEY, case_body, settings

JOB = "job_" + "0" * 24
REVIEW = "rev_" + "0" * 24
UNKNOWN_ID = "ab" * 8  # a well-formed token id that no token has
# One path for every route template in the role table, and the body each POST needs to get past its checks.
SAMPLES = {
    "/v1/status": "/v1/status", "/v1/me": "/v1/me", "/v1/frame": "/v1/frame", "/v1/jobs": "/v1/jobs",
    "/v1/jobs/{job_id}": f"/v1/jobs/{JOB}",
    "/v1/jobs/{job_id}/events": f"/v1/jobs/{JOB}/events", "/v1/jobs/{job_id}/cancel": f"/v1/jobs/{JOB}/cancel",
    "/v1/reviews": "/v1/reviews", "/v1/reviews/scorecard": "/v1/reviews/scorecard",
    "/v1/reviews/{review_id}": f"/v1/reviews/{REVIEW}",
    "/v1/reviews/{review_id}/decisions": f"/v1/reviews/{REVIEW}/decisions", "/v1/tokens": "/v1/tokens",
    "/v1/tokens/{token_id}/revoke": f"/v1/tokens/{UNKNOWN_ID}/revoke",
}
BODIES = {
    "/v1/jobs": case_body("key-role-check-0001"),
    "/v1/reviews/{review_id}/decisions": {"decision": "APPROVE", "reason": "role check", "expected_version": 1,
                                          "idempotency_key": "key-role-check-0002"},
    "/v1/tokens": {"display_name": "role check", "role": "submitter"},
}


def call(app, method, path, body=None, *, credential=KEY, client="tester", headers=None):
    all_headers = {"authorization": f"Bearer {credential}"} if credential is not None else {}
    data = b""
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        all_headers["content-type"] = "application/json"
    all_headers.update(headers or {})
    return app.handle(Request(method, path, {}, all_headers, data, client))


def body_of(response):
    return json.loads(response.body)


class AccessTestCase(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._temp.name)
        self.settings = settings(self.data_dir)
        self.store = QueueStore(self.settings.queue_db)
        self.store.migrate()
        self.now = 1_800_000_000.0
        self.app = ApiApp(self.settings, self.store, clock=lambda: self.now)

    def tearDown(self):
        self._temp.cleanup()

    def issue(self, name="ผู้ตรวจ 1", role="reviewer", *, client="owner"):
        response = call(self.app, "POST", "/v1/tokens", {"display_name": name, "role": role}, client=client)
        self.assertEqual(response.status, 201, response.body)
        reply = body_of(response)
        return reply["token"], reply["token_info"]

    def waiting_review(self, key="key-access-case-01"):
        """A case that waits for a person: sent with the owner's key and run by the Runner."""
        job = body_of(call(self.app, "POST", "/v1/jobs", case_body(key)))
        Runner(self.settings, store=self.store).drain()
        return job["job_id"], review_id_for(job["job_id"])


class IssueTests(AccessTestCase):
    def test_the_owner_issues_a_token_that_is_shown_once(self):
        response = call(self.app, "POST", "/v1/tokens", {"display_name": "  ผู้ตรวจ 1 ", "role": "reviewer"})
        self.assertEqual(response.status, 201)
        reply = body_of(response)
        token, info = reply["token"], reply["token_info"]
        token_id, secret = access.parse_token(token)
        self.assertIs(reply["shown_once"], True)
        self.assertEqual((info["token_id"], info["display_name"], info["role"], info["active"], info["created_by"]),
                         (token_id, "ผู้ตรวจ 1", "reviewer", True, "shared-access-key"))
        self.assertNotIn("secret_sha256", info)
        self.assertIn("retention", reply)
        digest = hashlib.sha256(secret.encode()).hexdigest()
        # Never again: not in the list, not in the caller's own view, not in the status.
        for later in (call(self.app, "GET", "/v1/tokens"), call(self.app, "GET", "/v1/me", credential=token),
                      call(self.app, "GET", "/v1/status")):
            for hidden in (token, secret, digest):
                self.assertNotIn(hidden.encode(), later.body)
        listed = body_of(call(self.app, "GET", "/v1/tokens"))
        self.assertEqual([item["token_id"] for item in listed["tokens"]], [token_id])
        self.assertEqual((listed["active"], listed["max_active_tokens"]), (1, access.MAX_ACTIVE_TOKENS))
        # The database keeps the hash, never the secret.
        stored = self.settings.queue_db.read_bytes()
        self.assertIn(digest.encode(), stored)
        self.assertNotIn(secret.encode(), stored)

    def test_requests_for_a_token_are_checked_before_anything_is_written(self):
        cases = [({"display_name": "x"}, "invalid_fields"), ({"display_name": "x", "role": "reviewer", "extra": 1},
                                                               "invalid_fields"),
                 (["display_name", "role"], "invalid_fields"), ({"display_name": "   ", "role": "reviewer"},
                                                                "invalid_display_name"),
                 ({"display_name": "x" * 61, "role": "reviewer"}, "invalid_display_name"),
                 ({"display_name": "line\nbreak", "role": "reviewer"}, "invalid_display_name"),
                 ({"display_name": 7, "role": "reviewer"}, "invalid_display_name"),
                 ({"display_name": f"nf_{UNKNOWN_ID}_pasted", "role": "reviewer"}, "invalid_display_name"),
                 ({"display_name": "x", "role": "owner"}, "invalid_role"),
                 ({"display_name": "x", "role": "admin"}, "invalid_role")]
        for body, code in cases:
            with self.subTest(body=body):
                response = call(self.app, "POST", "/v1/tokens", body, client=f"owner-{code}-{len(str(body))}")
                self.assertEqual((response.status, body_of(response)["error"]), (400, code))
        raw = call(self.app, "POST", "/v1/tokens", None, headers={"content-type": "text/plain"})
        self.assertEqual(raw.status, 415)
        broken = self.app.handle(Request("POST", "/v1/tokens", {}, {"authorization": f"Bearer {KEY}",
                                                                    "content-type": "application/json"}, b"{", "x"))
        self.assertEqual((broken.status, body_of(broken)["error"]), (400, "invalid_json"))
        self.assertEqual(self.store.list_tokens(), [])

    def test_at_most_fifty_tokens_are_active_at_once(self):
        for number in range(access.MAX_ACTIVE_TOKENS):
            _token, info = self.issue(f"ผู้ส่งเคส {number}", "submitter", client=f"owner-{number // 10}")
        refused = call(self.app, "POST", "/v1/tokens", {"display_name": "one more", "role": "reviewer"}, client="other")
        self.assertEqual((refused.status, body_of(refused)["error"], body_of(refused)["active"]),
                         (409, "too_many_tokens", access.MAX_ACTIVE_TOKENS))
        call(self.app, "POST", f"/v1/tokens/{info['token_id']}/revoke")
        self.issue("one more", client="other")

    def test_new_tokens_are_rate_limited_per_client(self):
        statuses = [call(self.app, "POST", "/v1/tokens", {"display_name": f"n{i}", "role": "reviewer"},
                         client="busy").status for i in range(11)]
        self.assertEqual(statuses, [201] * 10 + [429])
        self.assertEqual(call(self.app, "POST", "/v1/tokens", {"display_name": "n", "role": "reviewer"},
                              client="calm").status, 201)


class UseTests(AccessTestCase):
    def test_a_token_says_who_it_is_and_what_its_role_may_do(self):
        token, info = self.issue("ผู้ตรวจ 1", "reviewer")
        me = body_of(call(self.app, "GET", "/v1/me", credential=token))
        self.assertEqual((me["token_id"], me["role"], me["display_name"], me["shared_key"]),
                         (info["token_id"], "reviewer", "ผู้ตรวจ 1", False))
        self.assertEqual(me["can"], {"submit": False, "cancel": False, "review": True, "manage_tokens": False})
        owner = body_of(call(self.app, "GET", "/v1/me"))
        self.assertEqual((owner["token_id"], owner["role"], owner["shared_key"]), ("shared-access-key", "owner", True))
        self.assertTrue(all(owner["can"].values()))
        submitter, _ = self.issue("n8n", "submitter")
        self.assertEqual(body_of(call(self.app, "GET", "/v1/me", credential=submitter))["can"],
                         {"submit": True, "cancel": True, "review": False, "manage_tokens": False})

    def test_revoking_takes_effect_at_once(self):
        token, info = self.issue()
        self.assertEqual(call(self.app, "GET", "/v1/me", credential=token, client="reviewer").status, 200)
        revoked = call(self.app, "POST", f"/v1/tokens/{info['token_id']}/revoke")
        self.assertEqual((revoked.status, body_of(revoked)["changed"], body_of(revoked)["token_info"]["active"]),
                         (200, True, False))
        self.assertEqual(body_of(revoked)["token_info"]["revoked_by"], "shared-access-key")
        after = call(self.app, "GET", "/v1/me", credential=token, client="reviewer")
        self.assertEqual((after.status, body_of(after)["error"]), (401, "unauthorized"))
        again = call(self.app, "POST", f"/v1/tokens/{info['token_id']}/revoke", {})
        self.assertEqual((again.status, body_of(again)["changed"]), (200, False))
        self.assertEqual(call(self.app, "POST", f"/v1/tokens/{UNKNOWN_ID}/revoke").status, 404)
        bad = call(self.app, "POST", f"/v1/tokens/{info['token_id']}/revoke", {"why": "x"})
        self.assertEqual((bad.status, body_of(bad)["error"]), (400, "invalid_fields"))

    def test_wrong_unknown_malformed_and_revoked_tokens_are_slowed_down_per_client(self):
        token, info = self.issue()
        token_id, secret = access.parse_token(token)
        revoked, revoked_info = self.issue("old")
        call(self.app, "POST", f"/v1/tokens/{revoked_info['token_id']}/revoke")
        wrong = [f"nf_{token_id}_{'A' * 43}", f"nf_{UNKNOWN_ID}_{secret}", token[:-1], token + "x", revoked,
                 "nf_" + token_id, token.upper(), "wrong-key-but-long-enough", f"Bearer {token}", "x" * 300]
        statuses = [call(self.app, "GET", "/v1/me", credential=value, client="guesser").status for value in wrong]
        self.assertEqual(statuses, [401] * 10)
        self.assertEqual(call(self.app, "GET", "/v1/me", credential=wrong[0], client="guesser").status, 429)
        self.assertEqual(call(self.app, "GET", "/v1/me", credential=token, client="guesser").status, 429)  # waits too
        self.assertEqual(call(self.app, "GET", "/v1/me", credential=token, client="reviewer").status, 200)

    def test_last_use_is_written_at_most_once_a_minute(self):
        token, info = self.issue()
        self.assertIsNone(body_of(call(self.app, "GET", "/v1/tokens"))["tokens"][0]["last_used_at"])

        def last_used():
            return self.store.list_tokens()[0]["last_used_at"]

        call(self.app, "GET", "/v1/me", credential=token)
        self.assertEqual(last_used(), self.now)
        first = self.now
        self.now += 30
        call(self.app, "GET", "/v1/me", credential=token)
        self.assertEqual(last_used(), first)
        self.now += 31
        call(self.app, "GET", "/v1/me", credential=token)
        self.assertEqual(last_used(), self.now)

    def test_a_token_lost_with_the_queue_is_refused(self):
        # Render's free plan starts the queue empty after every sleep, restart and deploy: tokens fail closed.
        token, _ = self.issue()
        with tempfile.TemporaryDirectory() as folder:
            empty = settings(Path(folder))
            store = QueueStore(empty.queue_db)
            store.migrate()
            app = ApiApp(empty, store)
            self.assertEqual(call(app, "GET", "/v1/me", credential=token).status, 401)
            self.assertEqual(call(app, "GET", "/v1/me").status, 200)  # the owner's shared key still works

    def test_without_a_configured_shared_key_no_token_works_either(self):
        token, _ = self.issue()
        app = ApiApp(settings(self.data_dir, access_key=None, access_key_problem="missing"), self.store)
        self.assertEqual(call(app, "GET", "/v1/me", credential=token).status, 503)


class RoleTests(AccessTestCase):
    def test_the_role_table_and_the_router_name_the_same_routes(self):
        self.assertEqual({template for _method, template in access.PERMISSIONS}, set(SAMPLES))
        for template, path in SAMPLES.items():
            self.assertEqual(route_template(path), template)
            for method in ("GET", "POST", "PUT", "DELETE"):
                with self.subTest(method=method, template=template):
                    response = call(self.app, method, path, BODIES.get(template) if method == "POST" else None,
                                    client=f"router-{method}-{template}")
                    # A route the owner can reach is in the table; one it cannot is refused as a method (405).
                    self.assertEqual(response.status != 405, access.known(method, template), response.body)

    def test_every_role_may_do_exactly_what_the_table_says(self):
        credentials = {"owner": KEY, "reviewer": self.issue("ผู้ตรวจ", "reviewer")[0],
                       "submitter": self.issue("ระบบส่งเคส", "submitter")[0]}
        for role, credential in credentials.items():
            for (method, template), roles in access.PERMISSIONS.items():
                with self.subTest(role=role, method=method, template=template):
                    response = call(self.app, method, SAMPLES[template], BODIES.get(template) if method == "POST"
                                    else None, credential=credential, client=f"{role}-{method}-{template}")
                    if role in roles:
                        self.assertNotIn(response.status, (401, 403), response.body)
                    else:
                        self.assertEqual((response.status, body_of(response)["error"], body_of(response)["role"]),
                                         (403, "forbidden", role))
                    head = call(self.app, "HEAD", SAMPLES[template], credential=credential, client=f"head-{role}")
                    if method == "GET":
                        self.assertEqual(head.status == 403, role not in roles)

    def test_unknown_routes_stay_404_for_every_role(self):
        reviewer, _ = self.issue()
        for path in ("/v1/nothing", "/v1/tokens/xyz/revoke", f"/v1/tokens/{UNKNOWN_ID}"):
            with self.subTest(path=path):
                self.assertEqual(call(self.app, "GET", path, credential=reviewer).status, 404)

    def test_a_reviewer_decides_and_the_decision_records_the_token(self):
        job_id, review_id = self.waiting_review()
        token, info = self.issue("ผู้ตรวจ 1", "reviewer")
        body = {"decision": "APPROVE", "reason": "ตรวจแล้ว", "expected_version": 1, "idempotency_key": "key-decide-1"}
        response = call(self.app, "POST", f"/v1/reviews/{review_id}/decisions", body, credential=token)
        self.assertEqual(response.status, 201, response.body)
        reply = body_of(response)
        self.assertEqual(reply["decision"]["reviewer"],
                         {"token_id": info["token_id"], "role": "reviewer", "name": "ผู้ตรวจ 1"})
        # The approval hands on like the owner's (vocabulary v2 lets a reviewer approve, ADR-034).
        self.assertEqual([item["state"] for item in reply["handoffs"]], ["STARTED"])
        Runner(self.settings, store=self.store).drain()
        apply_job = self.store.get(reply["handoffs"][0]["target_job_id"])
        self.assertEqual((apply_job["status"], apply_job["input"]["approved_by"]), ("COMPLETED", "reviewer"))
        events = self.store.events(job_id, after=0, limit=100)[0]
        approved = [event for event in events if event["kind"] == "review.approved"]
        self.assertEqual(approved[0]["payload"]["reviewer_role"], "reviewer")
        job = body_of(call(self.app, "GET", f"/v1/jobs/{job_id}", credential=token))
        self.assertEqual(job["human_review"]["decision"]["reviewer"]["name"], "ผู้ตรวจ 1")

    def test_a_submitter_sends_and_cancels_but_neither_decides_nor_reads_the_inbox(self):
        token, _ = self.issue("ระบบส่งเคส", "submitter")
        sent = call(self.app, "POST", "/v1/jobs", case_body("key-submitter-01"), credential=token)
        self.assertEqual(sent.status, 202)
        job_id = body_of(sent)["job_id"]
        self.assertEqual(call(self.app, "GET", f"/v1/jobs/{job_id}", credential=token).status, 200)
        self.assertEqual(call(self.app, "POST", f"/v1/jobs/{job_id}/cancel", credential=token).status, 200)
        _job_id, review_id = self.waiting_review("key-submitter-02")
        body = {"decision": "APPROVE", "reason": "x", "expected_version": 1, "idempotency_key": "key-sub-decide"}
        self.assertEqual(call(self.app, "POST", f"/v1/reviews/{review_id}/decisions", body, credential=token).status,
                         403)
        self.assertEqual(call(self.app, "GET", "/v1/reviews", credential=token).status, 403)
        self.assertEqual(self.store.review_counts()["PENDING"], 1)  # nothing was decided

    def test_a_reviewer_neither_sends_cancels_nor_manages_tokens(self):
        token, info = self.issue()
        self.assertEqual(call(self.app, "POST", "/v1/jobs", case_body("key-reviewer-01"), credential=token).status, 403)
        self.assertEqual(self.store.list_jobs(limit=10)[0], [])
        queued = body_of(call(self.app, "POST", "/v1/jobs", case_body("key-reviewer-02")))
        self.assertEqual(call(self.app, "POST", f"/v1/jobs/{queued['job_id']}/cancel", credential=token).status, 403)
        self.assertEqual(self.store.get(queued["job_id"])["status"], "QUEUED")
        self.assertEqual(call(self.app, "GET", "/v1/tokens", credential=token).status, 403)
        self.assertEqual(call(self.app, "POST", f"/v1/tokens/{info['token_id']}/revoke", credential=token).status, 403)
        self.assertEqual(call(self.app, "POST", "/v1/tokens", {"display_name": "me too", "role": "reviewer"},
                              credential=token).status, 403)
        self.assertEqual(len(self.store.list_tokens()), 1)


class SecrecyTests(AccessTestCase):
    def test_no_token_or_hash_in_responses_logs_events_or_files(self):
        with self.assertLogs("neuron_flow", level="INFO") as logs:
            token, info = self.issue("ผู้ตรวจ 1", "reviewer")
            secret = access.parse_token(token)[1]
            digest = hashlib.sha256(secret.encode()).hexdigest()
            job_id, review_id = self.waiting_review()
            decision = {"decision": "REJECT", "reason": "ไม่ใช่เคสจริง", "expected_version": 1,
                        "idempotency_key": "key-secrecy-01"}
            responses = [call(self.app, "GET", "/v1/me", credential=token),
                         call(self.app, "GET", "/v1/status", credential=token),
                         call(self.app, "GET", "/v1/jobs", credential=token),
                         call(self.app, "GET", f"/v1/jobs/{job_id}", credential=token),
                         call(self.app, "GET", f"/v1/jobs/{job_id}/events", credential=token),
                         call(self.app, "GET", f"/v1/reviews/{review_id}", credential=token),
                         call(self.app, "POST", f"/v1/reviews/{review_id}/decisions", decision, credential=token),
                         call(self.app, "GET", "/v1/tokens"),
                         call(self.app, "POST", f"/v1/tokens/{info['token_id']}/revoke"),
                         call(self.app, "GET", "/v1/me", credential=token)]
        for response in responses:
            for hidden in (token, secret, digest):
                self.assertNotIn(hidden.encode(), response.body)
        joined = "\n".join(logs.output)
        for hidden in (token, secret, digest):
            self.assertNotIn(hidden, joined)
        self.assertIn(f"access token {info['token_id']} issued", joined)  # who got a token is logged, by id
        events = json.dumps(self.store.events(job_id, after=0, limit=100)[0], ensure_ascii=False)
        self.assertNotIn(secret, events)
        for path in self.data_dir.rglob("*"):
            if path.is_file():
                self.assertNotIn(secret.encode(), path.read_bytes(), str(path))
                self.assertNotIn(token.encode(), path.read_bytes(), str(path))

    def test_a_token_is_never_taken_as_a_request_id_or_logged_from_an_address(self):
        token, _ = self.issue()
        for sent in (token, token[:40], "client-" + token[:30]):
            with self.subTest(sent=sent[:12]):
                self.assertNotEqual(self.app.request_id({"x-request-id": sent}), sent)
        self.assertEqual(self.app.request_id({"x-request-id": "client-run-42"}), "client-run-42")
        for path in (f"/v1/{token}", f"/v1/jobs/{token}", f"/v1/tokens/{token}/revoke"):
            with self.subTest(path=path[:20]):
                self.assertNotIn(access.parse_token(token)[1], route_label(path))
        self.assertEqual(route_label(f"/v1/tokens/{UNKNOWN_ID}/revoke"), "/v1/tokens/{token_id}/revoke")

    def test_a_server_error_carries_no_token_to_the_reply_or_to_sentry(self):
        token, _ = self.issue()

        class Reporter:
            def __init__(self):
                self.seen = []

            def capture_exception(self, exc, **_):
                self.seen.append(repr(exc) + str(exc.args))

        reporter = Reporter()
        app = ApiApp(self.settings, self.store, reporter=reporter)

        def broken(**_kwargs):
            raise RuntimeError("the queue could not be read")

        self.store.list_jobs = broken
        with self.assertLogs("neuron_flow.api", level="ERROR"):
            response = call(app, "GET", "/v1/jobs", credential=token)
        self.assertEqual(response.status, 500)
        self.assertNotIn(token.encode(), response.body)
        self.assertTrue(reporter.seen)
        self.assertNotIn(token, "".join(reporter.seen))
        # What the Sentry SDK would send is scrubbed first: no request (headers), no frame locals.
        event = {"request": {"headers": {"Authorization": f"Bearer {token}"}},
                 "exception": {"values": [{"stacktrace": {"frames": [{"vars": {"presented": token}}]}}]}}
        self.assertNotIn(token, json.dumps(_before_send(event, None)))


class MigrationTests(unittest.TestCase):
    def test_a_version_3_queue_is_upgraded_with_no_tokens_and_keeps_its_jobs(self):
        with tempfile.TemporaryDirectory() as folder:
            config = settings(Path(folder))
            store = QueueStore(config.queue_db)
            store.migrate()
            app = ApiApp(config, store)
            job_id = body_of(call(app, "POST", "/v1/jobs", case_body("key-upgrade-v3-01")))["job_id"]
            with closing(sqlite3.connect(config.queue_db)) as db, db:
                db.executescript("DROP TABLE access_tokens; UPDATE meta SET value='3' WHERE key='schema_version';")
            store = QueueStore(config.queue_db)
            store.migrate()
            with closing(sqlite3.connect(config.queue_db)) as db:
                # 3 -> 4 (access tokens) -> 5 (reviewer time, roadmap 2.10)
                self.assertEqual(db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], "5")
            self.assertEqual(store.list_tokens(), [])
            self.assertEqual(store.get(job_id)["status"], "QUEUED")
            app = ApiApp(config, store)
            created = call(app, "POST", "/v1/tokens", {"display_name": "after upgrade", "role": "reviewer"})
            self.assertEqual(created.status, 201)
            store.migrate()  # again: nothing changes
            self.assertEqual(len(store.list_tokens()), 1)


if __name__ == "__main__":
    unittest.main()
