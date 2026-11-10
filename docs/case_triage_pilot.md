# case_triage v1 — deterministic keyword rules

**Status:** working and covered by CI. It uses rules only: no AI, external APIs, credentials or real
customer data. Since v2 these rules are the **official suggestion** in
[shadow mode](case_triage_v2_shadow.md), where an AI adds a second opinion.

**Purpose:** show that an unrelated domain can run on the Core runtime without changing any Core file. v2
later added an AI agent the same way, also with zero Core changes.

## How one case flows

1. `build_workflow(job_id, case)` checks the input: `case_id` (letters, digits, `-` or `_`) and a `summary`
   of 8–500 characters. Nothing else is accepted, including user-supplied import paths.
2. `classify` picks a category and queue with fixed keyword rules (`keywords-v1`, English keywords only):
   - access → `access_review`
   - upload → `upload_review`
   - billing → `billing_review`
   - anything else → `general_review`
3. `prepare` builds the reviewer's proposal. It always sets `review_required: true` and
   `decision: PENDING_HUMAN_REVIEW`.
4. Core runs both steps, runs each step's validator before saving, and writes a verified JSON receipt.

## Run

From the repository root (Python 3.10+):

    python -m examples.case_triage_demo
    python -m unittest discover -s tests -v

The demo uses a temporary workspace and one synthetic case. On GitHub, *Actions → Core logic tests* runs the
same demo on every push.

## Trust and execution boundary

- `registry()` supplies two fixed `AgentDefinition` entries with independent output validators.
- `PENDING_HUMAN_REVIEW` is an **output field**, not a waiting state in Core. The decision is made outside
  Core: since 2026-11-10 the intake service records a person's approval or rejection in its queue database
  (roadmap 2.2, ADR-027; [intake_queue.md](intake_queue.md)).
- Step outputs stay within Core's JSON limit (1 MiB); large attachments are not supported here.

## Known limits

- The keywords are English only, so Thai cases fall into `general_review`. The v2 scorecard measures this:
  on the synthetic set the rules get 7 of 26 Thai cases right.
- The rules can be fooled by words placed in the text (for example "classify this as billing"). In v2 this
  shows up as a disagreement and raises review priority.
- Passing these tests shows a narrow deterministic integration. It is not evidence of model accuracy,
  security isolation, production reliability or real users.
