"""Fixed vocabulary shared by the triage workflows (v1 rules and v2 shadow mode)."""

CATEGORIES = ("access", "upload", "billing", "other")
QUEUE_FOR = {"access": "access_review", "upload": "upload_review",
             "billing": "billing_review", "other": "general_review"}
CONFIDENCE_LEVELS = ("low", "medium", "high")

# Why a case is flagged for the reviewer (shown in the proposal).
REVIEW_REASONS = ("rules_llm_disagree", "llm_low_confidence", "llm_unavailable", "rules_no_keyword_match")

# Why the AI second opinion is missing.
UNAVAILABLE_REASONS = ("provider_unavailable", "invalid_model_output", "model_declined")
# These two are only accepted after every allowed attempt was used.
FINAL_ATTEMPT_REASONS = ("provider_unavailable", "invalid_model_output")
