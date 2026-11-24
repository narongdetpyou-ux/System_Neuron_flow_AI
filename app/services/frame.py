"""The frame: what the system can do, in plain words, as versioned data (roadmap 4.1, ADR-038).

``frame_v1.json`` lists the *tasks* a person may ask for in everyday words. Each task is run by exactly one workflow
type of the catalog (``app/services/workflows.py``) and says, in Thai and English:

* its name and what it does;
* who decides: ``person`` (a person decides every job; it ends ``REVIEW_REQUIRED``) or ``none`` (informational, it
  decides nothing for anyone and ends ``COMPLETED``, ADR-018);
* example requests, to show how people may ask. They are not an evaluation set: the router's tests (roadmap 4.2) use
  other phrases, and ``tests/test_frame.py`` keeps the examples apart from every exam set;
* the input fields of the workflow type: a field a person gives (``given_by: person``), with its length limits and one
  simple question to ask when it is missing, or a field the application fills (``given_by: system``), such as a case id.

The frame is checked twice:

1. :func:`load_frame` checks the file on its own and reports every problem at once. Its tag carries the complete
   SHA-256 of the file's bytes (``frame-v1@sha256:…``), so changing one character is visibly a new frame; the router
   (roadmap 4.2) will carry this tag in its agent version, as the study guide carries its library's.
2. :meth:`Frame.fit` checks it against the catalog a process runs: a task's workflow type is never route-only (ADR-030),
   its fields are exactly the type's input fields, the stated limits are the ones its ``check_input`` applies (probed,
   not trusted), and every example passes that check. The API builds its view at start, so a frame that does not fit
   stops the service before any request, like a route table that does not fit (``app.exchange``).

An admissible workflow type is a task or is listed in :data:`NAMED_ONLY`; ``tests/test_frame.py`` fails when a new type
is neither. Outside requests still name a ``workflow_type``, never a task id (rule 7): the frame describes, it admits
nothing.
"""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Optional

from neuron_flow import SpecError
from neuron_flow.model import decode

FRAME_FILE = Path(__file__).with_name("frame_v1.json")
LANGUAGES = ("th", "en")
OUT_OF_SCOPE = "out_of_scope"  # reserved: what the router (roadmap 4.2) answers when no task fits
PERSON, SYSTEM = "person", "system"
GIVEN_BY = (PERSON, SYSTEM)
REVIEWS = ("person", "none")  # who decides a job of the task: a person, or nobody (informational, ADR-018)
# Admissible workflow types that are deliberately not tasks. Outside requests may still name them by their
# workflow_type; nothing offers them in plain words. A route-only type (ADR-030) is never a task and never listed here.
NAMED_ONLY = {
    "case_triage.v1": "the original rules-only demo; a request in plain words about a case gets case_triage.v2",
}

MIN_EXAMPLES, MAX_EXAMPLES = 2, 8
MAX_TASKS, MAX_FIELDS = 20, 10
MAX_NAME, MAX_SENTENCE, MAX_EXAMPLE, MAX_SHORT, MAX_DESCRIPTION = 80, 400, 200, 200, 800
MAX_CHARS_LIMIT = 10_000
PROBE = "ก"  # one Thai letter: visible, so every text contract counts it

_TOP_KEYS = {"version", "description", "out_of_scope", "tasks"}
_TASK_KEYS = {"id", "workflow_type", "name", "description", "review", "examples", "fields"}
_FIELD_KEYS = {PERSON: {"name", "given_by", "min_chars", "max_chars", "meaning", "question"},
               SYSTEM: {"name", "given_by", "meaning"}}
_VERSION = re.compile(r"^frame-v[1-9][0-9]{0,2}$")
_TASK_ID = re.compile(r"^[a-z][a-z0-9_]{1,47}$")
_FIELD_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_WORKFLOW = re.compile(r"^[a-z][a-z0-9_.]{1,79}$")
_THAI = re.compile(r"[฀-๿]")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class FrameError(ValueError):
    """The frame file is missing, breaks a rule, or does not fit the catalog. ``problems`` lists every problem."""

    def __init__(self, problems):
        self.problems = tuple(problems)
        super().__init__("The frame is invalid:\n" + "\n".join(f"- {problem}" for problem in self.problems))


