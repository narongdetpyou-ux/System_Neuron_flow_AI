"""The frame (roadmap 4.1, ADR-038): what the system can do, in plain words, as versioned data.

1. The committed frame loads, its tag is the complete SHA-256 of the file's bytes, it fits the committed catalog, and
   every admissible workflow type is a task or is named-only on purpose (``frame.NAMED_ONLY``).
2. Every rule of the file is enforced, with each problem listed: shape, words in both languages, ids, examples, fields.
3. The frame is held to what the workflows really do: its fields are their input fields, its limits are the limits
   their own checks apply (probed), its examples pass those checks, and a person decides exactly the tasks the frame
   says a person decides (one real job per task through the Runner, with the mock AI).
4. Its examples are not exam items: none equals a text of an evaluation or robustness set, and the two paraphrases
   that Phase 4's gate uses are not examples. A failure names the item's id, never its text.
5. ``GET /v1/frame``: every role reads it, it needs a credential, it only reads, it holds no path, param or agent, it
   shows only the tasks this process runs, and a frame that does not fit the catalog stops the API at start.
"""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from app.api.routes import ApiApp, Request
from app.llm import LLMConfig
from app.persistence import QueueStore
from app.services.admission import admit
from app.services.frame import (FRAME_FILE, GIVEN_BY, NAMED_ONLY, PERSON, REVIEWS, SYSTEM, FrameError, load_frame,
                                normalized)
from app.services.runner import Runner
from app.services.workflows import CATALOG, admissible
from tests.service_fixtures import KEY, settings

ROOT = Path(__file__).resolve().parent.parent
COMMITTED = json.loads(FRAME_FILE.read_text(encoding="utf-8"))
# Phase 4's gate (ROADMAP 4.4) checks that these two paraphrases reach the same task; they must not be examples.
GATE_PARAPHRASES = ("เข้าระบบไม่ได้", "ล็อกอินไม่ผ่าน")
FINAL_STATE = {"person": "REVIEW_REQUIRED", "none": "COMPLETED"}


def write_frame(folder, data):
    path = Path(folder) / "frame_test.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def changed(mutate):
    """A copy of the committed frame's data with one change made by ``mutate(data)``."""
    data = copy.deepcopy(COMMITTED)
    mutate(data)
    return data


def task_input(task, value):
    """The input of a job of ``task``: the workflow's preview input with its one person field set to ``value``."""
    raw = dict(CATALOG[task.workflow_type].preview_input)
    (field,) = task.asked
    raw[field.name] = value
    return raw


