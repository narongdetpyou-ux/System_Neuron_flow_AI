"""Fixed vocabulary of the plain-language router (``intake.route.v1``, roadmap 4.2, ADR-039)."""

import re
import unicodedata

ROUTE_VERSION = "route-1"           # the rules of check and respond; change it when they change
UNDERSTAND_PROMPT_ID = "intake_understand_v1"
OUT_OF_SCOPE = "out_of_scope"       # the frame reserves this id for "no task fits" (app/services/frame.py)
STUDY_TASK = "study_guide"          # the frame task that offers study resources (the first-response rule)

# The person's message, after trimming: 4-500 characters a reader can see (invisible format characters do not
# count towards the minimum), as strict as every task's own field, so the router never accepts text that a task
# would refuse for its characters. Each task's own length is checked again from the frame (``check``).
MESSAGE_MIN_CHARS = 4
MESSAGE_MAX_CHARS = 500
LLM_MAX_ATTEMPTS = 2

CONFIDENCE_LEVELS = ("low", "medium", "high")
LANGUAGES = ("th", "en")
YES_NO = ("no", "yes")
# What the router answers: exactly one kind. It never runs a task: a person confirms a proposal first.
KINDS = ("proposal", "confirm", "question", "out_of_scope", "not_understood")
# Why ``check`` reached its verdict. Only ``fits`` lets ``respond`` propose the task.
CHECK_REASONS = ("fits", "needs_more", "too_short", "too_long", "out_of_scope", "not_understood")

# Why the AI step has no answer. The first two are only accepted after every allowed attempt was used.
UNAVAILABLE_REASONS = ("provider_unavailable", "invalid_model_output", "model_declined")
FINAL_ATTEMPT_REASONS = ("provider_unavailable", "invalid_model_output")

CONFIRM_QUESTION = {"th": "เข้าใจถูกไหม", "en": "Did I understand you correctly?"}
NOT_UNDERSTOOD = {"th": "ตอนนี้ระบบยังอ่านข้อความนี้ไม่ได้ เลือกงานจากรายการนี้เองได้",
                  "en": "The system could not read this message just now. You can choose a task from this list"}

# Arabic letter mark, left-to-right and right-to-left marks, embeddings, overrides and isolates (Unicode bidi controls).
BIDI_CONTROLS = re.compile("[؜‎‏‪-‮⁦-⁩]")
FRAME_TAG = re.compile(r"^frame-v[1-9][0-9]{0,2}@sha256:[0-9a-f]{64}$")
_THAI = re.compile(r"[฀-๿]")


def visible_length(text):
    """How many characters of ``text`` are not invisible format characters (Unicode category Cf)."""
    return sum(1 for character in text if unicodedata.category(character) != "Cf")


def has_visible_character(text):
    """Whether ``text`` holds a letter, digit, punctuation mark or symbol, not only marks, spaces or invisible ones."""
    return any(unicodedata.category(character)[0] in "LNPS" for character in text)


def language_of(text):
    """A plain character test, used when the AI gave no answer: Thai letters make it ``th``."""
    return "th" if _THAI.search(text) else "en"
