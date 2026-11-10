"""Skill handoffs through the queue, the Runner and the API (ADR-030, roadmap H3 and 2.3).

An approval of a ``case_triage.v2`` case starts exactly one ``case_triage.v2.apply`` job, in the decision's own
transaction: also with 16 identical clicks at once, never after a rejection, never half after a failure, and never
twice after a Runner crash. A refused handoff keeps the approval and says why. The case text never travels and never
reaches an event. A version-2 queue is upgraded to 3.
"""

import json
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock

from neuron_flow import AgentDefinition

from app.api.routes import ApiApp
from app.exchange import TRANSLATORS, Exchange, RouteTable, Translator
from app.exchange.common import fact
from app.persistence import QueueStore, review_id_for
from app.services.admission import admit
from app.services.runner import Runner
from app.services.workflows import CATALOG, WorkflowType, check_case
from tests.service_fixtures import case_body
from tests.test_service_api import ApiTestCase, body_of, get, post
from tests.test_service_reviews import decide, raw_db, waiting_job

SUMMARY = "I cannot upload an attachment to my ticket"


def apply_jobs(store):
    return [job for job in store.list_jobs(limit=100)[0] if job["workflow_type"] == "case_triage.v2.apply"]


def all_event_text(store, job_ids):
    return json.dumps([store.events(job_id, limit=100)[0] for job_id in job_ids], ensure_ascii=False)


