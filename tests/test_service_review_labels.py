"""Rules and AI against people's decisions: the reviewer-label scorecard (roadmap 2.8).

Most tests write decided cases into the queue directly, with chosen rules suggestions, AI answers and decisions, so
every expected number can be worked out by hand. One test runs real cases through the Runner (mock AI) and decides
them over the API, the way the page does.
"""

import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from app.api.routes import ApiApp, Request, route_template
from app.domains.case_triage.contracts import QUEUE_FOR
from app.persistence import QueueStore, review_id_for
from app.services import access, review_labels
from app.services.reviews import decide
from app.services.runner import Runner
from tests.service_fixtures import KEY, case_body, settings

ROOT = Path(__file__).resolve().parent.parent
AUTH = {"authorization": f"Bearer {KEY}"}
JSON = {"content-type": "application/json", **AUTH}
RULES_A = "rules:keywords-v2:" + "a" * 64
RULES_C = "rules:keywords-v2:" + "c" * 64
TYPHOON = {"provider": "typhoon", "model": "typhoon-v2.5-30b-a3b-instruct", "prompt_id": "triage_classify_v2",
           "prompt_sha256": "b" * 64, "redaction": "redact-v2"}
LOCAL = dict(TYPHOON, provider="local", model="typhoon2.5-qwen3-4b:0123456789ab")
REVIEWER_1 = {"token_id": "1" * 16, "role": "reviewer"}
REVIEWER_2 = {"token_id": "2" * 16, "role": "reviewer"}


