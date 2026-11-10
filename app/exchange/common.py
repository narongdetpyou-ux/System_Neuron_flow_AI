"""The common language of the skill-handoff exchange (ADR-030): facts from one versioned vocabulary.

A fact is ``{"value": …, "origin": …}`` under a name from ``vocabulary_v1.json``. The vocabulary says, for each
name, its type (``text``, ``id``, ``choice``), its limits and the origins it may come from:

* ``input``: typed by a person; ``rules``: made by code; ``person``: a reviewer's decision;
* ``ai``: a model's answer after its checks. It is data only: no route ever depends on it.

The vocabulary is versioned data. Its tag carries the complete SHA-256 of the file
(``vocabulary-v1@sha256:…``), and every handoff records it, so a changed file is visibly a new language.
"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
VOCABULARY_FILE = HERE / "vocabulary_v1.json"
TYPES = ("text", "id", "choice")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class FactInvalid(ValueError):
    """A fact the vocabulary does not allow. ``why`` is one of: ``unknown_fact``, ``bad_shape``, ``bad_origin``,
    ``bad_value``. The message never repeats the value (it may be a person's words)."""

    def __init__(self, name, why):
        super().__init__(f"{name}: {why}")
        self.name, self.why = name, why


def tagged(version, raw):
    """``<version>@sha256:<complete hex digest of the file's bytes>``."""
    return f"{version}@sha256:{hashlib.sha256(raw).hexdigest()}"


def fact(value, origin):
    return {"value": value, "origin": origin}


@dataclass(frozen=True)
class Vocabulary:
    version: str
    tag: str
    origins: dict
    facts: dict

    @classmethod
    def load(cls, path=VOCABULARY_FILE):
        raw = Path(path).read_bytes()
        data = json.loads(raw.decode("utf-8"))
        if set(data) != {"version", "origins", "facts"} or not isinstance(data["facts"], dict):
            raise ValueError("A vocabulary holds exactly version, origins and facts")
        for name, entry in data["facts"].items():
            if not re.fullmatch(r"[a-z]+\.[a-z_]+", name):
                raise ValueError(f"Fact name {name!r} must look like area.name")
            if entry.get("type") not in TYPES or not entry.get("origins") \
                    or not set(entry["origins"]) <= set(data["origins"]):
                raise ValueError(f"Fact {name} needs a known type and known origins")
            if entry["type"] == "choice" and not entry.get("values"):
                raise ValueError(f"Choice fact {name} needs values")
            if entry["type"] == "id":
                re.compile(entry["pattern"])
            if entry["type"] == "text" and not isinstance(entry.get("max_chars"), int):
                raise ValueError(f"Text fact {name} needs max_chars")
            if set(entry.get("meaning", {})) != {"en", "th"}:
                raise ValueError(f"Fact {name} needs its meaning in English and Thai")
        return cls(data["version"], tagged(data["version"], raw), data["origins"], data["facts"])

    def check(self, name, item):
        """Raises :class:`FactInvalid` unless ``item`` is a fact this vocabulary allows under ``name``."""
        entry = self.facts.get(name)
        if entry is None:
            raise FactInvalid(name, "unknown_fact")
        if not isinstance(item, dict) or set(item) != {"value", "origin"}:
            raise FactInvalid(name, "bad_shape")
        if item["origin"] not in entry["origins"]:
            raise FactInvalid(name, "bad_origin")
        value = item["value"]
        if entry["type"] == "choice":
            ok = isinstance(value, str) and value in entry["values"]
        elif entry["type"] == "id":
            ok = isinstance(value, str) and re.fullmatch(entry["pattern"], value) is not None
        else:
            ok = isinstance(value, str) and 1 <= len(value) <= entry["max_chars"] and not _CONTROL.search(value)
            if ok:
                try:
                    value.encode("utf-8")
                except UnicodeEncodeError:  # half of an emoji (a lone surrogate) cannot be stored
                    ok = False
        if not ok:
            raise FactInvalid(name, "bad_value")

    def view(self):
        """Names, types and meanings for people (the page, ``/v1/status``); no patterns, no values."""
        return {name: {"type": entry["type"], "origins": list(entry["origins"]), "meaning": dict(entry["meaning"])}
                for name, entry in self.facts.items()}
