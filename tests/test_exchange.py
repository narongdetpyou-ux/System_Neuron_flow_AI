"""The skill-handoff exchange on its own (ADR-030, docs/skill_handoff.md): the language, the translators, the route
table, every refusal code, and the isolation between skills. The queue, the Runner and the API are in
``tests/test_service_handoff.py``.
"""

import ast
import copy
import hashlib
from pathlib import Path
import unittest

from neuron_flow import SpecError

from app.domains.case_triage import check_apply_input
from app.exchange import (ENVELOPE_VERSION, REASONS, TRANSLATORS, Exchange, ExchangeConfigError, FactInvalid,
                          RouteTable, SourceIncomplete, SourceView, Translator, Vocabulary)
from app.exchange.common import VOCABULARY_FILE, fact
from app.exchange.routes import ROUTES_FILE
from app.services.admission import request_fingerprint
from app.services.workflows import CATALOG, WorkflowType, admissible, check_case

ROOT = Path(__file__).resolve().parent.parent
DECISION = {"decision_id": "dec_" + "b" * 24, "decision": "APPROVE", "final_category": "billing",
            "reviewer_role": "owner", "reason": "ลูกค้าพูดถึงการหักเงินซ้ำ"}
SUMMARY = "I was charged twice this month, please refund"


def approved_job(**changes):
    job = {"job_id": "job_" + "a" * 24, "workflow_type": "case_triage.v2", "status": "APPROVED",
           "input": {"case_id": "C-1", "summary": SUMMARY},
           "result": {"review": {"suggested_category": "billing", "second_opinion": {"status": "ok", "category": "billing"}}}}
    job.update(changes)
    return job


def table(routes, max_depth=3):
    return RouteTable.parse({"version": "routes-test", "max_depth": max_depth, "routes": routes}, "routes-test@sha256:0")


def route(**changes):
    item = {"id": "triage-approved-to-apply", "from": "case_triage.v2", "on": "APPROVED", "to": "case_triage.v2.apply",
            "out": "out.case_triage.v2@1", "in": "in.case_triage.v2.apply@1",
            "needs": ["case.id", "case.final_category", "case.final_queue", "review.decision_id", "review.reviewer_role"],
            "why": {"en": "test", "th": "ทดสอบ"}}
    item.update(changes)
    return item


def with_translators(**replaced):
    translators = dict(TRANSLATORS)
    for tag, translator in replaced.items():
        translators[tag] = translator
    return translators


def out_translator(function, facts=None):
    real = TRANSLATORS["out.case_triage.v2@1"]
    return Translator(real.name, real.version, "out", real.workflow_type, tuple(facts or real.facts), function,
                      states=real.states)


class VocabularyTests(unittest.TestCase):
    def setUp(self):
        self.vocabulary = Vocabulary.load()

    def test_the_tag_names_the_complete_sha256_of_the_file(self):
        digest = hashlib.sha256(VOCABULARY_FILE.read_bytes()).hexdigest()
        self.assertEqual(self.vocabulary.tag, f"vocabulary-v1@sha256:{digest}")
        self.assertEqual(set(self.vocabulary.origins), {"input", "rules", "person", "ai"})

    def test_good_facts_pass(self):
        good = {"request.text": fact("สวัสดี ระบบเข้าไม่ได้", "input"), "case.id": fact("WEB-1", "input"),
                "case.final_category": fact("access", "person"), "case.final_queue": fact("access_review", "person"),
                "case.second_opinion": fact("other", "ai"), "review.decision_id": fact("dec_" + "0" * 24, "person")}
        for name, item in good.items():
            with self.subTest(name=name):
                self.vocabulary.check(name, item)

    def test_bad_facts_are_refused_with_a_reason_and_never_their_value(self):
        bad = [
            ("case.unknown", fact("x", "input"), "unknown_fact"),
            ("case.id", {"value": "C-1"}, "bad_shape"),
            ("case.id", {"value": "C-1", "origin": "input", "extra": 1}, "bad_shape"),
            ("case.final_category", fact("access", "ai"), "bad_origin"),      # an AI cannot speak as a person
            ("case.final_category", fact("access", "rules"), "bad_origin"),
            ("case.second_opinion", fact("access", "person"), "bad_origin"),
            ("case.final_category", fact("refund", "person"), "bad_value"),
            ("case.final_queue", fact("access", "person"), "bad_value"),
            ("case.id", fact("has space", "input"), "bad_value"),
            ("case.id", fact(7, "input"), "bad_value"),
            ("review.decision_id", fact("dec_123", "person"), "bad_value"),
            ("request.text", fact("", "input"), "bad_value"),
            ("request.text", fact("x" * 501, "input"), "bad_value"),
            ("request.text", fact("bell\x07", "input"), "bad_value"),
            ("request.text", fact("half \ud83d emoji", "input"), "bad_value"),
            ("request.text", fact(None, "input"), "bad_value"),
        ]
        for name, item, why in bad:
            with self.subTest(name=name, why=why):
                with self.assertRaises(FactInvalid) as caught:
                    self.vocabulary.check(name, item)
                self.assertEqual(caught.exception.why, why)
                if isinstance(item.get("value"), str) and item["value"]:
                    self.assertNotIn(item["value"], str(caught.exception))

    def test_the_view_has_meanings_in_thai_and_no_patterns(self):
        view = self.vocabulary.view()
        self.assertEqual(set(view), set(self.vocabulary.facts))
        for name, entry in view.items():
            with self.subTest(name=name):
                self.assertEqual(set(entry), {"type", "origins", "meaning"})
                self.assertRegex(entry["meaning"]["th"], r"[฀-๿]")


