"""The study guide's topic catalog and verified resource library (roadmap 3.1)."""

import copy
import datetime as dt
import json
from pathlib import Path
import re
import tempfile
import unittest

from app.domains.study_guide import LEVEL_LABELS_TH, LEVELS, OUT_OF_SCOPE, LibraryError, load_library
from app.domains.study_guide.library import CATALOG_DIR, check_documents

ROOT = Path(__file__).resolve().parent.parent
TODAY = dt.date(2026, 11, 5)


def committed():
    topics = json.loads((CATALOG_DIR / "topics_v1.json").read_text(encoding="utf-8"))
    resources = json.loads((CATALOG_DIR / "resources_v1.json").read_text(encoding="utf-8"))
    return topics, resources


def write_library(folder, topics, resources, version="v1", indent=None):
    Path(folder, f"topics_{version}.json").write_text(json.dumps(topics, ensure_ascii=False, indent=indent),
                                                      encoding="utf-8")
    Path(folder, f"resources_{version}.json").write_text(
        json.dumps(resources, ensure_ascii=False, indent=indent), encoding="utf-8")


class CommittedLibraryTests(unittest.TestCase):
    def test_the_committed_library_loads_and_every_topic_has_a_resource(self):
        library = load_library()
        self.assertEqual(library.version, "v1")
        self.assertRegex(library.sha256, r"^[0-9a-f]{64}$")
        self.assertEqual(library.tag, f"v1@sha256:{library.sha256}")
        self.assertGreaterEqual(len(library.topics), 5)
        self.assertGreaterEqual(len(library.resources), 5)
        for topic in library.topics:
            self.assertTrue(library.resources_for(topic.id), topic.id)
            self.assertGreaterEqual(len(topic.examples_th), 2, topic.id)
            self.assertGreaterEqual(len(topic.examples_en), 2, topic.id)
        self.assertEqual(set(LEVEL_LABELS_TH), set(LEVELS))
        self.assertEqual(LEVEL_LABELS_TH["beginner"], "เริ่มต้น")
        self.assertNotIn(OUT_OF_SCOPE, [topic.id for topic in library.topics])

    def test_every_link_in_the_design_philosophy_seed_table_is_in_the_library(self):
        text = (ROOT / "docs" / "design_philosophy.md").read_text(encoding="utf-8")
        section = text.split("## แหล่งศึกษาเริ่มต้น", 1)[1].split("\n## ", 1)[0]
        seed = set(re.findall(r"https://[^\s)|]+", section))
        self.assertGreaterEqual(len(seed), 10)
        library_urls = {resource.url for resource in load_library().resources}
        self.assertEqual(sorted(seed - library_urls), [], "seed links missing from resources_v1.json")

    def test_the_owners_flagship_metaphor_is_kept_out_of_the_examples(self):
        # "บรรณารักษ์ที่รู้ใจ" is the owner's own example; it is saved for the evaluation set (roadmap 3.3), so
        # topic detection is not tested on a phrase it was shown.
        for topic in load_library().topics:
            for phrase in topic.examples_th + topic.examples_en:
                self.assertNotIn("บรรณารักษ์", phrase)
                self.assertNotIn("librarian", phrase.lower())

    def test_lookups(self):
        library = load_library()
        self.assertEqual(library.topic("ai_agents").level, "intermediate")
        ids = [resource.id for resource in library.resources_for("ai_agents")]
        self.assertEqual(ids, [r.id for r in library.resources if "ai_agents" in r.topics])
        with self.assertRaises(KeyError):
            library.topic("cooking")
        with self.assertRaises(KeyError):
            library.resources_for(OUT_OF_SCOPE)


class HashTests(unittest.TestCase):
    def test_one_hash_covers_both_files_and_ignores_formatting(self):
        topics, resources = committed()
        reference = load_library().sha256
        with tempfile.TemporaryDirectory() as folder:
            write_library(folder, topics, resources, indent=4)
            self.assertEqual(load_library(directory=folder).sha256, reference)

            changed = copy.deepcopy(resources)
            changed["resources"][0]["focus"]["en"] += "!"
            write_library(folder, topics, changed)
            self.assertNotEqual(load_library(directory=folder).sha256, reference)

            changed = copy.deepcopy(topics)
            changed["topics"][0]["summary"]["en"] += "!"
            write_library(folder, changed, resources)
            self.assertNotEqual(load_library(directory=folder).sha256, reference)


