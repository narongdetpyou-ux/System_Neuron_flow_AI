"""Strict application input contract and fixed, trusted DAG template.

What a case's ``summary`` must be (roadmap 5.5, the robustness benchmark's invisible-text gaps):
* 8-500 characters after trimming, where the minimum counts only characters a reader can see: invisible format
  characters (Unicode category Cf, such as zero-width spaces) do not count, so ten of them are not a case;
* at least one letter, digit, punctuation mark or symbol: a string of Thai vowel or tone marks alone, with no
  consonant, says nothing;
* no characters that change the direction of the text (bidi controls such as U+202E). They make a reviewer read
  something other than what the rules and the AI read, and Thai or English text never needs them.
Zero-width spaces inside real text are kept: Thai text copied from some websites carries them between words.
"""

import re
import unicodedata

from neuron_flow import AgentDefinition, SpecError
from . import agents
from .contracts import SUMMARY_MAX_CHARS, SUMMARY_MIN_CHARS

_CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
# Arabic letter mark, left-to-right and right-to-left marks, embeddings, overrides and isolates (Unicode bidi controls).
BIDI_CONTROLS = re.compile("[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def visible_length(text):
    """How many characters of ``text`` are not invisible format characters (Unicode category Cf)."""
    return sum(1 for character in text if unicodedata.category(character) != "Cf")


def has_visible_character(text):
    """Whether ``text`` holds a letter, digit, punctuation mark or symbol, not only marks, spaces or invisible ones."""
    return any(unicodedata.category(character)[0] in "LNPS" for character in text)


def registry():
    """Trusted entrypoints are built in code; never supplied by a user request."""
    return [
        AgentDefinition("triage.classify", "app.domains.case_triage.agents:classify",
                        agents.validate_classification, version="1"),
        AgentDefinition("triage.prepare", "app.domains.case_triage.agents:prepare",
                        agents.validate_preparation, version="1"),
    ]


def build_workflow(job_id, case):
    """Produce one immutable v1 core workflow from a bounded synthetic case."""
    if not isinstance(job_id, str) or _CASE_ID.fullmatch(job_id) is None:
        raise SpecError("job_id must be a valid core identifier")
    if not isinstance(case, dict) or set(case) != {"case_id", "summary"}:
        raise SpecError("Case input must contain only case_id and summary")
    case_id = case["case_id"]
    summary = case["summary"]
    if not isinstance(case_id, str) or _CASE_ID.fullmatch(case_id) is None:
        raise SpecError("case_id must be a valid identifier")
    if not isinstance(summary, str):
        raise SpecError("summary must be text")
    trimmed = summary.strip()
    if BIDI_CONTROLS.search(trimmed):
        raise SpecError("summary must not contain characters that change the direction of the text (bidi controls "
                        "such as U+202E); they make a reviewer read something else")
    if (not SUMMARY_MIN_CHARS <= visible_length(trimmed) or len(trimmed) > SUMMARY_MAX_CHARS
            or not has_visible_character(trimmed)):
        raise SpecError(f"summary must contain {SUMMARY_MIN_CHARS}–{SUMMARY_MAX_CHARS} characters, not counting "
                        "invisible ones, with at least one letter, digit or sign")
    return {
        "job_id": job_id,
        "input": {"case_id": case_id, "summary": trimmed},
        "steps": [
            {"id": "classify", "agent": "triage.classify", "max_attempts": 1},
            {"id": "prepare", "agent": "triage.prepare",
             "depends_on": ["classify"], "max_attempts": 1},
        ],
    }
