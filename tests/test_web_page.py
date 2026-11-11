"""The web page's contracts with the rest of the system (roadmap 3.4, and the page in general).

The page is plain HTML and JavaScript without a test runner, so these tests read its files and hold them to
what the service and the study guide promise:

1. every example on the page passes its workflow's input contract, and the study examples are the requests of
   ``examples/study_guide_demo.py``, answering with the mock AI the way the docs and the owner test say;
2. ``/v1/status`` tells the page both input limits (a case's summary, a study question's message);
3. the page has a Thai name for every step of every workflow in the catalog, and Thai words for every code a
   study answer can carry, equal to the study guide's own Thai labels where it has them;
4. the page never inserts server data as HTML, links only to https addresses that the library could hold,
   opens them without passing on where the person came from, and has no inline script or style;
5. the script parses (with Node.js, when it is installed: GitHub's runners have it);
6. reviews and retention (the independent review of 2026-11-10, points 3 and 4): every job status, decision and
   review error has Thai words; the page never says "saved permanently" without checking the storage; the browser
   keeps only the access key and job ids, never case text; and who decides is never sent from the page.

A headless-browser walkthrough of the page itself is described in docs/intake_queue.md.
"""

from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from app.api.routes import ApiApp
from app.domains.case_triage.contracts import SUMMARY_MAX_CHARS, SUMMARY_MIN_CHARS
from app.domains.study_guide import check_message, load_library
from app.domains.study_guide.contracts import (ANSWER_LANGUAGES, ANSWER_STATUSES, LEVEL_LABELS, MESSAGE_MAX_CHARS,
                                               MESSAGE_MIN_CHARS, PRIORITY_LABELS)
from app.domains.study_guide.library import ACCESS, KINDS, LANGUAGES, LEVELS
from app.llm import LLMConfig
from app.domains.case_triage.contracts import CATEGORIES
from app.persistence import STATUSES, QueueStore
from app.services.reviews import DECISIONS
from app.services.workflows import CATALOG, check_case, preview_spec
from examples.study_guide_demo import REQUESTS as DEMO_REQUESTS
from tests.service_fixtures import settings
from tests.test_service_api import body_of, get
from tests.test_study_guide import inline

WEB = Path(__file__).resolve().parent.parent / "app" / "web"
PAGE = (WEB / "index.html").read_text(encoding="utf-8")
SCRIPT = (WEB / "app.js").read_text(encoding="utf-8")
STYLE = (WEB / "app.css").read_text(encoding="utf-8")


class _Examples(HTMLParser):
    """The ``data-example`` buttons of each ``chips-…`` group (the groups hold no nested div)."""

    def __init__(self):
        super().__init__()
        self.groups, self._group = {}, None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div" and (attrs.get("id") or "").startswith("chips-"):
            self._group = attrs["id"]
            self.groups[self._group] = []
        elif tag == "button" and self._group and "data-example" in attrs:
            self.groups[self._group].append(attrs["data-example"])

    def handle_endtag(self, tag):
        if tag == "div":
            self._group = None


def examples():
    parser = _Examples()
    parser.feed(PAGE)
    return parser.groups


def js_table(name):
    """The string pairs of ``const NAME = { key: "value", … };`` in app.js (bare or quoted keys)."""
    match = re.search(r"\bconst " + re.escape(name) + r" = \{(.*?)\};", SCRIPT, re.S)
    if match is None:
        raise AssertionError(f"app.js has no table {name}; this test reads it, so keep it a plain object of strings")
    pairs = re.findall(r'(?:"([^"]+)"|\b([A-Za-z_][A-Za-z0-9_]*))\s*:\s*"((?:[^"\\]|\\.)*)"', match.group(1))
    return {quoted or bare: value for quoted, bare, value in pairs}


def library_link_pattern():
    """The page's own check for a link address (``LIBRARY_LINK`` in app.js), as a Python pattern."""
    match = re.search(r"const LIBRARY_LINK = /(.+)/;", SCRIPT)
    if match is None:
        raise AssertionError("app.js has no LIBRARY_LINK pattern")
    return re.compile(match.group(1).replace("\\/", "/"))