class ApprovalHandoffTests(ApiTestCase):
    def test_an_approval_hands_the_case_to_the_apply_skill_end_to_end(self):
        source_id = body_of(post(self.app, case_body("key-handoff-e2e-01", summary=SUMMARY)))["job_id"]
        Runner(self.settings, store=self.store).drain()
        self.assertEqual(self.store.get(source_id)["status"], "REVIEW_REQUIRED")
        self.assertEqual(apply_jobs(self.store), [])  # waiting for a person starts nothing

        reply = decide(self.app, review_id_for(source_id), final_category="billing")
        self.assertEqual(reply.status, 201)
        body = body_of(reply)
        [handoff] = body["handoffs"]
        self.assertEqual((handoff["state"], handoff["route_id"], handoff["target_workflow_type"]),
                         ("STARTED", "triage-approved-to-apply", "case_triage.v2.apply"))
        target_id = handoff["target_job_id"]
        target = self.store.get(target_id)
        self.assertEqual(target["status"], "QUEUED")  # committed with the decision, before the reply
        self.assertEqual(target["input"], {"approved_by": "owner", "case_id": "CASE-1",
                                           "decision_id": body["decision"]["decision_id"],
                                           "final_category": "billing", "final_queue": "billing_review"})
        shown = {item["name"]: item for item in handoff["facts"]}
        self.assertEqual({name: item["origin"] for name, item in shown.items()},
                         {"case.id": "input", "case.final_category": "person", "case.final_queue": "person",
                          "review.decision_id": "person", "review.reviewer_role": "person"})
        self.assertIn("request.text", handoff["left_out"])

        Runner(self.settings, store=self.store).drain()
        done = body_of(get(self.app, f"/v1/jobs/{target_id}"))
        self.assertEqual(done["status"], "COMPLETED")
        self.assertEqual([step["id"] for step in done["plan"]], ["record_routing"])
        record = done["result"]["output"]
        self.assertEqual((record["kind"], record["final_queue"], record["decision_id"], record["sends_outside"]),
                         ("routing_record", "billing_review", body["decision"]["decision_id"], False))
        self.assertEqual(len(done["result"]["receipt"]["sha256"]), 64)  # Core's verified receipt for the approval
        self.assertEqual(done["handoff"]["from"]["source_job_id"], source_id)
        self.assertEqual(done["handoff"]["to"], [])
        source = body_of(get(self.app, f"/v1/jobs/{source_id}"))
        self.assertEqual(source["status"], "APPROVED")
        self.assertEqual([item["target_job_id"] for item in source["handoff"]["to"]], [target_id])
        self.assertIsNone(source["handoff"]["from"])
        listed = {job["job_id"]: job for job in body_of(get(self.app, "/v1/jobs"))["jobs"]}
        self.assertEqual((listed[target_id]["from_job_id"], listed[source_id]["from_job_id"]), (source_id, None))

        kinds = [event["kind"] for event in self.store.events(source_id, limit=100)[0]]
        self.assertEqual(kinds[-2:], ["review.approved", "handoff.started"])
        queued = self.store.admission(target_id)
        self.assertEqual((queued["from_job_id"], queued["route_id"]), (source_id, "triage-approved-to-apply"))
        # The case text never travels to the next skill and never reaches an event.
        self.assertNotIn(SUMMARY, all_event_text(self.store, [source_id, target_id]))
        self.assertNotIn(SUMMARY, json.dumps(self.store.handoffs_from(source_id), ensure_ascii=False))
        self.assertNotIn(SUMMARY, json.dumps(target["input"]))
        self.assertEqual(self.store.handoff_counts(), {"STARTED": 1, "REFUSED": 0})

    def test_a_rejection_starts_nothing(self):
        job_id = waiting_job(self.store, "key-handoff-reject-1")
        body = body_of(decide(self.app, review_id_for(job_id), decision="REJECT"))
        self.assertEqual(body["handoffs"], [])
        self.assertEqual((apply_jobs(self.store), self.store.handoffs_from(job_id)), ([], []))

    def test_the_same_click_again_returns_the_same_handoff(self):
        job_id = waiting_job(self.store, "key-handoff-again-1")
        first = body_of(decide(self.app, review_id_for(job_id)))
        again = decide(self.app, review_id_for(job_id))
        self.assertEqual(again.status, 200)
        self.assertEqual(body_of(again)["handoffs"], first["handoffs"])
        self.assertEqual(len(apply_jobs(self.store)), 1)

    def test_sixteen_identical_clicks_at_once_make_one_handoff(self):
        job_id = waiting_job(self.store, "key-handoff-burst-1")
        replies = []

        def click():
            replies.append(decide(self.app, review_id_for(job_id)))

        threads = [threading.Thread(target=click) for _ in range(16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(reply.status for reply in replies), [200] * 15 + [201])
        self.assertEqual(len(self.store.handoffs_from(job_id)), 1)
        self.assertEqual(len(apply_jobs(self.store)), 1)

    def test_sixteen_different_decisions_at_once_hand_on_at_most_once(self):
        job_id = waiting_job(self.store, "key-handoff-race-1")
        replies = []

        def click(index):
            fields = {"idempotency_key": f"web-race-{index:04d}"}
            if index % 2:
                fields["decision"] = "REJECT"
            replies.append(decide(self.app, review_id_for(job_id), **fields))

        threads = [threading.Thread(target=click, args=(i,)) for i in range(16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(reply.status for reply in replies), [201] + [409] * 15)
        approved = self.store.get(job_id)["status"] == "APPROVED"
        self.assertEqual(len(self.store.handoffs_from(job_id)), 1 if approved else 0)
        self.assertEqual(len(apply_jobs(self.store)), 1 if approved else 0)

    def test_a_failure_inside_the_transaction_leaves_nothing(self):
        job_id = waiting_job(self.store, "key-handoff-atomic-1")
        with mock.patch.object(QueueStore, "_insert_job", side_effect=sqlite3.OperationalError("disk I/O error")):
            self.assertEqual(decide(self.app, review_id_for(job_id)).status, 500)
        self.assertEqual(self.store.get(job_id)["status"], "REVIEW_REQUIRED")
        self.assertEqual(self.store.get_review(review_id_for(job_id))["decisions"], [])
        self.assertEqual((self.store.handoffs_from(job_id), apply_jobs(self.store)), ([], []))
        retried = decide(self.app, review_id_for(job_id))  # the same click again, once the disk works
        self.assertEqual(retried.status, 201)
        self.assertEqual(len(apply_jobs(self.store)), 1)

    def test_a_refused_handoff_keeps_the_approval_and_says_why(self):
        def broken(_source):
            raise RuntimeError("a translator bug")
        real = TRANSLATORS["out.case_triage.v2@1"]
        translators = dict(TRANSLATORS, **{"out.case_triage.v2@1": Translator(
            real.name, real.version, "out", real.workflow_type, real.facts, broken, states=real.states)})
        app = ApiApp(self.settings, self.store, exchange=Exchange(CATALOG, translators=translators))
        job_id = waiting_job(self.store, "key-handoff-refuse-1")
        reply = decide(app, review_id_for(job_id))
        self.assertEqual(reply.status, 201)
        [handoff] = body_of(reply)["handoffs"]
        self.assertEqual((handoff["state"], handoff["reason"], handoff["target_job_id"]),
                         ("REFUSED", "translator_error", None))
        self.assertEqual(self.store.get(job_id)["status"], "APPROVED")  # the person's decision stands
        self.assertEqual(apply_jobs(self.store), [])
        event = self.store.events(job_id, limit=100)[0][-1]
        self.assertEqual((event["kind"], event["payload"]["reason"]), ("handoff.refused", "translator_error"))
        self.assertEqual(body_of(get(app, f"/v1/jobs/{job_id}"))["handoff"]["to"][0]["state"], "REFUSED")
        self.assertEqual(self.store.handoff_counts(), {"STARTED": 0, "REFUSED": 1})


class StatusAndAdmissionTests(ApiTestCase):
    def test_status_lists_the_routes_in_plain_words_and_marks_route_only_skills(self):
        status = body_of(get(self.app, "/v1/status"))
        handoff = status["handoff"]
        self.assertEqual([route["id"] for route in handoff["routes"]], ["triage-approved-to-apply"])
        self.assertRegex(handoff["routes"][0]["why"]["th"], r"[฀-๿]")
        self.assertRegex(handoff["facts"]["case.final_category"]["meaning"]["th"], r"[฀-๿]")
        self.assertTrue(handoff["routes_version"].startswith("routes-v1@sha256:"))
        self.assertEqual(handoff["counts"], {"STARTED": 0, "REFUSED": 0})
        flags = {item["name"]: item["route_only"] for item in status["workflows"]}
        self.assertEqual(flags, {"case_triage.v2": False, "case_triage.v1": False, "study_guide.v1": False,
                                 "case_triage.v2.apply": True})
        self.assertNotIn("pattern", json.dumps(handoff))

    def test_posting_a_route_only_skill_is_refused(self):
        reply = post(self.app, {"workflow_type": "case_triage.v2.apply", "idempotency_key": "web-decide-forged",
                                "input": {"case_id": "C-1", "final_category": "billing", "final_queue": "billing_review",
                                          "decision_id": "dec_" + "b" * 24, "approved_by": "owner"}})
        self.assertEqual(reply.status, 400)
        self.assertEqual(body_of(reply)["error"], "unknown_workflow_type")
        self.assertNotIn("case_triage.v2.apply", body_of(reply)["allowed"])
        self.assertEqual(self.jobs_in_store(), [])


# -- a route from COMPLETED, through the Runner ---------------------------------------------------

def note(message):
    return {"case_id": message["input"]["case_id"], "step": message["params"]["name"]}


def validate_note(message, output):
    if output != note(message):
        raise ValueError("unexpected note")


def _informational(name):
    def build(job_id, case, _config):
        return {"job_id": job_id, "input": case,
                "steps": [{"id": "note", "agent": f"{name}.note", "max_attempts": 1, "params": {"name": name}}]}
    return WorkflowType(name, "test only: one informational step", "note", check_case, build,
                        lambda _config: [AgentDefinition(f"{name}.note", "tests.test_service_handoff:note",
                                                         validate_note, version="1")])


def _out(name):
    def give(source):
        return {"case.id": fact(source.result["output"]["case_id"], "input"),
                "request.text": fact(source.input["summary"], "input")}
    return Translator(f"out.{name}", 1, "out", name, ("case.id", "request.text"), give, states=("COMPLETED",))


def _in(name):
    return Translator(f"in.{name}", 1, "in", name, ("case.id",),
                      lambda facts: {"case_id": facts["case.id"]["value"], "summary": "handed on by the exchange"})


def chain_exchange(catalog, *, max_depth=3):
    routes = [{"id": f"{a.replace('.', '-')}-to-{b.replace('.', '-')}", "from": a, "on": "COMPLETED", "to": b,
               "out": f"out.{a}@1", "in": f"in.{b}@1", "needs": ["case.id"], "why": {"en": "test", "th": "ทดสอบ"}}
              for a, b in (("test.first", "test.second"), ("test.second", "test.third"))]
    translators = {t.tag: t for name in ("test.first", "test.second", "test.third") for t in (_out(name), _in(name))}
    table = RouteTable.parse({"version": "routes-test", "max_depth": max_depth, "routes": routes}, "routes-test@sha256:0")
    return Exchange(catalog, table=table, translators=translators)


class RunnerHandoffTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.catalog = {name: _informational(name) for name in ("test.first", "test.second", "test.third")}

    def first_job(self):
        job, _ = admit(self.store, case_body("key-chain-00001", summary=SUMMARY, workflow_type="test.first"),
                       max_queued=10, catalog=self.catalog)
        return job["job_id"]

    def test_a_completed_job_is_handed_on_once_even_after_a_crash_before_the_commit(self):
        first = self.first_job()
        exchange = chain_exchange(self.catalog)
        real_finish = QueueStore.finish
        calls = []

        def crash_once(store, *args, **kwargs):
            if not calls:
                calls.append(1)
                raise KeyboardInterrupt  # the process dies after Core finished, before the outcome is committed
            return real_finish(store, *args, **kwargs)

        with mock.patch.object(QueueStore, "finish", crash_once):
            with self.assertRaises(KeyboardInterrupt):
                Runner(self.settings, store=self.store, catalog=self.catalog, exchange=exchange).drain()
            self.assertEqual(self.store.get(first)["status"], "RUNNING")
            self.assertEqual(self.store.handoffs_from(first), [])
            Runner(self.settings, store=self.store, catalog=self.catalog, exchange=exchange).drain()
        jobs = {job["workflow_type"]: job for job in self.store.list_jobs(limit=100)[0]}
        self.assertEqual(sorted(jobs), ["test.first", "test.second", "test.third"])
        self.assertEqual({job["status"] for job in jobs.values()}, {"COMPLETED"})
        self.assertEqual(len(self.store.handoffs_from(first)), 1)
        self.assertEqual([h["depth"] for h in self.store.handoffs_from(jobs["test.second"]["job_id"])], [2])
        self.assertNotIn(SUMMARY, json.dumps([self.store.handoffs_from(j["job_id"]) for j in jobs.values()]))

    def test_a_chain_stops_at_the_tables_depth(self):
        first = self.first_job()
        Runner(self.settings, store=self.store, catalog=self.catalog,
               exchange=chain_exchange(self.catalog, max_depth=1)).drain()
        [started] = self.store.handoffs_from(first)
        [refused] = self.store.handoffs_from(started["target_job_id"])
        self.assertEqual((started["state"], refused["state"], refused["reason"]), ("STARTED", "REFUSED", "chain_too_long"))
        self.assertEqual(sorted(job["workflow_type"] for job in self.store.list_jobs(limit=100)[0]),
                         ["test.first", "test.second"])


class DemoAndCheckTests(unittest.TestCase):
    def test_the_owner_demo_runs_and_every_guarantee_holds(self):
        from examples.skill_handoff_demo import CASE, run
        with tempfile.TemporaryDirectory() as folder:
            report, ok = run(folder)
        self.assertTrue(ok, report)
        for heading in ("ขั้น 1", "ขั้น 2", "ขั้น 3", "ขั้น 4", "ขั้น 5"):
            self.assertIn(heading, report)
        self.assertIn("ไม่ส่ง (เส้นทางนี้ไม่ใช้)", report)
        self.assertEqual(report.count(CASE["summary"]), 1)  # quoted once as what was sent; never as a fact value

    def test_the_handoff_checks_decision_pattern_covers_every_kind(self):
        from tests.handoff_check import SETS, plan_for
        plans = [plan_for(i, "billing") for i in range(15)]
        self.assertEqual(sum(p[0] == "REJECT" for p in plans), 3)
        self.assertTrue(any(p == ("APPROVE", "billing") for p in plans))
        self.assertTrue(any(p[0] == "APPROVE" and p[1] not in ("billing", None) for p in plans))
        self.assertTrue(all(path.exists() for path in SETS.values()))


class MigrationTests(ApiTestCase):
    def test_a_version_2_queue_is_upgraded_to_3_and_keeps_its_jobs(self):
        job_id = waiting_job(self.store, "key-upgrade-v2-001")
        with raw_db(self.store.path) as db:
            db.executescript("DROP TABLE handoffs; UPDATE meta SET value='2' WHERE key='schema_version';")
        store = QueueStore(self.store.path)
        store.migrate()
        with raw_db(self.store.path) as db:
            self.assertEqual(db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], "3")
        self.assertEqual(store.get(job_id)["status"], "REVIEW_REQUIRED")
        self.assertEqual(store.handoff_counts(), {"STARTED": 0, "REFUSED": 0})
        self.assertEqual(body_of(decide(ApiApp(self.settings, store), review_id_for(job_id)))["handoffs"][0]["state"],
                         "STARTED")


if __name__ == "__main__":
    unittest.main()
