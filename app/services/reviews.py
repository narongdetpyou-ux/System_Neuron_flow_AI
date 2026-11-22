"""Review decisions: a person approves or rejects a case that waits for review (roadmap 2.2, ADR-027).

Flow for one ``POST /v1/reviews/{review_id}/decisions``:
1. the body must hold ``decision`` (``APPROVE`` or ``REJECT``), ``reason`` (1-500 characters, the person's own
   words), ``expected_version`` (the review version the person looked at) and ``idempotency_key``; it may hold
   ``final_category``, one of the fixed triage categories. Approving without one keeps the rules' suggestion;
   rejecting without one records no category. It may also hold ``card_open_s``, how many seconds the decision card
   was open on the page before the person sent it (roadmap 2.10): a number from 0 to ``CARD_OPEN_MAX_S``, a
   measurement and not part of the decision, so it is left out of the request's fingerprint;
2. who decides comes from the credential, never from the body (``app.services.access``, ADR-034): the owner's shared
   key is recorded as ``shared-access-key`` with the role ``owner``, a reviewer's personal token as its token id
   with the role ``reviewer``. A submitter's token cannot decide;
3. the queue records the decision, the review's new state and version, and the job's new state in one
   transaction (``QueueStore.decide``). The same key with the same body returns the same decision; the same key
   with another body, a decided review or an old version is refused with 409 and changes nothing.

The AI never decides: no agent and no Runner code calls this, and n8n or MCP clients will not either (rule 4).
Approving records where the case goes (``final_queue``); it sends nothing outside. With an ``exchange`` (the API
always passes its own), the approval's skill-handoff route (ADR-030) starts the linked follow-up job in the same
transaction: for ``case_triage.v2`` that is ``case_triage.v2.apply``, which writes a Core receipt for the approval
(roadmap 2.3, ADR-004). A rejection starts nothing.
"""

import math
import re

from neuron_flow import SpecError
from neuron_flow.model import fingerprint

from app.domains.case_triage.contracts import CATEGORIES, QUEUE_FOR
from app.persistence import PENDING, REVIEW_STATES, DecisionConflict, StateError
from app.persistence.queue_store import CARD_OPEN_MAX_S, iso

from .access import OWNER_IDENTITY, PERMISSIONS
from .admission import IDEMPOTENCY_KEY

REASON_MAX_CHARS = 500
DECISIONS = ("APPROVE", "REJECT")
REVIEW_ID = re.compile(r"^rev_[0-9a-f]{24}$")
SHARED_KEY_REVIEWER = OWNER_IDENTITY.reviewer
DECIDE_ROLES = tuple(sorted(PERMISSIONS[("POST", "/v1/reviews/{review_id}/decisions")]))
_REQUIRED = {"decision", "reason", "expected_version", "idempotency_key"}
_OPTIONAL = {"final_category", "card_open_s"}
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")  # tabs and new lines are allowed in a reason
_PROPOSAL = ("suggested_category", "suggested_queue", "suggestion_source", "second_opinion", "agreement",
             "review_priority", "review_reasons", "mode")
_CONFLICT = {
    "idempotency_conflict": "This idempotency_key was already used for a different decision",
    "already_decided": "This review was already decided; decisions cannot be changed",
    "version_conflict": "The review changed since it was read; load it again before deciding",
}


class DecisionError(Exception):
    """A refused decision. ``status`` is the HTTP status, ``code`` a stable machine-readable reason."""

    def __init__(self, status, code, message, **extra):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra


def policy():
    """What the page needs to offer a decision: the choices, the limits and which roles may decide."""
    return {"decisions": list(DECISIONS), "categories": list(CATEGORIES), "queues": dict(QUEUE_FOR),
            "reason_max_chars": REASON_MAX_CHARS, "decide_roles": list(DECIDE_ROLES), "per_person_tokens": True,
            "card_open_max_s": CARD_OPEN_MAX_S}


def check_decision(body, review):
    """The normalized decision, or :class:`DecisionError` (400) before anything is written."""
    if not isinstance(body, dict) or not _REQUIRED <= set(body) <= _REQUIRED | _OPTIONAL:
        raise DecisionError(400, "invalid_fields", "The body must contain decision, reason, expected_version and "
                            "idempotency_key, and may contain final_category and card_open_s")
    decision = body["decision"]
    if decision not in DECISIONS:
        raise DecisionError(400, "invalid_decision", "decision must be APPROVE or REJECT")
    category = body.get("final_category")
    if category is not None and category not in CATEGORIES:
        raise DecisionError(400, "invalid_category", "final_category must be one of the fixed categories",
                            allowed=list(CATEGORIES))
    if category is None and decision == "APPROVE":
        category = review.get("suggested_category")  # approving as proposed keeps the rules' suggestion
    reason = body["reason"]
    if not isinstance(reason, str) or not reason.strip():
        raise DecisionError(400, "invalid_reason", "reason is required: say in your own words why")
    reason = reason.strip()
    if len(reason) > REASON_MAX_CHARS or _CONTROL.search(reason):
        raise DecisionError(400, "invalid_reason",
                            f"reason must be at most {REASON_MAX_CHARS} characters of text, without control characters")
    version = body["expected_version"]
    if type(version) is not int or not 1 <= version <= 2 ** 31:
        raise DecisionError(400, "invalid_version", "expected_version must be the review's version, a whole number")
    key = body["idempotency_key"]
    if not isinstance(key, str) or not IDEMPOTENCY_KEY.fullmatch(key):
        raise DecisionError(400, "invalid_idempotency_key",
                            "idempotency_key must be 8-128 letters, digits, '.', '_', ':' or '-'")
    return {"decision": decision, "final_category": category, "reason": reason, "expected_version": version,
            "idempotency_key": key, "card_open_s": check_card_open(body.get("card_open_s"))}