def call(app, method, path, *, credential=KEY, body=None):
    headers = {"authorization": f"Bearer {credential}"} if credential else {}
    data = b""
    if body is not None:
        headers["content-type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    return app.handle(Request(method, path, {}, headers, data, "tester"))


class CommittedFrameTests(unittest.TestCase):
    def test_it_loads_and_its_tag_is_the_complete_sha256_of_the_file(self):
        frame = load_frame()
        digest = hashlib.sha256(FRAME_FILE.read_bytes()).hexdigest()
        self.assertEqual(frame.tag, f"frame-v1@sha256:{digest}")
        self.assertEqual(frame.version, "frame-v1")

    def test_one_more_byte_is_another_frame(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "frame_v1.json"
            path.write_bytes(FRAME_FILE.read_bytes() + b"\n")
            other = load_frame(path)
        self.assertEqual(other.version, load_frame().version)
        self.assertNotEqual(other.tag, load_frame().tag)

    def test_it_fits_the_catalog_with_every_task(self):
        frame = load_frame()
        self.assertEqual([task.id for task in frame.fit(CATALOG)], ["case_triage", "study_guide"])
        self.assertEqual({task.workflow_type for task in frame.tasks}, {"case_triage.v2", "study_guide.v1"})

    def test_every_admissible_type_is_a_task_or_named_only_on_purpose(self):
        # A new workflow type in the catalog fails here until it is a task of the frame or named-only with a reason.
        tasks = {task.workflow_type for task in load_frame().tasks}
        self.assertEqual(set(admissible(CATALOG)), tasks | set(NAMED_ONLY))
        self.assertFalse(tasks & set(NAMED_ONLY))
        for name, reason in NAMED_ONLY.items():
            with self.subTest(name=name):
                self.assertFalse(CATALOG[name].route_only)  # a route-only type is never offered at all
                self.assertTrue(reason.strip())
        self.assertFalse({name for name, workflow in CATALOG.items() if workflow.route_only} & tasks)

    def test_every_field_a_person_gives_has_one_question_and_no_other_field_has_one(self):
        for task in load_frame().tasks:
            with self.subTest(task=task.id):
                self.assertGreaterEqual(len(task.asked), 1)
                for field in task.fields:
                    self.assertIn(field.given_by, GIVEN_BY)
                    if field.given_by == PERSON:
                        self.assertTrue(field.question.th and field.question.en)
                        self.assertLessEqual(field.min_chars, field.max_chars)
                    else:
                        self.assertEqual(field.given_by, SYSTEM)
                        self.assertIsNone(field.question)
                self.assertIn(task.review, REVIEWS)


class FileRuleTests(unittest.TestCase):
    """Each change breaks one rule of the file on its own; the error names it."""

    CASES = [
        ("an unknown key at the top", lambda d: d.update(extra=1), "the file must have exactly the keys"),
        ("a version that is not frame-vN", lambda d: d.update(version="frame-1"), "version must look like frame-v1"),
        ("a task without review", lambda d: d["tasks"][0].pop("review"), "must have exactly the keys"),
        ("Thai text without Thai", lambda d: d["tasks"][0]["name"].update(th="Sort cases"),
         "the Thai text has no Thai in it"),
        ("English text with Thai", lambda d: d["tasks"][0]["description"].update(en="Sorts a case ทดสอบ"),
         "the English text contains Thai"),
        ("a control character", lambda d: d["tasks"][1]["name"].update(en="Suggest\twhere to learn"),
         "contains a control character"),
        ("spaces around a text", lambda d: d["out_of_scope"].update(en=" Outside "), "has spaces at the start"),
        ("a task id used twice", lambda d: d["tasks"][1].update(id="case_triage"), "the id is used twice"),
        ("the reserved id", lambda d: d["tasks"][0].update(id="out_of_scope"), "is reserved"),
        ("a malformed id", lambda d: d["tasks"][0].update(id="Case Triage"), "id must match"),
        ("one workflow type for two tasks", lambda d: d["tasks"][1].update(workflow_type="case_triage.v2"),
         "one task per workflow type"),
        ("one example under two tasks",
         lambda d: d["tasks"][1]["examples"]["en"].__setitem__(0, d["tasks"][0]["examples"]["en"][0]),
         "a phrase points at one task"),
        ("an example repeated in its task",
         lambda d: d["tasks"][0]["examples"]["th"].__setitem__(1, d["tasks"][0]["examples"]["th"][0]),
         "examples.th[1]: repeated"),
        ("an example repeated in other letter case",
         lambda d: d["tasks"][0]["examples"]["en"].__setitem__(1, d["tasks"][0]["examples"]["en"][0].upper()),
         "examples.en[1]: repeated"),
        ("too few examples", lambda d: d["tasks"][0]["examples"].update(en=["Only one example here"]),
         "needs 2-8 phrases"),
        ("a review nobody knows", lambda d: d["tasks"][0].update(review="ai"), "review: must be one of person, none"),
        ("a field given by the AI", lambda d: d["tasks"][0]["fields"][0].update(given_by="ai"),
         "given_by must be one of person, system"),
        ("a person's field without a question", lambda d: d["tasks"][0]["fields"][0].pop("question"),
         "a field given by person has exactly the keys"),
        ("a system field with a question",
         lambda d: d["tasks"][0]["fields"][1].update(question={"th": "รหัสเคสคืออะไร", "en": "What is the id?"}),
         "a field given by system has exactly the keys"),
        ("min above max", lambda d: d["tasks"][0]["fields"][0].update(min_chars=600),
         "1 <= min_chars <= max_chars"),
        ("a limit that is not a whole number", lambda d: d["tasks"][1]["fields"][0].update(max_chars="500"),
         "1 <= min_chars <= max_chars"),
        ("a field listed twice", lambda d: d["tasks"][0]["fields"][1].update(name="summary"),
         "the field is listed twice"),
        ("nothing a person gives", lambda d: d["tasks"][0].update(fields=[d["tasks"][0]["fields"][1]]),
         "at least one field must be given by a person"),
        ("no task at all", lambda d: d.update(tasks=[]), "tasks must be a list of 1-20 entries"),
    ]

    def test_every_rule_refuses_its_case(self):
        with tempfile.TemporaryDirectory() as folder:
            for label, mutate, expected in self.CASES:
                with self.subTest(label):
                    with self.assertRaises(FrameError) as caught:
                        load_frame(write_frame(folder, changed(mutate)))
                    self.assertTrue(any(expected in problem for problem in caught.exception.problems),
                                    caught.exception.problems)

    def test_every_problem_is_listed_at_once(self):
        def two_problems(data):
            data["tasks"][0]["name"]["th"] = "Sort cases"
            data["tasks"][1]["review"] = "ai"

        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FrameError) as caught:
                load_frame(write_frame(folder, changed(two_problems)))
        self.assertEqual(len(caught.exception.problems), 2, caught.exception.problems)

    def test_a_missing_file_broken_json_and_a_repeated_key_are_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FrameError) as missing:
                load_frame(Path(folder) / "nothing.json")
            broken = Path(folder) / "broken.json"
            broken.write_bytes(b'{"version": ')
            with self.assertRaises(FrameError) as invalid:
                load_frame(broken)
            repeated = Path(folder) / "repeated.json"
            repeated.write_bytes(FRAME_FILE.read_bytes().replace(b'"version": "frame-v1",',
                                                                 b'"version": "frame-v1", "version": "frame-v2",', 1))
            with self.assertRaises(FrameError) as twice:
                load_frame(repeated)
        self.assertIn("file not found", missing.exception.problems[0])
        self.assertIn("not valid JSON", invalid.exception.problems[0])
        self.assertIn("not valid JSON", twice.exception.problems[0])