class RouteTableTests(unittest.TestCase):
    def test_the_committed_table_loads_with_its_complete_hash(self):
        loaded = RouteTable.load()
        digest = hashlib.sha256(ROUTES_FILE.read_bytes()).hexdigest()
        self.assertEqual(loaded.tag, f"routes-v1@sha256:{digest}")
        self.assertEqual([r.id for r in loaded.routes], ["triage-approved-to-apply"])
        self.assertLessEqual(loaded.max_depth, 3)

    def test_bad_tables_are_refused(self):
        cases = {
            "extra field": [route(extra=1)],
            "bad id": [route(id="Bad Id")],
            "start state": [route(on="REVIEW_REQUIRED")],
            "rejected": [route(on="REJECTED")],
            "no needs": [route(needs=[])],
            "repeated need": [route(needs=["case.id", "case.id"])],
            "no Thai": [route(why={"en": "only English"})],
            "same id twice": [route(), route(on="COMPLETED")],
        }
        for label, routes in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(ValueError):
                    table(routes)
        for depth in (0, 4):
            with self.subTest(depth=depth):
                with self.assertRaises(ValueError):
                    table([route()], max_depth=depth)


class ExchangeCheckTests(unittest.TestCase):
    def test_the_committed_routes_fit_the_catalog(self):
        exchange = Exchange(CATALOG)
        self.assertEqual(exchange.route_for("case_triage.v2", "APPROVED").target, "case_triage.v2.apply")
        for state in ("REVIEW_REQUIRED", "REJECTED", "COMPLETED", "FAILED", "CANCELLED"):
            self.assertIsNone(exchange.route_for("case_triage.v2", state))
        self.assertIsNone(exchange.route_for("study_guide.v1", "COMPLETED"))  # paused; no route starts from it
        view = exchange.view()
        self.assertEqual(view["envelope_version"], ENVELOPE_VERSION)
        self.assertEqual(view["reasons"], list(REASONS))
        self.assertTrue(view["routes"][0]["why"]["th"].startswith("บันทึก"))

    def test_a_route_that_does_not_fit_is_refused_at_start(self):
        triage_only = {name: CATALOG[name] for name in ("case_triage.v2",)}
        cases = {
            "target not in catalog": (triage_only, [route()], None),
            "two routes for one state": (CATALOG, [route(), route(id="second-route")], None),
            "unknown out-translator": (CATALOG, [route(out="out.nothing@1")], None),
            "in-translator as out": (CATALOG, [route(out="in.case_triage.v2.apply@1")], None),
            "wrong state for out": (CATALOG, [route(on="COMPLETED")], None),
            "in-translator of another skill": (CATALOG, [route(**{"in": "out.case_triage.v2@1"})], None),
            "fact outside the vocabulary": (CATALOG, [route(needs=route()["needs"] + ["case.secret"])], None),
            "fact the out-translator cannot give": (
                CATALOG, [route()],
                {"out.case_triage.v2@1": out_translator(lambda s: {}, facts=["case.id"])}),
            "in-translator reads more than carried": (CATALOG, [route(needs=route()["needs"][:-1])], None),
        }
        for label, (catalog, routes, replaced) in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(ExchangeConfigError):
                    Exchange(catalog, table=table(routes), translators=with_translators(**(replaced or {})))

    def test_a_cycle_is_refused(self):
        def informational(name):
            return WorkflowType(name, "test only", "x", check_case, lambda *a: None, lambda c: [])
        catalog = {"test.a": informational("test.a"), "test.b": informational("test.b")}
        translators = {
            "out.a@1": Translator("out.a", 1, "out", "test.a", ("case.id",), lambda s: {}, states=("COMPLETED",)),
            "in.a@1": Translator("in.a", 1, "in", "test.a", ("case.id",), lambda f: {}),
            "out.b@1": Translator("out.b", 1, "out", "test.b", ("case.id",), lambda s: {}, states=("COMPLETED",)),
            "in.b@1": Translator("in.b", 1, "in", "test.b", ("case.id",), lambda f: {}),
        }
        routes = [route(id="a-to-b", **{"from": "test.a", "to": "test.b", "on": "COMPLETED", "out": "out.a@1",
                                        "in": "in.b@1", "needs": ["case.id"]}),
                  route(id="b-to-a", **{"from": "test.b", "to": "test.a", "on": "COMPLETED", "out": "out.b@1",
                                        "in": "in.a@1", "needs": ["case.id"]})]
        with self.assertRaisesRegex(ExchangeConfigError, "cycle"):
            Exchange(catalog, table=table(routes), translators=translators)

    def test_a_catalog_without_the_source_skill_has_no_route(self):
        exchange = Exchange({"study_guide.v1": CATALOG["study_guide.v1"]})
        self.assertEqual(exchange.routes, ())


