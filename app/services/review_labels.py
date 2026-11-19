"""Rules and AI against people's decisions: the reviewer-label scorecard (roadmap 2.8).

When a person decides a case, the category they record (``final_category``) is a label a person gave. This module
counts, over the newest decided cases in the queue database, how often the rules' official suggestion and the AI's
second opinion named that same category. ADR-010 asks for this measurement before the AI's role may change (owner
decision D6). It only counts: it changes no case, no priority and no decision, and no workflow reads it (rule 4).

What counts:
* **a label**: a decision with a ``final_category``. An approval always has one (approving as proposed keeps the
  rules' suggestion); a rejection has one only when the person named the right category. A rejection without one is
  ``unlabelled`` and stays out of every rate;
* **rules match**: the label equals the rules' suggestion, over the labelled cases;
* **AI answered**: the AI gave a category (it was not ``unavailable``), over the labelled cases. **AI match**: its
  category equals the label, over the labelled cases it answered (the scorecards' convention, ``app/eval``);
* **when rules and AI disagree**: whose category the person recorded, or neither one's;
* **by language**: ``th`` when the case text holds a Thai letter, otherwise ``non_th``. A Thai letter is a letter of
  the Thai script (Unicode categories Lo and Lm in U+0E00-U+0E7F): the baht sign, Thai digits and tone marks alone do
  not make a case Thai, so "I was charged ฿500 twice" is ``non_th`` (quality report of 2026-11-19, finding 3). Code
  decides, because a live case has no language label. The text is read here and never returned.

One group per proposal source: the workflow type, the rules version, and the AI agent's version as Core recorded it
(``ai.agent_version`` in the job's result: provider, model, prompt, answer budget, effort, masking rules, the gateway's
answer checks and the answer format; ADR-035). Figures of two versions are never added together. A changed keyword
list, model, prompt, answer budget or set of checks is a new version (rule 5), and a number that mixed two would
describe neither. A result recorded before the agent version was kept (2026-11-19) has none: its group keeps the
provider, model and prompt apart as before, and says that the version is unknown (``version_known`` false).

Every rate keeps its numerator and denominator, and carries the 95% Wilson score interval: with few cases it is
wide, which is the point (2 of 2 is not 100%).

Honest limits (the reply says them in ``label_scope``; the page says them in Thai):
* the person saw the rules' suggestion and the AI's opinion before deciding, and approving without choosing keeps
  the rules' category, so these labels lean towards the proposal. They are not blind labels;
* the cases are synthetic, so no rate here is real-world accuracy, however many cases there are;
* with the mock provider the AI's figures describe a keyword simulation, not an AI;
* on storage that is not persistent the queue starts empty after every sleep, restart and deploy (ADR-029), so the
  report covers the decisions since then. Labels add up over days only on a disk (D1);
* the report reads the newest ``WINDOW`` decided cases at most.
"""

import math
import re

from app.persistence.queue_store import iso

SCHEMA = "neuron-flow-reviewer-labels-v1"
WINDOW = 500  # the newest decided cases
LANGUAGES = ("th", "non_th")
LABEL_SCOPE = ("Each label is the category a person recorded for a synthetic case, after seeing the rules' "
               "suggestion and the AI's opinion; approving as proposed keeps the rules' category. Not blind labels, "
               "not independent ground truth and not real-world accuracy.")
Z_95 = 1.959963984540054  # the 97.5th percentile of the standard normal distribution
# The letters of the Thai script (Lo and Lm): not U+0E31 and U+0E34-U+0E3A or U+0E47-U+0E4E (vowel and tone marks),
# U+0E3F (the baht sign), U+0E50-U+0E59 (Thai digits) or U+0E4F, U+0E5A, U+0E5B (signs).
_THAI_LETTER = re.compile(r"[ก-ะาำเ-ๆ]")
_AI_FIELDS = ("provider", "model", "prompt_id", "prompt_sha256")


def language_of(text):
    """``th`` for text that holds a Thai letter, otherwise ``non_th`` (the scorecards' rule for a Thai case)."""
    return "th" if isinstance(text, str) and _THAI_LETTER.search(text) else "non_th"


def _ai_key(provenance):
    """What tells two AI setups apart: the agent version Core recorded (ADR-035), then the provider, model and prompt.
    A result recorded before the version was kept has ``None`` first, so it never joins a group of a known version."""
    version = provenance.get("agent_version")
    return (version if isinstance(version, str) else None, *(provenance.get(field) for field in _AI_FIELDS))


def interval_95(numerator, denominator):
    """The 95% Wilson score interval of a proportion, ``(low, high)``, or ``(None, None)`` without data."""
    if not denominator:
        return None, None
    share = numerator / denominator
    centre = share + Z_95 ** 2 / (2 * denominator)
    margin = Z_95 * math.sqrt(share * (1 - share) / denominator + Z_95 ** 2 / (4 * denominator ** 2))
    scale = 1 + Z_95 ** 2 / denominator
    return round(max(0.0, (centre - margin) / scale), 4), round(min(1.0, (centre + margin) / scale), 4)