class CatalogFitTests(unittest.TestCase):
    """The frame against what the workflows really accept."""

    def fit_problems(self, mutate, catalog=CATALOG):
        with tempfile.TemporaryDirectory() as folder:
            frame = load_frame(write_frame(folder, changed(mutate)))
        with self.assertRaises(FrameError) as caught:
            frame.fit(catalog)
        return caught.exception.problems

    def test_a_route_only_type_is_never_a_task(self):
        problems = self.fit_problems(lambda d: d["tasks"][0].update(workflow_type="case_triage.v2.apply"))
        self.assertTrue(any("started only by a skill-handoff route" in problem for problem in problems), problems)

    def test_the_fields_are_exactly_the_input_fields(self):
        problems = self.fit_problems(lambda d: d["tasks"][1]["fields"][0].update(name="question"))
        self.assertIn("task study_guide: the fields must be exactly the input fields of study_guide.v1: message",
                      problems)

    def test_the_limits_are_the_ones_the_input_check_applies(self):
        for field, value, expected in (("max_chars", 499, "accepts 500 characters, but the frame says 8-499"),
                                       ("max_chars", 501, "refuses 501 characters, but the frame says 8-501"),
                                       ("min_chars", 9, "accepts 8 characters, but the frame says 9-500"),
                                       ("min_chars", 7, "refuses 7 characters, but the frame says 7-500")):
            with self.subTest(field=field, value=value):
                problems = self.fit_problems(lambda d: d["tasks"][0]["fields"][0].update({field: value}))
                self.assertTrue(any(expected in problem for problem in problems), problems)

    def test_every_example_passes_its_input_check(self):
        problems = self.fit_problems(lambda d: d["tasks"][0]["examples"]["en"].__setitem__(0, "Short"))
        self.assertIn("task case_triage.examples.en[0]: does not pass the input check of case_triage.v2 as its summary",
                      problems)

    def test_a_catalog_runs_only_its_own_tasks(self):
        only_cases = {"case_triage.v2": CATALOG["case_triage.v2"]}
        self.assertEqual([task.id for task in load_frame().fit(only_cases)], ["case_triage"])
        self.assertEqual(load_frame().fit({}), ())


class WhoDecidesTests(unittest.TestCase):
    def test_a_person_decides_exactly_the_tasks_the_frame_says(self):
        # One real job per task, its first Thai example as the input, run by the Runner with the mock AI.
        frame = load_frame()
        with tempfile.TemporaryDirectory() as folder:
            config = settings(Path(folder))
            store = QueueStore(config.queue_db)
            store.migrate()
            jobs = {}
            for number, task in enumerate(frame.tasks, 1):
                body = {"workflow_type": task.workflow_type, "idempotency_key": f"frame-review-{number:04d}",
                        "input": task_input(task, task.examples_th[0])}
                jobs[task.id] = admit(store, body, max_queued=10)[0]["job_id"]
            Runner(config, store=store, llm_config=LLMConfig()).drain()
            for task in frame.tasks:
                with self.subTest(task=task.id):
                    self.assertEqual(store.get(jobs[task.id])["status"], FINAL_STATE[task.review])


