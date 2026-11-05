"""The study guide's topic catalog and verified resource library (roadmap 3.1).

Two versioned JSON files in ``catalog/`` are the whole frame of the study guide:

* ``topics_<version>.json``: what the guide can help with. Each topic has a Thai and an English name and
  summary, example phrases and metaphors in both languages, prerequisite topics and a level.
* ``resources_<version>.json``: the only links the guide may ever show. Each resource says what it is for,
  its level, language and cost, which topics it covers, which parts to focus on, and the date a person last
  checked that the page is what the entry says.

The study guide's AI steps (roadmap 3.2) will only name ids from these files, and code inserts the URLs, so
a made-up link cannot reach a person. ``load_library`` checks both files strictly and reports every problem
at once. One SHA-256 covers both files (canonical JSON, like a prompt file's hash); it becomes part of the
agent version, so changing one character in either file is a new version and an old job refuses to re-run.
"""

from dataclasses import dataclass
import datetime as dt
from pathlib import Path
import re
from urllib.parse import urlsplit

from neuron_flow.model import SpecError, decode, fingerprint

CATALOG_DIR = Path(__file__).with_name("catalog")

OUT_OF_SCOPE = "out_of_scope"  # reserved: what topic detection answers when no topic fits
LEVELS = ("beginner", "intermediate", "advanced")
LEVEL_LABELS_TH = {"beginner": "เริ่มต้น", "intermediate": "กลาง", "advanced": "ลึก"}
LANGUAGES = ("th", "en")
KINDS = ("course", "roadmap", "article", "documentation", "paper", "dataset", "standard", "guidelines")
ACCESS = ("free", "paid")

TOPIC_KEYS = ("id", "name", "summary", "examples", "prerequisites", "level")
RESOURCE_KEYS = ("id", "url", "title", "by", "kind", "level", "language", "access", "topics", "purpose",
                 "focus", "verified_at")
MIN_EXAMPLES, MAX_EXAMPLES = 2, 10
MAX_TOPICS, MAX_RESOURCES = 100, 500
MAX_NAME, MAX_SENTENCE, MAX_EXAMPLE, MAX_TITLE, MAX_URL = 120, 300, 200, 200, 300

