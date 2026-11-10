"""Versioned deterministic triage rules for the shadow workflow (E2).

Matching normalizes a copy, never the stored case. English forms are explicit
whole words; Thai forms are substrings because Thai does not require spaces.
These are demonstration keywords, not a language model or a real triage policy.
The original rules-only workflow remains the ``keywords-v1`` demonstration.
"""

import hashlib
import json
import re
import unicodedata
from pathlib import Path

from .contracts import QUEUE_FOR

KEYWORDS_PATH = Path(__file__).with_name("keywords_v2.json")
PRECEDENCE = ("access", "upload", "billing")
_SCHEMA = "neuron-flow-triage-keywords-v2"
_REMOVED = frozenset("\u00ad\u200b\u200c\u200d\u2060\ufeff")


def normalize(text):
    """NFKC/lowercase, remove invisibles and Latin-only combining marks.

    Decomposing only for the mark pass keeps Thai vowels and tone marks intact.
    Hyphen alternatives are handled separately, identically for data and input.
    """
    text = unicodedata.normalize("NFKC", text).lower()
    chars = []
    latin_base = False
    for char in unicodedata.normalize("NFD", text):
        if char in _REMOVED:
            continue
        if unicodedata.category(char).startswith("M"):
            if not latin_base:
                chars.append(char)
            continue
        latin_base = unicodedata.name(char, "").startswith("LATIN ")
        chars.append(char)
    return unicodedata.normalize("NFC", "".join(chars))


def _forms(text):
    normalized = normalize(text)
    # Both forms are deliberate: log-in -> log in, up-load -> upload.
    spaced = "".join(" " if unicodedata.category(c) == "Pd" else c for c in normalized)
    joined = "".join(c for c in normalized if unicodedata.category(c) != "Pd")
    return tuple(dict.fromkeys(" ".join(form.split()) for form in (spaced, joined)))


def _load(path=None):
    raw = Path(path or KEYWORDS_PATH).read_bytes()
    data = json.loads(raw)
    if (not isinstance(data, dict) or set(data) != {"schema", "precedence", "keywords"}
            or data["schema"] != _SCHEMA or data["precedence"] != list(PRECEDENCE)
            or not isinstance(data["keywords"], dict) or set(data["keywords"]) != set(PRECEDENCE)):
        raise ValueError("Invalid triage keyword data or precedence")
    for groups in data["keywords"].values():
        if not isinstance(groups, dict) or set(groups) != {"en", "th"}:
            raise ValueError("Keyword groups must contain English and Thai lists")
        for language, words in groups.items():
            if (not isinstance(words, list) or not words
                    or any(not isinstance(word, str) or not word.strip() for word in words)
                    or len(set(words)) != len(words)):
                raise ValueError("Keywords must be distinct nonempty strings")
            if language == "en" and any(not word.isascii() for word in words):
                raise ValueError("English keyword forms must be ASCII")
    return data, "keywords-v2:" + hashlib.sha256(raw).hexdigest()


def rule_version():
    """Algorithm version plus the complete hash of the exact keyword bytes."""
    return _load()[1]


def classify_case(case):
    """Pure classification helper. No mutation, AI, side effect or decision."""
    data, version = _load()
    texts = _forms(case["summary"])
    category = "other"
    for candidate in PRECEDENCE:
        groups = data["keywords"][candidate]
        english = any(re.search(r"(?<!\w)" + re.escape(form) + r"(?!\w)", text)
                      for word in groups["en"] for form in _forms(word) for text in texts)
        thai = any(normalize(word) in text for word in groups["th"] for text in texts)
        if english or thai:
            category = candidate
            break
    return {"category": category, "queue": QUEUE_FOR[category], "rule_version": version}


def classify(message):
    output = classify_case(message["input"])
    if message["params"]["rule_version"] != output["rule_version"]:
        raise ValueError("Triage keyword data changed after this job was submitted")
    return output


def validate_classification(message, output):
    if output != classify(message):
        raise ValueError("Classification output violates the v2 deterministic contract")