class ExamItemTests(unittest.TestCase):
    @staticmethod
    def exam_texts():
        """``{normalized text: item id}`` of every evaluation and robustness item."""
        texts = {}
        for path in sorted((ROOT / "app" / "eval" / "golden").glob("*.json")):
            for case in json.loads(path.read_text(encoding="utf-8"))["cases"]:
                text = case.get("summary") or case.get("message")
                if isinstance(text, str):
                    texts[normalized(text)] = f"{path.name}:{case['case_id']}"
        robustness = json.loads((ROOT / "tests" / "robustness" / "synthetic_v1.json").read_text(encoding="utf-8"))
        for item in robustness["items"]:
            for value in item["input"].values():
                if isinstance(value, str):
                    texts[normalized(value)] = f"synthetic_v1.json:{item['id']}"
        return texts

    def test_no_example_is_an_exam_item(self):
        texts = self.exam_texts()
        self.assertGreater(len(texts), 300)
        clashes = []
        for task in load_frame().tasks:
            for language, examples in (("th", task.examples_th), ("en", task.examples_en)):
                for index, example in enumerate(examples):
                    if normalized(example) in texts:  # report ids only: an exam text is never printed
                        clashes.append(f"task {task.id} examples.{language}[{index}] = {texts[normalized(example)]}")
        self.assertEqual(clashes, [])

    def test_the_paraphrases_of_phase_4s_gate_are_not_examples(self):
        for task in load_frame().tasks:
            for example in task.examples_th + task.examples_en:
                for phrase in GATE_PARAPHRASES:
                    self.assertNotIn(phrase, example)


class FrameApiTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.settings = settings(Path(self._temp.name))
        self.store = QueueStore(self.settings.queue_db)
        self.store.migrate()
        self.app = ApiApp(self.settings, self.store)

    def tearDown(self):
        self._temp.cleanup()

    def test_every_role_reads_the_same_frame(self):
        expected = load_frame().view(CATALOG)
        response = call(self.app, "GET", "/v1/frame")
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.body), expected)
        for role in ("reviewer", "submitter"):
            with self.subTest(role=role):
                issued = call(self.app, "POST", "/v1/tokens", body={"display_name": f"frame {role}", "role": role})
                token = json.loads(issued.body)["token"]
                reply = call(self.app, "GET", "/v1/frame", credential=token)
                self.assertEqual((reply.status, json.loads(reply.body)), (200, expected))

    def test_it_needs_a_credential_and_only_reads(self):
        self.assertEqual(call(self.app, "GET", "/v1/frame", credential=None).status, 401)
        self.assertEqual(call(self.app, "HEAD", "/v1/frame").status, 200)
        refused = call(self.app, "POST", "/v1/frame", body={})
        self.assertEqual(refused.status, 405)
        self.assertIn(("Allow", "GET, HEAD"), refused.headers)

    def test_it_holds_no_path_param_or_agent(self):
        response = call(self.app, "GET", "/v1/frame")
        view, text = json.loads(response.body), response.body.decode("utf-8")
        self.assertEqual(set(view), {"frame_version", "languages", "out_of_scope", "tasks"})
        self.assertRegex(view["frame_version"], r"^frame-v1@sha256:[0-9a-f]{64}$")
        for task in view["tasks"]:
            self.assertEqual(set(task), {"id", "workflow_type", "name", "description", "review", "examples",
                                         "fields"})

        def keys(value):
            if isinstance(value, dict):
                return set(value) | set().union(*(keys(item) for item in value.values()))
            if isinstance(value, list):
                return set().union(set(), *(keys(item) for item in value))
            return set()

        self.assertFalse(keys(view) & {"agent", "agents", "params", "steps", "spec", "path", "file", "callback"})
        self.assertNotIn(str(ROOT), text)
        self.assertNotIn("frame_v1.json", text)

    def test_a_catalog_shows_only_the_tasks_it_runs(self):
        # A process that runs the triage only: the frame offers its task alone (the exchange needs both triage types).
        triage = {name: CATALOG[name] for name in ("case_triage.v2", "case_triage.v2.apply")}
        app = ApiApp(self.settings, self.store, catalog=triage)
        view = json.loads(call(app, "GET", "/v1/frame").body)
        self.assertEqual([task["id"] for task in view["tasks"]], ["case_triage"])

    def test_a_frame_that_does_not_fit_stops_the_api_at_start(self):
        with tempfile.TemporaryDirectory() as folder:
            frame = load_frame(write_frame(folder, changed(
                lambda d: d["tasks"][0]["fields"][0].update(max_chars=499))))
        with self.assertRaises(FrameError):
            ApiApp(self.settings, self.store, frame=frame)


if __name__ == "__main__":
    unittest.main()