class LoadErrorTests(unittest.TestCase):
    def test_missing_files_bad_json_duplicate_keys_and_bad_versions_are_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(LibraryError) as caught:
                load_library(directory=folder)
            self.assertEqual(len(caught.exception.problems), 2)
            self.assertIn("topics_v1.json: file not found", caught.exception.problems)

            topics, resources = committed()
            write_library(folder, topics, resources)
            Path(folder, "resources_v1.json").write_text("{not json", encoding="utf-8")
            with self.assertRaisesRegex(LibraryError, "resources_v1.json: not valid JSON"):
                load_library(directory=folder)
            Path(folder, "resources_v1.json").write_text('{"id": "a", "id": "b"}', encoding="utf-8")
            with self.assertRaisesRegex(LibraryError, "Duplicate JSON field"):
                load_library(directory=folder)
        for version in ("1", "v0", "../v1", "v1/../x", None):
            with self.assertRaisesRegex(LibraryError, "invalid library version"):
                load_library(version)

    def test_a_file_from_another_version_is_refused(self):
        topics, resources = committed()
        with tempfile.TemporaryDirectory() as folder:
            write_library(folder, topics, resources, version="v2")
            with self.assertRaisesRegex(LibraryError, "id must be 'topics_v2'"):
                load_library("v2", directory=folder)


def _mutations():
    """(what breaks, how to break a copy of the committed files, the problem it must produce)."""
    def topic(docs, index=0):
        return docs[0]["topics"][index]

    def resource(docs, index=0):
        return docs[1]["resources"][index]

    def find_topic(docs, topic_id):
        return next(item for item in docs[0]["topics"] if item["id"] == topic_id)

    return [
        ("extra file key", lambda d: d[0].update(extra=1), "the file must have exactly the keys"),
        ("empty topic list", lambda d: d[0].update(topics=[]), "topics must be a list of 1-100 entries"),
        ("extra topic key", lambda d: topic(d).update(color="red"), "must have exactly the keys"),
        ("missing topic key", lambda d: topic(d).pop("level"), "must have exactly the keys"),
        ("bad topic id", lambda d: topic(d).update(id="AI Basics"), "id must match"),
        ("reserved topic id", lambda d: topic(d).update(id=OUT_OF_SCOPE), "is reserved"),
        ("duplicate topic id", lambda d: topic(d, 1).update(id=topic(d)["id"]), "the id is used twice"),
        ("unknown level", lambda d: topic(d).update(level="expert"), "level: must be one of"),
        ("Thai name without Thai", lambda d: topic(d)["name"].update(th="AI basics"), "has no Thai in it"),
        ("English text with Thai", lambda d: topic(d)["summary"].update(en="พื้นฐาน"), "contains Thai"),
        ("name missing a language", lambda d: topic(d)["name"].pop("en"), "exactly the keys th and en"),
        ("spaces around a name", lambda d: topic(d)["name"].update(en=" AI "), "spaces at the start"),
        ("control character", lambda d: topic(d)["summary"].update(en="a\nb"), "control character"),
        ("too few examples", lambda d: topic(d)["examples"].update(en=["one"]), "needs 2-10 phrases"),
        ("repeated example", lambda d: topic(d)["examples"]["en"].append(topic(d)["examples"]["en"][0].upper()),
         "repeated"),
        ("example of two topics",
         lambda d: topic(d, 1)["examples"]["en"].append(topic(d)["examples"]["en"][0]),
         "a phrase must point at one topic"),
        ("unknown prerequisite", lambda d: topic(d)["prerequisites"].append("cooking"), "unknown topic 'cooking'"),
        ("self prerequisite", lambda d: topic(d)["prerequisites"].append(topic(d)["id"]), "cannot need itself"),
        ("repeated prerequisite", lambda d: find_topic(d, "ai_agents").update(
            prerequisites=["prompt_writing", "prompt_writing"]), "without repeats"),
        ("prerequisite cycle", lambda d: find_topic(d, "ai_basics")["prerequisites"].append("prompt_writing"),
         "form a cycle: ai_basics -> prompt_writing -> ai_basics"),
        ("harder prerequisite", lambda d: find_topic(d, "plain_language")["prerequisites"].append("ai_agents"),
         "ai_agents is harder (intermediate) than the topic itself (beginner)"),
        ("topic without resources", lambda d: d[0]["topics"].append(
            dict(copy.deepcopy(find_topic(d, "system_design")), id="cooking",
                 examples={"th": ["ทำกับข้าว", "ต้มยำ"], "en": ["cooking", "soup"]})), "topic cooking: no resource"),
        ("extra resource key", lambda d: resource(d).update(rating=5), "must have exactly the keys"),
        ("duplicate resource id", lambda d: resource(d, 1).update(id=resource(d)["id"]), "the id is used twice"),
        ("resource id equal to a topic id", lambda d: resource(d).update(id="ai_basics"), "also a topic id"),
        ("http link", lambda d: resource(d).update(url="http://roadmap.sh/ai-engineer"), "must start with https://"),
        ("link with a password", lambda d: resource(d).update(url="https://user:pw@example.org/a"),
         "must not carry a user name or password"),
        ("link with a space", lambda d: resource(d).update(url="https://example.org/a b"), "without spaces"),
        ("non-ASCII link", lambda d: resource(d).update(url="https://example.org/ไทย"), "printable ASCII"),
        ("link without a host", lambda d: resource(d).update(url="https:///path"), "needs a full host name"),
        ("bad port", lambda d: resource(d).update(url="https://example.org:99999/"), "not a valid address"),
        ("javascript link", lambda d: resource(d).update(url="javascript:alert(1)"), "must start with https://"),
        ("same link twice", lambda d: resource(d, 1).update(url=resource(d)["url"]), "already resource"),
        ("unknown kind", lambda d: resource(d).update(kind="video"), "kind: must be one of"),
        ("unknown language", lambda d: resource(d).update(language="fr"), "language: must be one of"),
        ("unknown access", lambda d: resource(d).update(access="trial"), "access: must be one of"),
        ("empty title", lambda d: resource(d).update(title=""), "title: must be a non-empty string"),
        ("Thai purpose without Thai", lambda d: resource(d)["purpose"].update(th="A map"), "has no Thai in it"),
        ("resource without topics", lambda d: resource(d).update(topics=[]), "non-empty list without repeats"),
        ("resource with an unknown topic", lambda d: resource(d).update(topics=["cooking"]),
         "unknown topic 'cooking'"),
        ("badly written date", lambda d: resource(d).update(verified_at="5 Nov 2026"), "YYYY-MM-DD"),
        ("impossible date", lambda d: resource(d).update(verified_at="2026-02-30"), "YYYY-MM-DD"),
        ("date in the future", lambda d: resource(d).update(verified_at="2026-11-30"), "is in the future"),
    ]