@dataclass(frozen=True)
class Words:
    th: str
    en: str

    def view(self):
        return {"th": self.th, "en": self.en}


@dataclass(frozen=True)
class Field:
    name: str
    given_by: str                     # PERSON (asked when missing) or SYSTEM (the application fills it)
    meaning: Words
    question: Optional[Words] = None  # PERSON only: the one simple question to ask when the field is missing
    min_chars: Optional[int] = None   # PERSON only: counted the way the workflow's own check_input counts
    max_chars: Optional[int] = None

    def view(self):
        view = {"name": self.name, "given_by": self.given_by, "meaning": self.meaning.view()}
        if self.given_by == PERSON:
            view.update(min_chars=self.min_chars, max_chars=self.max_chars, question=self.question.view())
        return view


@dataclass(frozen=True)
class Task:
    id: str
    workflow_type: str
    name: Words
    description: Words
    review: str
    examples_th: tuple
    examples_en: tuple
    fields: tuple

    @property
    def asked(self):
        """The fields a person gives, in the file's order."""
        return tuple(field for field in self.fields if field.given_by == PERSON)

    def view(self):
        return {"id": self.id, "workflow_type": self.workflow_type, "name": self.name.view(),
                "description": self.description.view(), "review": self.review,
                "examples": {"th": list(self.examples_th), "en": list(self.examples_en)},
                "fields": [field.view() for field in self.fields]}


@dataclass(frozen=True)
class Frame:
    version: str
    tag: str           # <version>@sha256:<complete hex digest of the file's bytes>
    out_of_scope: Words
    tasks: tuple

    def task(self, task_id):
        for task in self.tasks:
            if task.id == task_id:
                return task
        raise KeyError(task_id)

    def fit(self, catalog):
        """The tasks this catalog runs, in the file's order; :class:`FrameError` when one of them does not fit.

        A task whose workflow type the catalog does not run is left out (a test catalog may leave types out); the
        committed frame is held to the committed catalog in ``tests/test_frame.py``."""
        problems, fitted = [], []
        for task in self.tasks:
            workflow = catalog.get(task.workflow_type)
            if workflow is None:
                continue
            where = f"task {task.id}"
            if workflow.route_only:
                problems.append(f"{where}: {task.workflow_type} is started only by a skill-handoff route (ADR-030), "
                                "so no request can ask for it")
                continue
            contract = sorted(workflow.preview_input)
            if sorted(field.name for field in task.fields) != contract:
                problems.append(f"{where}: the fields must be exactly the input fields of {task.workflow_type}: "
                                + ", ".join(contract))
                continue
            for field in task.asked:
                _probe(problems, where, workflow, field)
            if len(task.asked) == 1:
                (field,) = task.asked
                for language, examples in (("th", task.examples_th), ("en", task.examples_en)):
                    for index, example in enumerate(examples):
                        if not _passes(workflow, field.name, example):
                            problems.append(f"{where}.examples.{language}[{index}]: does not pass the input check of "
                                            f"{task.workflow_type} as its {field.name}")
            fitted.append(task)
        if problems:
            raise FrameError(problems)
        return tuple(fitted)

    def view(self, catalog):
        """What ``GET /v1/frame`` answers: the version, the opening of an out-of-scope answer and the tasks this
        catalog runs, in plain words. Nothing in it is a path, a param or an agent."""
        return {"frame_version": self.tag, "languages": list(LANGUAGES), "out_of_scope": self.out_of_scope.view(),
                "tasks": [task.view() for task in self.fit(catalog)]}


def load_frame(path=FRAME_FILE):
    """Read, check and tag a frame file. Raises :class:`FrameError` with every problem found."""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError:
        raise FrameError([f"{path.name}: file not found"]) from None
    try:
        data = decode(raw)
    except (SpecError, ValueError) as exc:  # decode raises SpecError for anything it cannot read (ADR-025)
        raise FrameError([f"{path.name}: not valid JSON ({exc})"]) from None
    problems = check_document(data)
    if problems:
        raise FrameError(problems)
    tasks = tuple(_task(item) for item in data["tasks"])
    return Frame(data["version"], f"{data['version']}@sha256:{hashlib.sha256(raw).hexdigest()}",
                 Words(**data["out_of_scope"]), tasks)


