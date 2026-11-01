# Illustrative budget and acceptance milestones

**Not a quote, approved grant award, or actual expenditure.**
Currency: **USD**. Example request: **$10,000** over an **estimated 12 weeks**.
All rates, hours and vendor costs are planning assumptions; suitability and
eligible costs must be confirmed for each specific funder. Do not represent
anyone as contracted, paid or recruited.

## Budget assumptions

| Cost heading | Quantity / assumed unit price | Estimated USD |
|---|---:|---:|
| Independent developer implementation & tests | 240 hours × $25 | $6,000 |
| External security / reliability technical review | 30 hours × $60 | $1,800 |
| Testing hardware / accessible development setup | Allowance, if eligible | $900 |
| CI, hosting, reproducibility and AI API usage for evaluation runs | Allowance | $500 |
| Technical documentation/accessibility review | 20 hours × $30 | $600 |
| Contingency or unallocated buffer | Allowance, **only if allowed** | $200 |
| **Illustrative total** | | **$10,000** |

The plan assumes 20 implementation hours per week for 12 weeks. External
review and documentation hours are separate. Unallowable costs (especially
hardware, applicant labor or contingency) must be removed or re-budgeted
before submission; no vendor quotation has been collected.

## Milestones: targets, not claimed accomplishments

| Gate | Indicative window | Acceptance evidence |
|---|---|---|
| M0 — Existing foundation | Before funded work (in place as of 2026-11-01) | Code SHA `59c6889` and green CI; `docs/architecture.md`; triage v1 rules and v2 AI shadow mode (tested offline); Sentry monitoring; synthetic scorecard |
| M1 — Admission/Runner | Weeks 1–3 | Deterministic request-key idempotency; concurrent duplicate cases; only Runner opens Core Runtime |
| M2 — Crash recovery | Weeks 4–6 | Controlled worker/controller interruption; replay reconciliation; no unsafely repeated external effects |
| M3 — Human review + artifact checks | Weeks 7–9 | Authenticated accept/reject; single linked phase-B job; unauthorized decision rejected; changed artifact detected |
| M4 — Independent review + repeatable release | Weeks 10–12 | Recorded findings and resolutions; second unrelated domain without Core changes; reproducible CI and docs |

**Funding disbursement must follow each funder's own rules**; these windows
are proposal assumptions only, not guaranteed program tranches.

## Change control

Any scope extension should include an acceptance test, a corresponding
reallocation of budget and a written justification. Failure to find external
reviewers or a usable budget route should be reported transparently rather
than converted into fictional deliverables.

The funder-specific application should also explain software licensing and
any use of generative AI, where required. Different funders have materially
different rules.