class TranslatorTests(unittest.TestCase):
    """Golden outputs: a changed output with an unchanged version fails here (ADR-030, rule 5)."""

    def source(self, **changes):
        job = approved_job(**changes)
        return SourceView(job["workflow_type"], job["status"], job["input"], job["result"], DECISION)

    def test_out_case_triage_v2_at_1(self):
        out = TRANSLATORS["out.case_triage.v2@1"]
        self.assertEqual(out.function(self.source()), {
            "request.text": fact(SUMMARY, "input"),
            "case.id": fact("C-1", "input"),
            "case.suggested_category": fact("billing", "rules"),
            "case.final_category": fact("billing", "person"),
            "case.final_queue": fact("billing_review", "person"),
            "review.decision_id": fact("dec_" + "b" * 24, "person"),
            "review.reviewer_role": fact("owner", "person"),
            "case.second_opinion": fact("billing", "ai"),
        })
        unavailable = self.source(result={"review": {"suggested_category": "other",
                                                     "second_opinion": {"status": "unavailable"}}})
        self.assertNotIn("case.second_opinion", out.function(unavailable))  # no AI answer, no AI fact
        self.assertEqual(out.function(self.source()), out.function(self.source()))  # pure

    def test_out_refuses_what_is_not_an_approval(self):
        out = TRANSLATORS["out.case_triage.v2@1"]
        sources = [
            SourceView("case_triage.v2", "REJECTED", {}, approved_job()["result"], dict(DECISION, decision="REJECT")),
            SourceView("case_triage.v2", "APPROVED", {}, {"review": None}, DECISION),
            SourceView("case_triage.v2", "APPROVED", {}, None, DECISION),
            SourceView("case_triage.v2", "APPROVED", {}, approved_job()["result"], None),
            SourceView("case_triage.v2", "APPROVED", {}, approved_job()["result"], dict(DECISION, final_category=None)),
        ]
        for source in sources:
            with self.subTest(source=source):
                with self.assertRaises(SourceIncomplete):
                    out.function(source)

    def test_in_case_triage_v2_apply_at_1(self):
        inp = TRANSLATORS["in.case_triage.v2.apply@1"]
        facts = {"case.id": fact("C-1", "input"), "case.final_category": fact("billing", "person"),
                 "case.final_queue": fact("billing_review", "person"),
                 "review.decision_id": fact("dec_" + "b" * 24, "person"), "review.reviewer_role": fact("owner", "person")}
        built = inp.function(facts)
        self.assertEqual(built, {"case_id": "C-1", "final_category": "billing", "final_queue": "billing_review",
                                 "decision_id": "dec_" + "b" * 24, "approved_by": "owner"})
        self.assertEqual(check_apply_input(built), dict(sorted(built.items())))  # the target's own door accepts it


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.exchange = Exchange(CATALOG)

    def test_an_approval_becomes_one_target_job_through_the_common_language(self):
        plan = self.exchange.prepare(approved_job(), decision=DECISION)
        self.assertEqual((plan["state"], plan["reason"], plan["depth"]), ("STARTED", None, 1))
        target = plan["target"]
        self.assertEqual(target["idempotency_key"], "handoff:job_" + "a" * 24 + ":triage-approved-to-apply")
        self.assertRegex(target["job_id"], r"^job_[0-9a-f]{24}$")
        self.assertEqual(target["input"], check_apply_input(target["input"]))
        self.assertEqual(target["request_fingerprint"], request_fingerprint("case_triage.v2.apply", target["input"]))
        envelope = plan["envelope"]
        self.assertEqual(set(envelope["facts"]), set(self.exchange.route_for("case_triage.v2", "APPROVED").needs))
        self.assertEqual(envelope["left_out"], ["case.second_opinion", "case.suggested_category", "request.text"])
        self.assertEqual((envelope["source"]["state"], envelope["out"], envelope["depth"]),
                         ("APPROVED", "out.case_triage.v2@1", 1))
        # Data minimisation: the case text and the reviewer's reason are never carried to the next skill.
        self.assertNotIn(SUMMARY, repr(plan))
        self.assertNotIn(DECISION["reason"], repr(plan))

    def test_no_route_no_plan(self):
        for job in (approved_job(status="REVIEW_REQUIRED"), approved_job(status="REJECTED"),
                    approved_job(workflow_type="study_guide.v1", status="COMPLETED"),
                    approved_job(workflow_type="case_triage.v1")):
            with self.subTest(job=(job["workflow_type"], job["status"])):
                self.assertIsNone(self.exchange.prepare(job, decision=DECISION))

    def refused(self, exchange=None, job=None, decision=DECISION, depth=0):
        plan = (exchange or self.exchange).prepare(job or approved_job(), decision=decision, depth=depth)
        self.assertEqual(plan["state"], "REFUSED")
        self.assertIsNone(plan["target"])
        return plan

    def test_every_refusal_code_is_reached_and_nothing_is_guessed(self):
        def raising(_source):
            raise KeyError("a bug")
        bad_in = Translator("in.case_triage.v2.apply", 1, "in", "case_triage.v2.apply",
                            TRANSLATORS["in.case_triage.v2.apply@1"].facts, lambda facts: {"case_id": "only this"})
        real = TRANSLATORS["out.case_triage.v2@1"].function
        reached = {
            "source_incomplete": self.refused(job=approved_job(result={"review": None})),
            "fact_invalid": self.refused(decision=dict(DECISION, decision_id="dec_not_hex")),
            "fact_missing": self.refused(Exchange(CATALOG, translators=with_translators(**{
                "out.case_triage.v2@1": out_translator(lambda s: {k: v for k, v in real(s).items()
                                                                  if k != "review.decision_id"})}))),
            "target_input_invalid": self.refused(Exchange(CATALOG, translators=with_translators(**{
                "in.case_triage.v2.apply@1": bad_in}))),
            "chain_too_long": self.refused(depth=3),
            "translator_error": self.refused(Exchange(CATALOG, translators=with_translators(**{
                "out.case_triage.v2@1": out_translator(raising)}))),
        }
        self.assertEqual({code: plan["reason"] for code, plan in reached.items()}, {code: code for code in REASONS})
        self.assertEqual(reached["translator_error"]["error_type"], "KeyError")
        self.assertIsNone(reached["source_incomplete"]["envelope"])
        self.assertIsNotNone(reached["target_input_invalid"]["envelope"])  # translated, then refused at the door

    def test_a_translator_may_give_only_what_it_declares_and_an_ai_cannot_speak_as_a_person(self):
        real = TRANSLATORS["out.case_triage.v2@1"].function
        undeclared = out_translator(lambda s: dict(real(s), **{"case.id": fact("C-1", "input")}),
                                    facts=[f for f in TRANSLATORS["out.case_triage.v2@1"].facts if f != "request.text"])
        plan = self.refused(Exchange(CATALOG, translators=with_translators(**{"out.case_triage.v2@1": undeclared})))
        self.assertEqual(plan["reason"], "fact_invalid")
        posing = out_translator(lambda s: dict(real(s), **{"case.final_category": fact("access", "ai")}))
        plan = self.refused(Exchange(CATALOG, translators=with_translators(**{"out.case_triage.v2@1": posing})))
        self.assertEqual(plan["reason"], "fact_invalid")

    def test_a_handoff_view_shows_codes_and_ids_but_only_the_length_of_text(self):
        plan = self.exchange.prepare(approved_job(), decision=DECISION)
        envelope = copy.deepcopy(plan["envelope"])
        envelope["facts"]["request.text"] = fact(SUMMARY, "input")
        row = {"handoff_id": plan["handoff_id"], "route_id": plan["route_id"], "state": "STARTED", "reason": None,
               "source_job_id": plan["source_job_id"], "source_state": "APPROVED",
               "target_job_id": plan["target"]["job_id"], "target_workflow_type": "case_triage.v2.apply", "depth": 1,
               "translator_out": plan["translator_out"], "translator_in": plan["translator_in"],
               "routes_tag": plan["routes_tag"], "vocabulary_tag": plan["vocabulary_tag"], "envelope": envelope,
               "envelope_sha256": "0" * 64, "created_at": 0.0}
        view = self.exchange.handoff_view(row)
        shown = {item["name"]: item for item in view["facts"]}
        self.assertEqual(shown["case.final_category"]["value"], "billing")
        self.assertEqual(shown["request.text"], {"name": "request.text", "origin": "input", "chars": len(SUMMARY)})
        self.assertNotIn(SUMMARY, repr(view))