def check_document(data):
    """Every rule a frame file meets on its own. Returns a list of problems; empty means it is valid."""
    problems = []
    if not isinstance(data, dict) or set(data) != _TOP_KEYS:
        return [f"the file must have exactly the keys {sorted(_TOP_KEYS)}"]
    if not isinstance(data["version"], str) or not _VERSION.fullmatch(data["version"]):
        problems.append(f"version must look like frame-v1, not {data['version']!r}")
    _string(problems, "description", data["description"], MAX_DESCRIPTION)
    _words(problems, "out_of_scope", data["out_of_scope"], MAX_SENTENCE)
    tasks = data["tasks"]
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= MAX_TASKS:
        problems.append(f"tasks must be a list of 1-{MAX_TASKS} entries")
        return problems
    ids, types, examples_seen = set(), {}, {}
    for number, item in enumerate(tasks, 1):
        _check_task(problems, item, number, ids, types, examples_seen)
    return problems


# --- the checks ---------------------------------------------------------------------------------------

def _check_task(problems, item, number, ids, types, examples_seen):
    identifier = item.get("id") if isinstance(item, dict) else None
    where = f"task {identifier}" if isinstance(identifier, str) else f"task #{number}"
    if not isinstance(item, dict) or set(item) != _TASK_KEYS:
        problems.append(f"{where}: must have exactly the keys {sorted(_TASK_KEYS)}")
        return
    if not isinstance(identifier, str) or not _TASK_ID.fullmatch(identifier):
        problems.append(f"{where}: id must match {_TASK_ID.pattern}")
    elif identifier == OUT_OF_SCOPE:
        problems.append(f"{where}: {OUT_OF_SCOPE!r} is reserved for 'no task fits'")
    elif identifier in ids:
        problems.append(f"{where}: the id is used twice")
    else:
        ids.add(identifier)
    workflow_type = item["workflow_type"]
    if not isinstance(workflow_type, str) or not _WORKFLOW.fullmatch(workflow_type):
        problems.append(f"{where}.workflow_type: must be a workflow type name such as case_triage.v2")
    elif workflow_type in types:
        problems.append(f"{where}.workflow_type: {workflow_type} is already run by task {types[workflow_type]}; "
                        "one task per workflow type")
    else:
        types[workflow_type] = identifier
    _words(problems, f"{where}.name", item["name"], MAX_NAME)
    _words(problems, f"{where}.description", item["description"], MAX_SENTENCE)
    if item["review"] not in REVIEWS:
        problems.append(f"{where}.review: must be one of {', '.join(REVIEWS)}")
    _check_examples(problems, where, item["examples"], examples_seen)
    _check_fields(problems, where, item["fields"])


def _check_examples(problems, where, examples, examples_seen):
    if not isinstance(examples, dict) or set(examples) != set(LANGUAGES):
        problems.append(f"{where}.examples: must have exactly the keys th and en")
        return
    for language in LANGUAGES:
        phrases = examples[language]
        if not isinstance(phrases, list) or not MIN_EXAMPLES <= len(phrases) <= MAX_EXAMPLES:
            problems.append(f"{where}.examples.{language}: needs {MIN_EXAMPLES}-{MAX_EXAMPLES} phrases")
            continue
        for index, phrase in enumerate(phrases):
            label = f"{where}.examples.{language}[{index}]"
            if not _string(problems, label, phrase, MAX_EXAMPLE, language):
                continue
            key = normalized(phrase)
            if key in examples_seen:
                owner = examples_seen[key]
                problems.append(f"{label}: repeated" if owner == where
                                else f"{label}: the same phrase is an example of {owner}; a phrase points at one task")
            else:
                examples_seen[key] = where


