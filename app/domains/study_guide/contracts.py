"""Fixed vocabulary of the study guide workflow (``study_guide.v1``, roadmap 3.2)."""

from neuron_flow import PermanentAgentError

LIBRARY_VERSION = "v1"
DETECT_PROMPT_ID = "study_detect_topic_v1"
EXPLAIN_PROMPT_ID = "study_explain_v1"
STUDY_VERSION = "study-1"  # the rules of pick_resources, build_path and prepare; change it when they change

# The person's message, counted after trimming spaces at both ends (checked before any agent runs).
MESSAGE_MIN_CHARS = 4
MESSAGE_MAX_CHARS = 500

MAX_RESOURCES = 5        # design_philosophy.md: at most 5 resources, so a beginner is not overwhelmed
MAX_MAIN_RESOURCES = 3   # resources of the topic itself; the rest of the budget goes to prerequisites
LLM_MAX_ATTEMPTS = 2

CONFIDENCE_LEVELS = ("low", "medium", "high")
ANSWER_LANGUAGES = ("th", "en")
ROLES = ("main", "prerequisite")
PRIORITIES = ("prerequisite", "core", "later")  # skip if you know it · most important · can wait
ANSWER_STATUSES = ("guide", "out_of_scope", "not_understood")

# Why an AI step has no answer. The first two are only accepted after every allowed attempt was used.
UNAVAILABLE_REASONS = ("provider_unavailable", "invalid_model_output", "model_declined")
FINAL_ATTEMPT_REASONS = ("provider_unavailable", "invalid_model_output")

PRIORITY_LABELS = {
    "th": {"prerequisite": "พื้นฐานที่ควรรู้ก่อน (ข้ามได้ถ้ารู้แล้ว)", "core": "สำคัญที่สุด", "later": "อ่านทีหลังได้"},
    "en": {"prerequisite": "Background first (skip it if you know it)", "core": "Most important",
           "later": "Can wait"},
}
LEVEL_LABELS = {
    "th": {"beginner": "เริ่มต้น", "intermediate": "กลาง", "advanced": "ลึก"},
    "en": {"beginner": "beginner", "intermediate": "intermediate", "advanced": "advanced"},
}
CONFIRM_QUESTION = {"th": "เข้าใจถูกไหม", "en": "Did I understand you correctly?"}


class LibraryChanged(PermanentAgentError):
    """The library (or a prompt) differs from the one frozen into the job: never answer from another one."""
