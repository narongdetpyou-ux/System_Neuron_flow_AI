"""Attention signals for the shadow workflow: plain code that marks a case "a person should look at this first".

The limits run of 2026-11-11 (ADR-031, ADR-032) showed that nothing in the workflow
knew which cases a careful operator would want to see first: an account taken over, a legal or privacy
request, a person in distress or danger, or text that tries to steer the routing or the approval. The only
flag was "rules and AI disagree", which says nothing about any of those.

This step looks for versioned phrases of four kinds and reports the kinds it found, never the text. It runs
beside the rules and the AI and cannot change either one's category: a signal only raises the review priority
and adds a reason for the reviewer (rule 4: a person still decides every case). No AI is involved, so text
that tries to instruct a model has nothing here to instruct.

Matching reuses the rules' normalisation: English forms are whole words, Thai forms are substrings (Thai
needs no spaces), and ``markers`` are raw substrings for tag- or key-like text (``</case_text>``,
``category=``). These are demonstration phrases, not a safety classifier: they miss anything worded
differently, and a lookalike word raises a needless flag. Both rates are measured, never assumed.
"""

import hashlib
import json
import re
from pathlib import Path

from .rules import _forms, normalize

SIGNALS_PATH = Path(__file__).with_name("signals_v1.json")
KINDS = ("distress", "security", "legal_privacy", "instruction")
REASON_FOR = {kind: "signal_" + kind for kind in KINDS}
_SCHEMA = "neuron-flow-triage-signals-v1"
_GROUPS = ({"en", "th"}, {"en", "th", "markers"})


def _load(path=None):
    raw = Path(path or SIGNALS_PATH).read_bytes()
    data = json.loads(raw)
    if (not isinstance(data, dict) or set(data) != {"schema", "kinds", "signals"} or data["schema"] != _SCHEMA
            or data["kinds"] != list(KINDS) or not isinstance(data["signals"], dict)
            or set(data["signals"]) != set(KINDS)):
        raise ValueError("Invalid attention signal data")
    for groups in data["signals"].values():
        if not isinstance(groups, dict) or set(groups) not in _GROUPS:
            raise ValueError("Signal groups must contain English and Thai lists (and optionally markers)")
        for language, words in groups.items():
            if (not isinstance(words, list) or not words
                    or any(not isinstance(word, str) or not word.strip() for word in words)
                    or len(set(words)) != len(words)):
                raise ValueError("Signal phrases must be distinct nonempty strings")
            if language == "en" and any(not word.isascii() for word in words):
                raise ValueError("English signal phrases must be ASCII")
    return data, "signals-v1:" + hashlib.sha256(raw).hexdigest()


def signal_version():
    """Algorithm version plus the complete hash of the exact phrase bytes."""
    return _load()[1]


def find_signals(summary):
    """The kinds of attention signal in one case text, in the fixed order of ``KINDS``. Pure: no mutation, AI,
    side effect or decision, and nothing of the text is returned."""
    data, version = _load()
    texts = _forms(summary)
    plain = normalize(summary)
    found = []
    for kind in KINDS:
        groups = data["signals"][kind]
        english = any(re.search(r"(?<!\w)" + re.escape(form) + r"(?!\w)", text)
                      for word in groups["en"] for form in _forms(word) for text in texts)
        thai = any(normalize(word) in text for word in groups["th"] for text in texts)
        marker = any(normalize(word) in plain for word in groups.get("markers", ()))
        if english or thai or marker:
            found.append(kind)
    return {"signals": found, "signal_version": version}


def screen(message):
    output = find_signals(message["input"]["summary"])
    if message["params"]["signal_version"] != output["signal_version"]:
        raise ValueError("Attention signal data changed after this job was submitted")
    return output


def validate_screen(message, output):
    if output != screen(message):
        raise ValueError("Screen output violates the signals-v1 deterministic contract")