class ExampleTests(unittest.TestCase):
    def test_every_example_on_the_page_passes_its_input_contract(self):
        groups = examples()
        self.assertEqual(set(groups), {"chips-case", "chips-study"})
        self.assertEqual(len(groups["chips-case"]), 4)
        self.assertEqual(len(groups["chips-study"]), 4)
        for summary in groups["chips-case"]:
            with self.subTest(summary=summary):
                self.assertEqual(check_case({"case_id": "EXAMPLE-1", "summary": summary})["summary"], summary)
        for message in groups["chips-study"]:
            with self.subTest(message=message):
                self.assertEqual(check_message({"message": message}), {"message": message})

    def test_the_study_examples_are_the_demo_requests_and_answer_as_documented(self):
        # The run page of Core logic tests shows the demo's answers, so the owner can read what each example on
        # the page answers with the mock AI. The owner test in docs/ROADMAP.md (3.4) relies on these outcomes.
        study = examples()["chips-study"]
        self.assertCountEqual(study, [text for _job_id, text in DEMO_REQUESTS])
        expected = {
            "อยากมีรั้วกั้นไม่ให้ AI ออกนอกลู่นอกทาง": ("guide", 5),
            "อยากให้ระบบเป็นเหมือนบรรณารักษ์ที่รู้ใจ": ("out_of_scope", 0),  # the keyword mock cannot read the metaphor
            "How do I write a good prompt?": ("guide", 2),
            "ขอสูตรต้มยำกุ้งน้ำข้นหน่อย": ("out_of_scope", 0),
        }
        for message in study:
            with self.subTest(message=message):
                outputs, _messages = inline(message)
                answer = outputs["answer"]
                self.assertEqual((answer["status"], len(answer["steps"])), expected[message])
                if answer["status"] == "out_of_scope":
                    self.assertEqual(len(answer["can_help_with"]), len(load_library().topics))


class StatusTests(unittest.TestCase):
    def test_status_tells_the_page_both_input_limits(self):
        with tempfile.TemporaryDirectory() as folder:
            config = settings(Path(folder))
            store = QueueStore(config.queue_db)
            store.migrate()
            limits = body_of(get(ApiApp(config, store), "/v1/status"))["limits"]
        self.assertEqual((limits["summary_min_chars"], limits["summary_max_chars"]), (SUMMARY_MIN_CHARS, SUMMARY_MAX_CHARS))
        self.assertEqual((limits["message_min_chars"], limits["message_max_chars"]), (MESSAGE_MIN_CHARS, MESSAGE_MAX_CHARS))


class VocabularyTests(unittest.TestCase):
    def test_every_step_of_every_workflow_has_a_thai_name(self):
        names, short = js_table("STEP"), js_table("STEP_SHORT")
        workflows = js_table("WORKFLOW")
        for workflow in CATALOG.values():
            with self.subTest(workflow=workflow.name):
                self.assertIn(workflow.name, workflows)
                for step in preview_spec(workflow, LLMConfig())["steps"]:
                    self.assertIn(step["id"], names)
                    self.assertIn(step["id"], short)
        self.assertIn("study_guide.v1", SCRIPT)

    def test_every_code_of_a_study_answer_has_thai_words(self):
        self.assertEqual(set(js_table("ANSWER_STATUS")), set(ANSWER_STATUSES))
        # Where the study guide has Thai labels of its own, the page uses the same words.
        self.assertEqual(js_table("LEVEL_TH"), LEVEL_LABELS["th"])
        self.assertEqual(set(js_table("LEVEL_TH")), set(LEVELS))
        self.assertEqual(js_table("PRIORITY_TH"), PRIORITY_LABELS["th"])
        self.assertEqual(set(js_table("LANGUAGE_TH")), set(LANGUAGES) | set(ANSWER_LANGUAGES))
        self.assertEqual(set(js_table("ACCESS_TH")), set(ACCESS))
        self.assertEqual(set(js_table("KIND_TH")), set(KINDS))
        for table in ("ANSWER_STATUS", "LEVEL_TH", "PRIORITY_TH", "LANGUAGE_TH", "ACCESS_TH", "KIND_TH"):
            with self.subTest(table=table):
                self.assertTrue(all(re.search(r"[฀-๿]", word) for word in js_table(table).values()))