def rate(numerator, denominator):
    low, high = interval_95(numerator, denominator)
    return {"numerator": numerator, "denominator": denominator,
            "rate": round(numerator / denominator, 4) if denominator else None, "low_95": low, "high_95": high}


def _row(review):
    """What the report needs from one decided review; never the case text or the person's reason."""
    result = review.get("result") or {}
    proposal = result.get("review") or {}
    second = proposal.get("second_opinion")
    provenance = result.get("ai") or {}
    has_ai = isinstance(second, dict)  # a rules-only workflow has no second opinion at all
    answered = has_ai and second.get("status") == "ok"
    return {"workflow_type": review["workflow_type"],
            "rules": proposal.get("suggestion_source"),
            "rules_category": review["suggested_category"],
            "ai": _ai_key(provenance) if has_ai else None,
            "ai_answered": answered,
            "ai_category": second.get("category") if answered else None,
            "decision": review["decision"],
            "label": review["final_category"],
            "language": language_of((review.get("input") or {}).get("summary")),
            "role": review["reviewer_role"],
            "credential": review["reviewer_token_id"],
            "at": review["decision_at"]}


def _counts(rows):
    return {"decided": len(rows),
            "approved": sum(r["decision"] == "APPROVE" for r in rows),
            "rejected": sum(r["decision"] == "REJECT" for r in rows),
            "labelled": sum(r["label"] is not None for r in rows),
            "unlabelled": sum(r["label"] is None for r in rows)}


def _scores(rows, has_ai):
    """The rates of one set of decided cases. Without an AI in the workflow the AI's rates are ``None``, not 0."""
    labelled = [r for r in rows if r["label"] is not None]
    answered = [r for r in labelled if r["ai_answered"]]
    return {"decided": len(rows), "labelled": len(labelled),
            "rules_match": rate(sum(r["rules_category"] == r["label"] for r in labelled), len(labelled)),
            "ai_answered": rate(len(answered), len(labelled)) if has_ai else None,
            "ai_match": rate(sum(r["ai_category"] == r["label"] for r in answered), len(answered)) if has_ai else None}


def _group(rows):
    first = rows[0]
    has_ai = first["ai"] is not None
    labelled = [r for r in rows if r["label"] is not None]
    answered = [r for r in labelled if r["ai_answered"]]
    disagreeing = [r for r in answered if r["ai_category"] != r["rules_category"]]
    ai = None
    if has_ai:
        version, *fields = first["ai"]
        ai = {**dict(zip(_AI_FIELDS, fields)), "agent_version": version, "version_known": version is not None}
        ai["simulated"] = ai["provider"] == "mock"
    return {"workflow_type": first["workflow_type"], "rules": first["rules"], "ai": ai,
            **_counts(rows), **{key: value for key, value in _scores(rows, has_ai).items()
                                if key not in ("decided", "labelled")},
            "rules_ai_agree": rate(len(answered) - len(disagreeing), len(answered)) if has_ai else None,
            # The person's category when the two differed: the question behind owner decision D6.
            "when_disagreeing": {"total": len(disagreeing),
                                 "ai_match": sum(r["ai_category"] == r["label"] for r in disagreeing),
                                 "rules_match": sum(r["rules_category"] == r["label"] for r in disagreeing),
                                 "neither": sum(r["label"] not in (r["ai_category"], r["rules_category"])
                                                for r in disagreeing)} if has_ai else None,
            "by_language": {language: _scores([r for r in rows if r["language"] == language], has_ai)
                            for language in LANGUAGES if any(r["language"] == language for r in rows)},
            "first_decision_at": iso(min(r["at"] for r in rows)),
            "last_decision_at": iso(max(r["at"] for r in rows))}


def report(store, *, window=WINDOW):
    """The scorecard over the newest ``window`` decided cases of the queue database, newest group first."""
    reviews, decided_total = store.decided_reviews(window)
    rows = [_row(review) for review in reviews]
    groups = {}
    for row in rows:  # newest first, so a dict keeps the groups in the order of their latest decision
        groups.setdefault((row["workflow_type"], row["rules"], row["ai"]), []).append(row)
    roles = {}
    for row in rows:
        roles[row["role"]] = roles.get(row["role"], 0) + 1
    return {"schema": SCHEMA, "label_scope": LABEL_SCOPE,
            "window": {"limit": window, "decided": len(rows), "decided_total": decided_total,
                       "truncated": decided_total > len(rows)},
            "totals": {**_counts(rows), "by_role": dict(sorted(roles.items())),
                       # How many different credentials decided: one person's labels, or several people's.
                       "reviewers": len({row["credential"] for row in rows})},
            "groups": [_group(group) for group in groups.values()]}