def check_card_open(value):
    """Seconds the decision card was open (roadmap 2.10), rounded to a tenth, or ``None`` when the client did not say.

    A number from 0 to ``CARD_OPEN_MAX_S``; anything else is refused (400) rather than guessed, because a wrong value
    would be counted silently. A JSON number too large for a float, such as 1e400, arrives as infinity."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        valid = False
    else:
        try:
            valid = math.isfinite(value) and 0 <= value <= CARD_OPEN_MAX_S
        except OverflowError:  # an integer too large to compare as a float
            valid = False
    if not valid:
        raise DecisionError(400, "invalid_card_open_s", "card_open_s must be the seconds the decision card was open: "
                            f"a number from 0 to {CARD_OPEN_MAX_S}", max_s=CARD_OPEN_MAX_S)
    return round(float(value), 1) + 0.0  # + 0.0 turns -0.0 into 0.0


def decide(store, review_id, body, *, reviewer=None, request_id=None, exchange=None):
    """Returns ``(review, decision_row, created)``; raises :class:`DecisionError` when the decision is refused.

    ``exchange`` (an :class:`app.exchange.Exchange`) writes the handoff the new state starts, in the same transaction.
    """
    reviewer = reviewer or SHARED_KEY_REVIEWER
    review = store.get_review(review_id)
    if review is None:
        raise DecisionError(404, "review_not_found", "No review with this id")
    checked = check_decision(body, review)
    try:
        # card_open_s stays out: a retried click is the same decision, even when its card was open longer by then.
        digest = fingerprint({"review_id": review_id, **{k: checked[k] for k in
                                                         ("decision", "final_category", "reason", "expected_version")}})
    except SpecError:  # text Core's encoder cannot hold, such as half of an emoji
        raise DecisionError(400, "invalid_reason", "The reason holds characters that cannot be stored, "
                            "such as half of an emoji") from None
    try:
        row, created = store.decide(review_id, decision=checked["decision"], final_category=checked["final_category"],
                                    reason=checked["reason"], expected_version=checked["expected_version"],
                                    idempotency_key=checked["idempotency_key"], request_sha256=digest,
                                    reviewer_token_id=reviewer["token_id"], reviewer_role=reviewer["role"],
                                    request_id=request_id, card_open_s=checked["card_open_s"],
                                    handoff=exchange.prepare if exchange else None)
    except KeyError:
        raise DecisionError(404, "review_not_found", "No review with this id") from None
    except DecisionConflict as exc:
        raise DecisionError(409, exc.code, _CONFLICT[exc.code], **exc.extra) from None
    except StateError:
        raise DecisionError(409, "not_reviewable", "The case is no longer waiting for review") from None
    return store.get_review(review_id), row, created


# -- views ------------------------------------------------------------------------------------

def decision_view(row):
    """One decision as the API shows it. Never its ``card_open_s``: reviewer time is reported per group of cases in
    the scorecard (roadmap 2.10), never per decision or per person."""
    if row is None:
        return None
    approved = row["decision"] == "APPROVE"
    # The token's display name when the decision came from a personal token that still exists (ADR-034).
    reviewer = {"token_id": row["reviewer_token_id"], "role": row["reviewer_role"], "name": row.get("reviewer_name")}
    return {"decision_id": row["decision_id"], "version": row["version"], "decision": row["decision"],
            "final_category": row["final_category"],
            "final_queue": QUEUE_FOR.get(row["final_category"]) if approved else None,
            "reason": row["reason"], "reviewer": reviewer,
            "request_id": row["request_id"], "created_at": iso(row["created_at"])}


def review_summary(review):
    """A review in a list: enough to choose which one to open."""
    case = review.get("input") or {}
    return {"review_id": review["review_id"], "job_id": review["job_id"], "state": review["state"],
            "version": review["version"], "priority": review["priority"],
            "suggested_category": review["suggested_category"], "workflow_type": review["workflow_type"],
            "case_id": case.get("case_id"), "summary_preview": (case.get("summary") or "")[:90],
            "created_at": iso(review["created_at"]), "decided_at": iso(review["decided_at"])}


def review_detail(review):
    """One review: the case, the proposal (rules, AI second opinion, why it was raised) and every decision."""
    proposal = ((review.get("result") or {}).get("review")) or {}
    return {**review_summary(review), "case": review.get("input"), "proposal_sha256": review["proposal_sha256"],
            "proposal": {field: proposal.get(field) for field in _PROPOSAL},
            "decisions": [decision_view(row) for row in review.get("decisions", [])],
            "decidable": review["state"] == PENDING}


def job_review_view(review):
    """The review part of a job's detail view (``None`` for a job that never waited for review)."""
    if review is None:
        return None
    return {"review_id": review["review_id"], "state": review["state"], "version": review["version"],
            "priority": review["priority"], "created_at": iso(review["created_at"]),
            "decided_at": iso(review["decided_at"]), "decision": decision_view(review.get("decision")),
            "decidable": review["state"] == PENDING}


def parse_after(raw):
    """The ``after`` cursor of ``GET /v1/reviews`` (``<rank>-<seq>``, as ``next_after`` gave it), or ``None``."""
    match = re.fullmatch(r"([01])-([0-9]{1,18})", raw or "")
    return (int(match.group(1)), int(match.group(2))) if match else None


def known_state(raw):
    return raw if raw in REVIEW_STATES else None
