"""Translators for the case-triage skills: ``case_triage.v2`` (out) and ``case_triage.v2.apply`` (in).

They import only the skill's fixed vocabulary (``contracts.py``), never its agents or another translator.
"""

from app.domains.case_triage.contracts import QUEUE_FOR

from ..common import fact
from .base import SourceIncomplete

# What out.case_triage.v2@1 may say about an approved case, in the common language.
OUT_FACTS = ("request.text", "case.id", "case.suggested_category", "case.second_opinion", "case.final_category",
             "case.final_queue", "review.decision_id", "review.reviewer_role")
# What in.case_triage.v2.apply@1 reads to build the apply job's own input.
APPLY_READS = ("case.id", "case.final_category", "case.final_queue", "review.decision_id", "review.reviewer_role")


def triage_v2_out(source):
    """An approved ``case_triage.v2`` job → facts; :class:`SourceIncomplete` when the record lacks what is needed."""
    review = (source.result or {}).get("review")
    decision = source.decision or {}
    if source.state != "APPROVED" or not isinstance(review, dict) or decision.get("decision") != "APPROVE":
        raise SourceIncomplete("an approved case_triage.v2 job with its proposal and an APPROVE decision")
    category = decision.get("final_category")
    if category not in QUEUE_FOR:
        raise SourceIncomplete("the decision holds no approved category")
    case = source.input or {}
    facts = {
        "request.text": fact(case.get("summary"), "input"),
        "case.id": fact(case.get("case_id"), "input"),
        "case.suggested_category": fact(review.get("suggested_category"), "rules"),
        "case.final_category": fact(category, "person"),
        "case.final_queue": fact(QUEUE_FOR[category], "person"),  # mapped by code from the person's choice
        "review.decision_id": fact(decision.get("decision_id"), "person"),
        "review.reviewer_role": fact(decision.get("reviewer_role"), "person"),
    }
    second = review.get("second_opinion")
    if isinstance(second, dict) and second.get("status") == "ok":
        facts["case.second_opinion"] = fact(second.get("category"), "ai")  # data only; routes never read it
    return facts


def apply_in(facts):
    """Facts → the input of ``case_triage.v2.apply`` (its own field names)."""
    value = {name: item["value"] for name, item in facts.items()}
    return {"case_id": value["case.id"], "final_category": value["case.final_category"],
            "final_queue": value["case.final_queue"], "decision_id": value["review.decision_id"],
            "approved_by": value["review.reviewer_role"]}