class LabelsTestCase(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.settings = settings(Path(self._temp.name))
        self.store = QueueStore(self.settings.queue_db)
        self.store.migrate()
        self.number = 0

    def tearDown(self):
        self._temp.cleanup()

    def waiting(self, *, rules="billing", ai="billing", ai_status="ok", summary="I was charged twice this month",
                workflow_type="case_triage.v2", rules_source=RULES_A, provenance=TYPHOON):
        """A case the Runner finished as REVIEW_REQUIRED, with this rules suggestion and this AI answer.
        ``ai_status=None`` is a rules-only workflow (no second opinion at all). Returns the review id."""
        self.number += 1
        key = f"key-labels-{self.number:04d}"
        job, created = self.store.admit(job_id="job_" + hashlib.sha256(key.encode()).hexdigest()[:24],
                                        idempotency_key=key, request_fingerprint=key, workflow_type=workflow_type,
                                        input={"case_id": f"LABEL-{self.number}", "summary": summary}, max_queued=1000)
        self.assertTrue(created)
        self.assertEqual(self.store.claim_next("runner-test")["job_id"], job["job_id"])  # nothing else waits
        if ai_status is None:
            second, ai_view = None, None
        elif ai_status == "ok":
            second = {"status": "ok", "category": ai, "queue": QUEUE_FOR[ai], "confidence": "high",
                      "attention": "none", "rationale": "synthetic"}
            ai_view = {"status": "ok", **provenance}
        else:
            second = {"status": "unavailable", "reason": "provider_unavailable"}
            ai_view = {"status": "unavailable", **provenance}
        agreement = None if second is None else (
            "llm_unavailable" if second["status"] != "ok" else "agree" if ai == rules else "disagree")
        proposal = {"case_id": f"LABEL-{self.number}", "suggested_category": rules, "suggested_queue": QUEUE_FOR[rules],
                    "suggestion_source": rules_source, "second_opinion": second, "agreement": agreement,
                    "review_required": True, "review_priority": "normal", "review_reasons": [],
                    "decision": "PENDING_HUMAN_REVIEW", "mode": "shadow" if second is not None else "rules_only"}
        self.store.finish(job["job_id"], "REVIEW_REQUIRED", result={"review": proposal, "ai": ai_view, "steps": []})
        return review_id_for(job["job_id"])

    def decided(self, decision="APPROVE", final=None, *, reviewer=None, reason="ตรวจแล้ว", **case):
        review_id = self.waiting(**case)
        body = {"decision": decision, "reason": reason, "expected_version": 1,
                "idempotency_key": f"key-label-decision-{self.number:04d}"}
        if final is not None:
            body["final_category"] = final
        _review, _row, created = decide(self.store, review_id, body, reviewer=reviewer)
        self.assertTrue(created)
        return review_id

    def report(self, **options):
        return review_labels.report(self.store, **options)


def figures(value):
    return None if value is None else (value["numerator"], value["denominator"])


class ReportTests(LabelsTestCase):
    def test_an_empty_queue_reports_nothing_and_no_rate(self):
        report = self.report()
        self.assertEqual(report["schema"], "neuron-flow-reviewer-labels-v1")
        self.assertIn("not real-world accuracy", report["label_scope"])
        self.assertEqual(report["window"], {"limit": review_labels.WINDOW, "decided": 0, "decided_total": 0,
                                            "truncated": False})
        self.assertEqual(report["totals"], {"decided": 0, "approved": 0, "rejected": 0, "labelled": 0,
                                            "unlabelled": 0, "by_role": {}, "reviewers": 0})
        self.assertEqual(report["groups"], [])

    def test_approvals_and_named_rejections_are_labels_and_a_bare_rejection_is_not(self):
        self.decided("APPROVE", rules="billing", ai="billing")             # as proposed: label billing
        self.decided("APPROVE", "access", rules="upload", ai="access")     # the person sides with the AI
        self.decided("REJECT", "other", rules="access", ai="access")       # both wrong, the right one named
        self.decided("REJECT", rules="other", ai="billing")                # rejected, no category: no label
        self.decided("APPROVE", rules="billing", ai_status="unavailable")  # labelled, but the AI said nothing
        (group,) = self.report()["groups"]
        self.assertEqual({key: group[key] for key in ("decided", "approved", "rejected", "labelled", "unlabelled")},
                         {"decided": 5, "approved": 3, "rejected": 2, "labelled": 4, "unlabelled": 1})
        self.assertEqual(figures(group["rules_match"]), (2, 4))   # the first and the last
        self.assertEqual(figures(group["ai_answered"]), (3, 4))   # not the last
        self.assertEqual(figures(group["ai_match"]), (2, 3))      # out of the cases it answered
        self.assertEqual(figures(group["rules_ai_agree"]), (2, 3))
        # The unlabelled rejection disagreed too, but without a label nobody can say who was right.
        self.assertEqual(group["when_disagreeing"], {"total": 1, "ai_match": 1, "rules_match": 0, "neither": 0})
        self.assertEqual((group["workflow_type"], group["rules"]), ("case_triage.v2", RULES_A))
        self.assertEqual(group["ai"], {"provider": "typhoon", "model": TYPHOON["model"], "prompt_id": "triage_classify_v2",
                                       "prompt_sha256": "b" * 64, "simulated": False})

    def test_every_rate_keeps_its_counts_and_its_95_percent_interval(self):
        self.assertEqual(review_labels.interval_95(0, 0), (None, None))
        self.assertEqual(review_labels.interval_95(2, 3), (0.2077, 0.9385))
        self.assertEqual(review_labels.interval_95(4, 4), (0.5101, 1.0))  # 4 of 4 is not proof of 100%
        self.assertEqual(review_labels.interval_95(0, 5), (0.0, 0.4345))
        self.assertEqual(review_labels.interval_95(30, 40), (0.5981, 0.8581))
        self.assertEqual(review_labels.rate(1, 2), {"numerator": 1, "denominator": 2, "rate": 0.5,
                                                    "low_95": 0.0945, "high_95": 0.9055})
        self.assertEqual(review_labels.rate(0, 0), {"numerator": 0, "denominator": 0, "rate": None,
                                                    "low_95": None, "high_95": None})

    def test_figures_of_two_versions_are_never_added_together(self):
        self.decided(rules="billing", ai="billing")                               # rules A, Typhoon
        self.decided(rules="billing", ai="upload", rules_source=RULES_C)          # another keyword list
        self.decided(rules="access", ai="access", provenance=LOCAL)               # another model
        self.decided(rules="upload", ai_status=None, workflow_type="case_triage.v1",
                     rules_source="rules:keywords-v1")                            # rules only, no AI at all
        groups = self.report()["groups"]
        self.assertEqual([(g["workflow_type"], g["rules"], (g["ai"] or {}).get("provider")) for g in groups],
                         [("case_triage.v1", "rules:keywords-v1", None), ("case_triage.v2", RULES_A, "local"),
                          ("case_triage.v2", RULES_C, "typhoon"), ("case_triage.v2", RULES_A, "typhoon")])  # newest first
        self.assertEqual([g["decided"] for g in groups], [1, 1, 1, 1])
        rules_only = groups[0]
        self.assertEqual(figures(rules_only["rules_match"]), (1, 1))
        # Without an AI in the workflow its figures are missing, not zero.
        for key in ("ai", "ai_answered", "ai_match", "rules_ai_agree", "when_disagreeing"):
            self.assertIsNone(rules_only[key], key)
        self.assertEqual(rules_only["by_language"]["non_th"]["ai_match"], None)

    def test_cases_are_split_by_whether_the_text_holds_a_thai_letter(self):
        self.decided(summary="เดือนนี้ถูกหักค่าบริการสองครั้ง ขอคืนเงินด้วยครับ")
        self.decided(summary="Login ไม่ได้ ช่วยด้วย", rules="access", ai="access")
        self.decided("APPROVE", "upload", summary="I cannot upload an attachment", rules="other", ai="upload")
        (group,) = self.report()["groups"]
        self.assertEqual(set(group["by_language"]), {"th", "non_th"})
        thai, other = group["by_language"]["th"], group["by_language"]["non_th"]
        self.assertEqual((thai["decided"], figures(thai["rules_match"]), figures(thai["ai_match"])), (2, (2, 2), (2, 2)))
        self.assertEqual((other["decided"], figures(other["rules_match"]), figures(other["ai_match"])), (1, (0, 1), (1, 1)))
        self.assertEqual([review_labels.language_of(text) for text in ("ล็อกอินไม่ผ่าน", "12345678", None)],
                         ["th", "non_th", "non_th"])

    def test_only_decided_cases_count_and_the_newest_come_first_up_to_the_window(self):
        self.decided("REJECT", "other")      # the oldest decision
        self.decided("APPROVE")
        self.decided("APPROVE", "upload")
        self.waiting()                       # still waiting for a person: never a label
        everything = self.report()
        self.assertEqual((everything["totals"]["decided"], everything["window"]["truncated"]), (3, False))
        newest = self.report(window=2)
        self.assertEqual(newest["window"], {"limit": 2, "decided": 2, "decided_total": 3, "truncated": True})
        self.assertEqual((newest["totals"]["approved"], newest["totals"]["rejected"]), (2, 0))
        self.assertEqual(figures(newest["groups"][0]["rules_match"]), (1, 2))

    def test_who_decided_is_counted_by_role_and_by_credential(self):
        self.decided()
        self.decided()
        self.decided(reviewer=REVIEWER_1)
        self.decided("REJECT", reviewer=REVIEWER_2)
        totals = self.report()["totals"]
        self.assertEqual((totals["by_role"], totals["reviewers"]), ({"owner": 2, "reviewer": 2}, 3))

    def test_the_report_holds_no_case_text_no_reason_and_no_token(self):
        self.decided(summary="ลูกค้า ZEBRA-7731 ถูกหักเงินซ้ำสองครั้ง", reason="เหตุผลลับ QUOKKA-4402 ของผู้ตรวจ")
        rows, total = self.store.decided_reviews(10)
        self.assertEqual(total, 1)
        self.assertNotIn("reason", rows[0])  # the store never reads the person's words for this
        text = json.dumps(self.report(), ensure_ascii=False)
        for private in ("ZEBRA-7731", "QUOKKA-4402", "ลูกค้า", "เหตุผลลับ", "nf_"):
            self.assertNotIn(private, text)

    def test_it_reads_one_store_method_and_neither_writes_nor_asks_an_ai(self):
        source = (ROOT / "app" / "services" / "review_labels.py").read_text(encoding="utf-8")
        self.assertEqual(sorted(set(re.findall(r"\bstore\.(\w+)\(", source))), ["decided_reviews"])
        imports = re.findall(r"^(?:from|import) ([\w.]+)", source, re.M)
        self.assertEqual(sorted(imports), ["app.persistence.queue_store", "math", "re"])
        # A scorecard decides nothing (rule 4): no workflow, agent, translator or the Runner reads it.
        for path in [*(ROOT / "app" / "domains").rglob("*.py"), *(ROOT / "app" / "exchange").rglob("*.py"),
                     *(ROOT / "app" / "llm").rglob("*.py"), ROOT / "app" / "services" / "runner.py"]:
            self.assertNotIn("review_labels", path.read_text(encoding="utf-8"), path)


class ApiTests(LabelsTestCase):
    def setUp(self):
        super().setUp()
        self.app = ApiApp(self.settings, self.store)

    def call(self, method, path, body=None, *, credential=KEY, client="tester", app=None):
        headers = {"authorization": f"Bearer {credential}"} if credential is not None else {}
        data = b""
        if body is not None:
            headers["content-type"] = "application/json"
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        return (app or self.app).handle(Request(method, path, {}, headers, data, client))

    def issue(self, role):
        response = self.call("POST", "/v1/tokens", {"display_name": f"test {role}", "role": role})
        self.assertEqual(response.status, 201)
        return json.loads(response.body)["token"]

    def test_the_owner_and_reviewers_read_it_and_submitters_do_not(self):
        self.decided()
        self.assertEqual(route_template("/v1/reviews/scorecard"), "/v1/reviews/scorecard")
        self.assertEqual({role for role in access.ROLES if access.allowed("GET", "/v1/reviews/scorecard", role)},
                         {"owner", "reviewer"})
        owner = self.call("GET", "/v1/reviews/scorecard")
        self.assertEqual(owner.status, 200)
        self.assertEqual(json.loads(owner.body)["totals"]["decided"], 1)
        self.assertEqual(self.call("GET", "/v1/reviews/scorecard", credential=self.issue("reviewer")).status, 200)
        refused = self.call("GET", "/v1/reviews/scorecard", credential=self.issue("submitter"))
        self.assertEqual((refused.status, json.loads(refused.body)["error"]), (403, "forbidden"))
        self.assertEqual(self.call("GET", "/v1/reviews/scorecard", credential=None, client="stranger").status, 401)
        self.assertEqual(self.call("HEAD", "/v1/reviews/scorecard").status, 200)
        self.assertEqual(self.call("POST", "/v1/reviews/scorecard", {}).status, 405)

    def test_the_reply_says_how_long_the_labels_last(self):
        free = ApiApp(settings(Path(self._temp.name), storage="local_default"), self.store)
        reply = json.loads(self.call("GET", "/v1/reviews/scorecard", app=free).body)
        self.assertEqual(reply["retention"], {"persistent": False, "lost_on": ["sleep", "restart", "deploy"],
                                              "store_id": self.store.store_info()["id"],
                                              "store_started_at": self.store.store_info()["created_at"]})
        self.assertTrue(json.loads(self.call("GET", "/v1/reviews/scorecard").body)["retention"]["persistent"])

    def test_real_cases_decided_on_the_api_are_counted_against_the_mock(self):
        sent = []
        for number, summary in enumerate(("I cannot upload an attachment",                    # rules upload, mock upload
                                          "เดือนนี้ถูกหักค่าบริการสองครั้ง ขอคืนเงินด้วยครับ",  # billing and billing
                                          "Please add dark mode for users in Billings.")):    # rules other, mock billing
            response = self.call("POST", "/v1/jobs", case_body(f"key-labels-api-{number}", summary=summary,
                                                               case_id=f"API-{number}"))
            self.assertEqual(response.status, 202)
            sent.append(json.loads(response.body)["job_id"])
        Runner(self.settings, store=self.store).drain()
        # As proposed; the person moves the Thai billing case to access; the person keeps the rules' "other".
        for number, (job_id, final) in enumerate(zip(sent, (None, "access", "other"))):
            body = {"decision": "APPROVE", "reason": "ตรวจแล้ว", "expected_version": 1,
                    "idempotency_key": f"key-labels-api-decision-{number}"}
            if final:
                body["final_category"] = final
            response = self.call("POST", f"/v1/reviews/{review_id_for(job_id)}/decisions", body)
            self.assertEqual(response.status, 201, response.body)
        Runner(self.settings, store=self.store).drain()  # the approvals' apply jobs run; they have no review
        reply = json.loads(self.call("GET", "/v1/reviews/scorecard").body)
        self.assertEqual((reply["totals"]["decided"], reply["totals"]["labelled"]), (3, 3))
        (group,) = reply["groups"]
        self.assertEqual((group["ai"]["provider"], group["ai"]["simulated"], group["ai"]["prompt_id"]),
                         ("mock", True, "triage_classify_v2"))
        self.assertTrue(group["rules"].startswith("rules:keywords-v2:"))
        self.assertEqual(figures(group["rules_match"]), (2, 3))
        self.assertEqual(figures(group["ai_match"]), (1, 3))
        self.assertEqual(figures(group["rules_ai_agree"]), (2, 3))
        self.assertEqual(group["when_disagreeing"], {"total": 1, "ai_match": 0, "rules_match": 1, "neither": 0})
        self.assertEqual(figures(group["by_language"]["th"]["rules_match"]), (0, 1))
        self.assertEqual(figures(group["by_language"]["non_th"]["ai_match"]), (1, 2))
        self.assertNotIn("ถูกหักค่าบริการ", json.dumps(reply, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