class ValidationTests(unittest.TestCase):
    def test_the_committed_documents_have_no_problems(self):
        self.assertEqual(check_documents(*committed(), today=TODAY), [])

    def test_each_broken_rule_is_reported(self):
        for name, mutate, expected in _mutations():
            with self.subTest(name):
                docs = copy.deepcopy(committed())
                mutate(docs)
                problems = check_documents(*docs, today=TODAY)
                self.assertTrue(any(expected in p for p in problems), f"{name}: {problems}")

    def test_every_problem_is_reported_at_once_and_load_refuses_the_library(self):
        topics, resources = copy.deepcopy(committed())
        topics["topics"][0]["level"] = "expert"
        resources["resources"][0]["url"] = "http://example.org"
        with tempfile.TemporaryDirectory() as folder:
            write_library(folder, topics, resources)
            with self.assertRaises(LibraryError) as caught:
                load_library(directory=folder, today=TODAY)
        self.assertEqual(len(caught.exception.problems), 2, caught.exception.problems)
        self.assertIn("must be one of", str(caught.exception))

    def test_a_date_one_day_ahead_is_accepted_for_time_zones(self):
        topics, resources = copy.deepcopy(committed())
        resources["resources"][0]["verified_at"] = "2026-11-06"
        self.assertEqual(check_documents(topics, resources, today=TODAY), [])

    def test_non_dict_entries_do_not_crash_the_checks(self):
        topics, resources = copy.deepcopy(committed())
        topics["topics"].append("not a topic")
        resources["resources"].append(["not", "a", "resource"])
        problems = check_documents(topics, resources, today=TODAY)
        self.assertTrue(any(p.startswith("topic #12") for p in problems), problems)
        self.assertTrue(any(p.startswith("resource #18") for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