class AdmissionTests(unittest.TestCase):
    def test_a_route_only_skill_cannot_be_admitted_from_outside(self):
        from app.services.admission import AdmissionError, admit
        self.assertTrue(CATALOG["case_triage.v2.apply"].route_only)
        self.assertNotIn("case_triage.v2.apply", admissible(CATALOG))
        body = {"workflow_type": "case_triage.v2.apply", "idempotency_key": "forged-0001",
                "input": {"case_id": "C-1", "final_category": "billing", "final_queue": "billing_review",
                          "decision_id": "dec_" + "b" * 24, "approved_by": "owner"}}
        with self.assertRaises(AdmissionError) as caught:
            admit(None, body, max_queued=10)  # refused before the store is touched
        self.assertEqual((caught.exception.status, caught.exception.code), (400, "unknown_workflow_type"))
        self.assertNotIn("case_triage.v2.apply", caught.exception.extra["allowed"])

    def test_the_apply_input_contract(self):
        good = {"case_id": "C-1", "final_category": "other", "final_queue": "general_review",
                "decision_id": "dec_" + "c" * 24, "approved_by": "owner"}
        self.assertEqual(check_apply_input(good)["final_queue"], "general_review")
        for bad in (dict(good, final_queue="access_review"), dict(good, final_category="refund"),
                    dict(good, decision_id="dec_1"), dict(good, approved_by="ai"), dict(good, extra=1),
                    {k: v for k, v in good.items() if k != "case_id"}, dict(good, case_id="bad id")):
            with self.subTest(bad=bad):
                with self.assertRaises(SpecError):
                    check_apply_input(bad)


