"""Trusted deterministic support triage agents (demonstration only).

All rules are examples, not verified real-world triage policy. No external calls,
AI inference, credential access, or irreversible side effects.
"""

def _classification(case):
    summary = case["summary"].lower()
    # Fixed rule precedence makes repeat submissions deterministic.
    if any(word in summary for word in ("password", "sign in", "login", "account access")):
        return {"category": "access", "queue": "access_review", "rule_version": "keywords-v1"}
    if any(word in summary for word in ("upload", "attachment", "file transfer")):
        return {"category": "upload", "queue": "upload_review", "rule_version": "keywords-v1"}
    if any(word in summary for word in ("payment", "billing", "invoice")):
        return {"category": "billing", "queue": "billing_review", "rule_version": "keywords-v1"}
    return {"category": "other", "queue": "general_review", "rule_version": "keywords-v1"}


def classify(message):
    return _classification(message["input"])


def validate_classification(message, output):
    if output != _classification(message["input"]):
        raise ValueError("Classification output violates the v1 deterministic contract")


def prepare(message):
    classified = message["dependencies"]["classify"]
    return {
        "case_id": message["input"]["case_id"],
        "category": classified["category"],
        "suggested_queue": classified["queue"],
        "review_required": True,
        "decision": "PENDING_HUMAN_REVIEW",
    }


def validate_preparation(message, output):
    classified = _classification(message["input"])
    expected = {
        "case_id": message["input"]["case_id"],
        "category": classified["category"],
        "suggested_queue": classified["queue"],
        "review_required": True,
        "decision": "PENDING_HUMAN_REVIEW",
    }
    if message["dependencies"]["classify"] != classified or output != expected:
        raise ValueError("Preparation output violates the v1 review contract")