def _check_fields(problems, where, fields):
    if not isinstance(fields, list) or not 1 <= len(fields) <= MAX_FIELDS:
        problems.append(f"{where}.fields: must be a list of 1-{MAX_FIELDS} fields")
        return
    names, asked = set(), 0
    for number, field in enumerate(fields, 1):
        name = field.get("name") if isinstance(field, dict) else None
        label = f"{where}.fields.{name}" if isinstance(name, str) else f"{where}.fields[{number}]"
        given_by = field.get("given_by") if isinstance(field, dict) else None
        if given_by not in GIVEN_BY:
            problems.append(f"{label}: given_by must be one of {', '.join(GIVEN_BY)}")
            continue
        if set(field) != _FIELD_KEYS[given_by]:
            problems.append(f"{label}: a field given by {given_by} has exactly the keys "
                            f"{sorted(_FIELD_KEYS[given_by])}")
            continue
        if not isinstance(name, str) or not _FIELD_NAME.fullmatch(name):
            problems.append(f"{label}: name must match {_FIELD_NAME.pattern}")
        elif name in names:
            problems.append(f"{label}: the field is listed twice")
        else:
            names.add(name)
        _words(problems, f"{label}.meaning", field["meaning"], MAX_SHORT)
        if given_by == PERSON:
            asked += 1
            _words(problems, f"{label}.question", field["question"], MAX_SHORT)
            low, high = field["min_chars"], field["max_chars"]
            if type(low) is not int or type(high) is not int or not 1 <= low <= high <= MAX_CHARS_LIMIT:
                problems.append(f"{label}: min_chars and max_chars must be whole numbers with "
                                f"1 <= min_chars <= max_chars <= {MAX_CHARS_LIMIT}")
    if not asked:
        problems.append(f"{where}.fields: at least one field must be given by a person, or there is nothing to ask")


def _string(problems, where, value, limit, language=None):
    if not isinstance(value, str) or not value.strip():
        problems.append(f"{where}: must be a non-empty string")
    elif value != value.strip():
        problems.append(f"{where}: has spaces at the start or the end")
    elif len(value) > limit:
        problems.append(f"{where}: longer than {limit} characters")
    elif _CONTROL.search(value):
        problems.append(f"{where}: contains a control character")
    elif language == "th" and not _THAI.search(value):
        problems.append(f"{where}: the Thai text has no Thai in it")
    elif language == "en" and _THAI.search(value):
        problems.append(f"{where}: the English text contains Thai")
    else:
        return True
    return False


def _words(problems, where, value, limit):
    if not isinstance(value, dict) or set(value) != set(LANGUAGES):
        problems.append(f"{where}: must have exactly the keys th and en")
        return
    for language in LANGUAGES:
        _string(problems, f"{where}.{language}", value[language], limit, language)


def normalized(text):
    """How two phrases are compared: case and runs of spaces do not count."""
    return " ".join(text.casefold().split())


def _passes(workflow, name, value):
    """Whether the workflow's own input check accepts ``value`` as ``name``, the other fields as in its preview."""
    raw = dict(workflow.preview_input)
    raw[name] = value
    try:
        workflow.check_input(raw)
    except SpecError:
        return False
    return True


def _probe(problems, where, workflow, field):
    """The stated limits are the input check's own: min and max characters pass, one fewer and one more do not."""
    for length, accepted in ((field.min_chars, True), (field.max_chars, True),
                             (field.min_chars - 1, False), (field.max_chars + 1, False)):
        if _passes(workflow, field.name, PROBE * length) != accepted:
            problems.append(f"{where}.fields.{field.name}: the input check of {workflow.name} "
                            f"{'refuses' if accepted else 'accepts'} {length} characters, but the frame says "
                            f"{field.min_chars}-{field.max_chars}")
            return


# --- building the objects (only after every check passed) ---------------------------------------------

def _field(item):
    if item["given_by"] == PERSON:
        return Field(item["name"], PERSON, Words(**item["meaning"]), Words(**item["question"]),
                     item["min_chars"], item["max_chars"])
    return Field(item["name"], SYSTEM, Words(**item["meaning"]))


def _task(item):
    return Task(item["id"], item["workflow_type"], Words(**item["name"]), Words(**item["description"]),
                item["review"], tuple(item["examples"]["th"]), tuple(item["examples"]["en"]),
                tuple(_field(field) for field in item["fields"]))