class SafetyTests(unittest.TestCase):
    def test_server_data_is_never_inserted_as_html(self):
        for unsafe in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function",
                       'setAttribute("style"', "cssText"):
            with self.subTest(unsafe=unsafe):
                self.assertNotIn(unsafe, SCRIPT)
        # No inline script, style attribute or event handler: the Content-Security-Policy forbids them anyway.
        self.assertIsNone(re.search(r"<script(?![^>]*\bsrc=)[^>]*>", PAGE))
        self.assertIsNone(re.search(r"\sstyle=", PAGE))
        self.assertIsNone(re.search(r"\son[a-z]+=", PAGE))

    def test_links_go_only_to_https_addresses_and_tell_no_referrer(self):
        pattern = library_link_pattern()
        for resource in load_library().resources:
            with self.subTest(resource=resource.id):
                self.assertRegex(resource.url, pattern)
        for bad in ("javascript:alert(1)", "http://example.com/", "https://example.com/a b", "//example.com",
                    'https://example.com/"onmouseover="x', "data:text/html,hi", " https://example.com/"):
            with self.subTest(bad=bad):
                self.assertIsNone(pattern.search(bad))
        # The page builds exactly one kind of link, and only after that check.
        self.assertEqual(SCRIPT.count("href:"), 1)
        builder = SCRIPT[SCRIPT.index("function resourceLink"):]
        builder = builder[:builder.index("\n  }\n")]
        self.assertIn("LIBRARY_LINK.test(", builder)
        self.assertIn('rel: "noopener noreferrer"', builder)
        self.assertEqual(SCRIPT.count('target: "_blank"'), SCRIPT.count('rel: "noopener noreferrer"'))
        self.assertIn('name="referrer" content="no-referrer"', PAGE)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_the_script_parses(self):
        result = subprocess.run([shutil.which("node"), "--check", str(WEB / "app.js")], capture_output=True, text=True,
                                timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_stylesheet_has_balanced_braces(self):
        without_comments = re.sub(r"/\*.*?\*/", "", STYLE, flags=re.S)
        depth = 0
        for character in without_comments:
            depth += {"{": 1, "}": -1}.get(character, 0)
            self.assertGreaterEqual(depth, 0)
        self.assertEqual(depth, 0)


if __name__ == "__main__":
    unittest.main()


class ReviewAndRetentionTests(unittest.TestCase):
    def test_every_status_decision_and_review_error_has_thai_words(self):
        self.assertEqual(set(js_table("STATUS")), set(STATUSES))
        self.assertEqual(set(js_table("DECISION")), set(DECISIONS))
        self.assertTrue(set(CATEGORIES) <= set(js_table("CATEGORY")))
        errors = js_table("API_ERROR")
        for code in ("invalid_decision", "invalid_category", "invalid_reason", "invalid_version", "already_decided",
                     "version_conflict", "not_reviewable", "review_not_found", "idempotency_conflict", "rate_limited"):
            with self.subTest(code=code):
                self.assertIn(code, errors)
        for status in ("APPROVED", "REJECTED"):
            self.assertIn(f'"{status}"', SCRIPT[SCRIPT.index("const TERMINAL"):SCRIPT.index("const CASE_ID")])

    def test_permanent_storage_is_only_claimed_after_checking_it(self):
        # Before 2026-11-10 the page said "บันทึกถาวรแล้ว" (saved permanently) on Render's free plan, which forgets.
        for line in SCRIPT.splitlines():
            if "บันทึกถาวร" in line:
                with self.subTest(line=line.strip()[:80]):
                    self.assertTrue("persistent()" in line or "persistent ?" in line, line)

    def test_the_browser_keeps_the_key_and_job_ids_only(self):
        writes = re.findall(r"(localStorage|sessionStorage)\.setItem\(([A-Z_]+)", SCRIPT)
        self.assertEqual({name for _store, name in writes}, {"KEY_STORAGE", "SENT_STORAGE"})
        remember = SCRIPT[SCRIPT.index("function rememberSent"):]
        remember = remember[:remember.index("\n  }\n")]
        self.assertIn("JOB_ID.test(job.job_id)", remember)
        self.assertNotRegex(remember, r"summary|message|input|reason")

    def test_a_late_reply_never_clears_another_cases_decision_card(self):
        # Found by the automated review of PR #63: a reply for case A cleared the card the person had started
        # filling on case B meanwhile. Only the request's own card may be cleared or redrawn.
        submit = SCRIPT[SCRIPT.index("async function submitDecision"):]
        submit = submit[:submit.index("\n  }\n")]
        marker = "const stillOpen = state.review === form;"
        self.assertIn(marker, submit)
        after_reply = submit[submit.index(marker):]  # before it, the card being checked is the one on screen
        touches = [line.strip() for line in after_reply.splitlines()
                   if "state.review = null" in line or "renderThread(true)" in line]
        self.assertTrue(touches)
        for line in touches:
            with self.subTest(line=line):
                self.assertIn("if (stillOpen)", line)

    def test_every_review_reason_has_thai_words(self):
        # Attention signals (ADR-032) added four reasons; a reason without Thai words would show its code.
        from app.domains.case_triage.contracts import REVIEW_REASONS
        reasons = js_table("REASON")
        self.assertEqual(set(reasons), set(REVIEW_REASONS))
        self.assertTrue(all(re.search(r"[฀-๿]", word) for word in reasons.values()))
        self.assertIn('stepId === "screen"', SCRIPT)

    def test_every_handoff_code_has_thai_words_and_links_open_only_job_ids(self):
        # Skill handoffs (ADR-030): the page names every origin, state and refusal code of app/exchange in Thai, and
        # its only way to another job is a button whose id passes JOB_ID, never an address.
        from app.exchange import REASONS, Vocabulary
        from app.persistence import HANDOFF_STATES
        self.assertEqual(set(js_table("ORIGIN_TH")), set(Vocabulary.load().origins))
        self.assertEqual(set(js_table("HANDOFF_STATE")), set(HANDOFF_STATES))
        self.assertEqual(set(js_table("HANDOFF_REASON")), set(REASONS))
        for table in ("ORIGIN_TH", "HANDOFF_STATE", "HANDOFF_REASON"):
            with self.subTest(table=table):
                self.assertTrue(all(re.search(r"[฀-๿]", word) for word in js_table(table).values()))
        self.assertIn('action === "open-job" && JOB_ID.test(', SCRIPT)
        opener = SCRIPT[SCRIPT.index("function openJobButton"):]
        self.assertIn("JOB_ID.test(", opener[:opener.index("\n  }\n")])
        # A route-only workflow is shown, never offered: the composer sends only the default workflow or the study one.
        self.assertIn("info.route_only", SCRIPT)
        self.assertNotIn("case_triage.v2.apply", SCRIPT[SCRIPT.index("function modeWorkflow"):][:200])

    def test_the_page_never_says_who_decides(self):
        submit = SCRIPT[SCRIPT.index("async function submitDecision"):]
        submit = submit[:submit.index("\n  }\n")]
        body = re.search(r"const body = (\{[^}]*\})", submit).group(1)
        fields = {part.split(":")[0].strip() for part in body.strip("{} ").split(",")}
        self.assertEqual(fields, {"decision", "reason", "expected_version"})
        self.assertNotRegex(submit, r"reviewer|token_id|role")
        self.assertIn('id="inbox"', PAGE)
        self.assertIn('id="lost-banner"', PAGE)