_VERSION = re.compile(r"^v[1-9][0-9]{0,2}$")
_ID = re.compile(r"^[a-z][a-z0-9_]{1,47}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_THAI = re.compile(r"[฀-๿]")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_URL_CHARS = re.compile(r"^[\x21-\x7e]+$")  # printable ASCII, no spaces: non-ASCII must be percent-encoded


class LibraryError(ValueError):
    """The library files are missing or break a rule. ``problems`` lists every problem found."""

    def __init__(self, problems):
        self.problems = tuple(problems)
        super().__init__("The study library is invalid:\n" + "\n".join(f"- {p}" for p in self.problems))


@dataclass(frozen=True)
class Text:
    th: str
    en: str


@dataclass(frozen=True)
class Topic:
    id: str
    name: Text
    summary: Text
    examples_th: tuple
    examples_en: tuple
    prerequisites: tuple
    level: str


@dataclass(frozen=True)
class Resource:
    id: str
    url: str
    title: str
    by: str
    kind: str
    level: str
    language: str
    access: str
    topics: tuple
    purpose: Text
    focus: Text
    verified_at: str


@dataclass(frozen=True)
class Library:
    version: str
    sha256: str
    topics: tuple
    resources: tuple

    @property
    def tag(self):
        """What goes into an agent version, e.g. ``v1@sha256:…``."""
        return f"{self.version}@sha256:{self.sha256}"

    def topic(self, topic_id):
        for topic in self.topics:
            if topic.id == topic_id:
                return topic
        raise KeyError(topic_id)

    def resources_for(self, topic_id):
        """The resources that cover a topic, in library order."""
        self.topic(topic_id)
        return tuple(resource for resource in self.resources if topic_id in resource.topics)


def load_library(version="v1", directory=None, *, today=None):
    """Read, check and hash ``topics_<version>.json`` and ``resources_<version>.json``."""
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise LibraryError([f"invalid library version {version!r} (expected v1, v2, …)"])
    folder = Path(directory) if directory is not None else CATALOG_DIR
    documents, problems = {}, []
    for part in ("topics", "resources"):
        name = f"{part}_{version}.json"
        try:
            documents[part] = decode((folder / name).read_bytes())
        except OSError:
            problems.append(f"{name}: file not found")
        except (SpecError, ValueError) as exc:
            problems.append(f"{name}: not valid JSON ({exc})")
    if problems:
        raise LibraryError(problems)
    problems = check_documents(documents["topics"], documents["resources"], version, today=today)
    if problems:
        raise LibraryError(problems)
    return Library(version, fingerprint({"topics": documents["topics"], "resources": documents["resources"]}),
                   tuple(_topic(item) for item in documents["topics"]["topics"]),
                   tuple(_resource(item) for item in documents["resources"]["resources"]))


def check_documents(topics_doc, resources_doc, version="v1", *, today=None):
    """Every rule both files must meet. Returns a list of problems; empty means the library is valid."""
    problems = []
    topics = _document(problems, topics_doc, f"topics_{version}", "topics", MAX_TOPICS)
    resources = _document(problems, resources_doc, f"resources_{version}", "resources", MAX_RESOURCES)
    topic_ids = _unique_ids(problems, topics, "topic")
    resource_ids = _unique_ids(problems, resources, "resource")
    for clash in sorted(topic_ids & resource_ids):
        problems.append(f"resource {clash}: the id is also a topic id; keep the two apart")

    examples_seen = {}
    for number, item in enumerate(topics, 1):
        _check_topic(problems, item, number, topic_ids, examples_seen)
    _check_prerequisites(problems, topics, topic_ids)

    urls_seen, covered = {}, set()
    today = today or dt.datetime.now(dt.timezone.utc).date()
    for number, item in enumerate(resources, 1):
        _check_resource(problems, item, number, topic_ids, urls_seen, today)
        if isinstance(item, dict) and isinstance(item.get("topics"), list):
            covered.update(t for t in item["topics"] if isinstance(t, str))
    for topic_id in sorted(topic_ids - covered):
        problems.append(f"topic {topic_id}: no resource covers it")
    return problems


# --- the checks ---------------------------------------------------------------------------------------

def _document(problems, document, expected_id, list_key, limit):
    keys = {"id", "description", list_key}
    if not isinstance(document, dict) or set(document) != keys:
        problems.append(f"{expected_id}: the file must have exactly the keys {sorted(keys)}")
        return []
    if document["id"] != expected_id:
        problems.append(f"{expected_id}: id must be {expected_id!r}, not {document['id']!r}")
    _string(problems, f"{expected_id}.description", document["description"], MAX_SENTENCE * 2)
    items = document[list_key]
    if not isinstance(items, list) or not items or len(items) > limit:
        problems.append(f"{expected_id}: {list_key} must be a list of 1-{limit} entries")
        return []
    return items


def _unique_ids(problems, items, kind):
    ids = set()
    for number, item in enumerate(items, 1):
        identifier = item.get("id") if isinstance(item, dict) else None
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
            problems.append(f"{kind} #{number}: id must match {_ID.pattern}")
        elif identifier == OUT_OF_SCOPE:
            problems.append(f"{kind} #{number}: {OUT_OF_SCOPE!r} is reserved for 'no topic fits'")
        elif identifier in ids:
            problems.append(f"{kind} {identifier}: the id is used twice")
        else:
            ids.add(identifier)
    return ids


def _label(kind, item, number=None):
    identifier = item.get("id") if isinstance(item, dict) else None
    return f"{kind} {identifier}" if isinstance(identifier, str) else f"{kind} #{number}"


def _check_topic(problems, item, number, topic_ids, examples_seen):
    where = _label("topic", item, number)
    if not isinstance(item, dict) or set(item) != set(TOPIC_KEYS):
        problems.append(f"{where}: must have exactly the keys {list(TOPIC_KEYS)}")
        return
    _text(problems, f"{where}.name", item["name"], MAX_NAME)
    _text(problems, f"{where}.summary", item["summary"], MAX_SENTENCE)
    _choice(problems, f"{where}.level", item["level"], LEVELS)
    examples = item["examples"]
    if not isinstance(examples, dict) or set(examples) != set(LANGUAGES):
        problems.append(f"{where}.examples: must have exactly the keys th and en")
    else:
        here = set()
        for language in LANGUAGES:
            phrases = examples[language]
            if (not isinstance(phrases, list) or not MIN_EXAMPLES <= len(phrases) <= MAX_EXAMPLES):
                problems.append(f"{where}.examples.{language}: needs {MIN_EXAMPLES}-{MAX_EXAMPLES} phrases")
                continue
            for index, phrase in enumerate(phrases):
                label = f"{where}.examples.{language}[{index}]"
                if not _string(problems, label, phrase, MAX_EXAMPLE, language):
                    continue
                key = " ".join(phrase.casefold().split())
                if key in here:
                    problems.append(f"{label}: repeated")
                elif key in examples_seen:
                    problems.append(f"{label}: the same phrase is an example of topic {examples_seen[key]}; "
                                    "a phrase must point at one topic")
                else:
                    here.add(key)
                    examples_seen[key] = where.removeprefix("topic ")
    prerequisites = item["prerequisites"]
    if not isinstance(prerequisites, list) or len(set(map(str, prerequisites))) != len(prerequisites):
        problems.append(f"{where}.prerequisites: must be a list without repeats")
        return
    for prerequisite in prerequisites:
        if prerequisite == item["id"]:
            problems.append(f"{where}.prerequisites: a topic cannot need itself")
        elif prerequisite not in topic_ids:
            problems.append(f"{where}.prerequisites: unknown topic {prerequisite!r}")


def _check_prerequisites(problems, topics, topic_ids):
    """No cycles, and a prerequisite is never harder than the topic that needs it (so a study path can go
    from prerequisites to the topic and from easy to hard at the same time)."""
    graph, level = {}, {}
    for item in topics:
        if (isinstance(item, dict) and item.get("id") in topic_ids
                and isinstance(item.get("prerequisites"), list)):
            graph[item["id"]] = [p for p in item["prerequisites"] if p in topic_ids and p != item["id"]]
            level[item["id"]] = item.get("level")
    for topic_id, needs in graph.items():
        for prerequisite in needs:
            if level.get(topic_id) in LEVELS and level.get(prerequisite) in LEVELS:
                if LEVELS.index(level[prerequisite]) > LEVELS.index(level[topic_id]):
                    problems.append(f"topic {topic_id}.prerequisites: {prerequisite} is harder "
                                    f"({level[prerequisite]}) than the topic itself ({level[topic_id]})")
    state = {}  # 1 = on the current path, 2 = done

    def visit(node, path):
        state[node] = 1
        for nxt in graph.get(node, ()):
            if state.get(nxt) == 1:
                cycle = path[path.index(nxt):] + [nxt]
                problems.append("topic prerequisites form a cycle: " + " -> ".join(cycle))
            elif nxt not in state:
                visit(nxt, path + [nxt])
        state[node] = 2

    for node in graph:
        if node not in state:
            visit(node, [node])


def _check_resource(problems, item, number, topic_ids, urls_seen, today):
    where = _label("resource", item, number)
    if not isinstance(item, dict) or set(item) != set(RESOURCE_KEYS):
        problems.append(f"{where}: must have exactly the keys {list(RESOURCE_KEYS)}")
        return
    _url(problems, f"{where}.url", item["url"])
    if isinstance(item["url"], str):
        owner = urls_seen.setdefault(item["url"], item["id"])
        if owner != item["id"]:
            problems.append(f"{where}.url: the same address is already resource {owner}")
    _string(problems, f"{where}.title", item["title"], MAX_TITLE)
    _string(problems, f"{where}.by", item["by"], MAX_TITLE)
    _choice(problems, f"{where}.kind", item["kind"], KINDS)
    _choice(problems, f"{where}.level", item["level"], LEVELS)
    _choice(problems, f"{where}.language", item["language"], LANGUAGES)
    _choice(problems, f"{where}.access", item["access"], ACCESS)
    _text(problems, f"{where}.purpose", item["purpose"], MAX_SENTENCE)
    _text(problems, f"{where}.focus", item["focus"], MAX_SENTENCE)
    covers = item["topics"]
    if (not isinstance(covers, list) or not covers or len(set(map(str, covers))) != len(covers)):
        problems.append(f"{where}.topics: must be a non-empty list without repeats")
    else:
        for topic_id in covers:
            if topic_id not in topic_ids:
                problems.append(f"{where}.topics: unknown topic {topic_id!r}")
    verified = item["verified_at"]
    try:
        if not isinstance(verified, str) or not _DATE.fullmatch(verified):
            raise ValueError
        day = dt.date.fromisoformat(verified)
    except ValueError:
        problems.append(f"{where}.verified_at: must be a date written YYYY-MM-DD")
    else:
        if day > today + dt.timedelta(days=1):  # one day of slack for time zones
            problems.append(f"{where}.verified_at: {verified} is in the future")


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


def _text(problems, where, value, limit):
    if not isinstance(value, dict) or set(value) != set(LANGUAGES):
        problems.append(f"{where}: must have exactly the keys th and en")
        return
    for language in LANGUAGES:
        _string(problems, f"{where}.{language}", value[language], limit, language)


def _choice(problems, where, value, choices):
    if value not in choices:
        problems.append(f"{where}: must be one of {', '.join(choices)}")


def _url(problems, where, value):
    if not isinstance(value, str) or not value or len(value) > MAX_URL or not _URL_CHARS.fullmatch(value):
        problems.append(f"{where}: must be an address of at most {MAX_URL} printable ASCII characters "
                        "without spaces")
        return
    try:
        parts = urlsplit(value)
        parts.port  # raises ValueError for a malformed port
    except ValueError:
        problems.append(f"{where}: not a valid address")
        return
    if parts.scheme != "https":
        problems.append(f"{where}: must start with https://")
    elif not parts.hostname or "." not in parts.hostname:
        problems.append(f"{where}: needs a full host name")
    elif parts.username is not None or parts.password is not None:
        problems.append(f"{where}: must not carry a user name or password")


# --- building the objects (only after every check passed) ---------------------------------------------

def _topic(item):
    return Topic(item["id"], Text(**item["name"]), Text(**item["summary"]), tuple(item["examples"]["th"]),
                 tuple(item["examples"]["en"]), tuple(item["prerequisites"]), item["level"])


def _resource(item):
    return Resource(item["id"], item["url"], item["title"], item["by"], item["kind"], item["level"],
                    item["language"], item["access"], tuple(item["topics"]), Text(**item["purpose"]),
                    Text(**item["focus"]), item["verified_at"])