class IsolationTests(unittest.TestCase):
    """Skills stay separate: no skill imports another skill or the exchange; a translator imports only its own
    skill's fixed vocabulary (rule 1's direction holds too: domains never import services, the API or the exchange)."""

    @staticmethod
    def imports(path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found.add(node.module)
        return found

    def test_no_skill_imports_another_skill_or_the_exchange(self):
        domains = ROOT / "app" / "domains"
        skills = sorted(p.name for p in domains.iterdir() if p.is_dir() and (p / "__init__.py").exists())
        self.assertGreaterEqual(len(skills), 2)
        for skill in skills:
            for path in sorted((domains / skill).rglob("*.py")):
                for module in self.imports(path):
                    with self.subTest(file=str(path.relative_to(ROOT)), module=module):
                        for other in skills:
                            if other != skill:
                                self.assertFalse(module.startswith(f"app.domains.{other}"))
                        for layer in ("app.exchange", "app.services", "app.api", "app.persistence"):
                            self.assertFalse(module.startswith(layer))

    def test_translators_import_only_their_own_skills_fixed_vocabulary(self):
        folder = ROOT / "app" / "exchange" / "translators"
        for path in sorted(folder.glob("*.py")):
            domain_imports = {m for m in self.imports(path) if m.startswith("app.domains")}
            with self.subTest(file=path.name):
                self.assertTrue(all(m.endswith(".contracts") for m in domain_imports), domain_imports)
                self.assertFalse({m for m in self.imports(path) if m.startswith(("app.llm", "app.services", "socket",
                                                                                  "urllib", "http", "random", "time"))})


if __name__ == "__main__":
    unittest.main()
