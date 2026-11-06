# Grant diligence: evidence register and eligibility blockers

**Prepared:** 2026-10-31. **Evidence register updated:** 2026-11-03 (`main` @ `0b03735`).
**Internal working reference only.**
The funder notes below are a **snapshot researched on 2026-10-31**. Funding calls, terms and legal
eligibility can change, so recheck every original program page on the day of application.

## Evidence register

| Claim | Source | Confidence / limitation |
|---|---|---|
| Portable Core exists | `neuron_flow/`, root README; source-controlled on GitHub | Verified code, not external production adoption |
| Automated tests pass | 119 tests in `tests/`; green CI on `main` @ `0b03735` (Python 3.10, 3.12): https://github.com/narongdetpyou-ux/System_Neuron_flow_AI/actions/runs/41550257103 | Synthetic tests; not production evidence |
| Architecture documented | `docs/architecture.md` | Core, domains, intake queue, Runner, API and web page implemented; the human-review service (Milestone C) is design only |
| Online service runs | Render free plan since 2026-11-01; `docs/evidence/2026-11-03-render-operations.md` (graceful stops, deploy filter, cold start) | Synthetic data, one owner, no SLA; a free-plan restart loses queued cases |
| Case-triage domain, v1 rules and v2 AI shadow mode | `app/domains/case_triage/`, `examples/`, `tests/test_case_triage*.py` | Synthetic data. The AI path was tested offline with a mock and a fake API server; **the only live runs are a free model's** (Typhoon, 2026-11-06, `docs/evidence/2026-11-06-first-live-typhoon.md`), on developer-labelled synthetic cases; Claude has not been run |
| No Core changes needed for new domain versions | `git diff 09100f7 main -- neuron_flow/` shows only the planned telemetry fix (PR #21, not driven by a domain) | Shows the no-Core-change rule so far; a second unrelated domain is still to come |
| Error monitoring works end to end | Sentry project `neuron-flow-runtime` received CI smoke-test events | Integration check only |
| Measurement harness exists | `app/eval/` scorecard, 61 synthetic labelled cases (EN + TH), shown on the CI run page | Mock scores are inflated by design; no AI accuracy claim |
| Open-source deployment | Repository currently **private** | Not demonstrated. GPL license alone is insufficient to claim public distribution |
| Real user needs / traction | None independently verified | **Missing**; interview real users if applying to adoption-based programs |
| Independent review / security certification | None independently verified | **Missing** |
| Detailed actual project costs | None independently verified | Only illustrative budget |
| Application eligibility / applicant credentials | Not supplied or verified | **Missing**, applicant-specific |
| Prior outside grants / awards | Not documented here | Do not assume any |

## Funder research and current fit

**Sentient Foundation, open-source AGI grant**
- Official: https://sentient.foundation/grants
- Grant track backs open-source researchers/maintainers/public goods, rolling
  application, with distribution, compute, engineering and community support.
- Fit is conditional: demonstrate a specific verifiable *open AI* use case;
  this repo has an optional AI integration (shadow mode), tested offline and
  run against one free live model (Typhoon) on synthetic data only, and it is
  private.
- No award amount, assistance allocation or selection is guaranteed.

**Emergent Ventures, Mercatus Center**
- Official: https://www.mercatus.org/emergent-ventures
- Values high-upside early ideas; the applicant must establish social benefit,
  innovation and why the proposed work needs funding.
- Check current applicant terms, including limits on AI-generated application
  text. Do not submit this AI-assisted document as applicant-authored text if
  the current program disallows it.

**GitHub Secure Open Source Fund**
- Official: https://github.com/open-source/github-secure-open-source-fund
- $10,000 program with specific security education, credits and check-ins.
- Program explicitly requires an **open-source-first project with community
  traction/adoption**, clear governance and GitHub Sponsors-supported region.
- Repo's current private status and lack of verified adoption are blockers;
  it is not an immediate ready-to-submit route.

**NLnet Restack / CodeSupply**
- Official: https://nlnet.nl/restack/ and
  https://nlnet.nl/news/2026/20261020-AI-policy.html
- Restack 2026 call deadline: 2026-11-03 12:00 CET; conditional geographic/
  European-dimension eligibility. Exact grant program rules govern.
- NLnet adopted more stringent Generative AI policy on 2026-10-20.
  Existing AI-assisted development and future AI-written applications need
  explicit compatibility review. Do not submit by assuming eligibility.
- CodeSupply is specifically supply-chain focused; ordinary workflow
  orchestration may not match the call.

**Sequoia OSS Fellowship**
- Official program: https://sequoiacap.com/oss
- Target is maintainers of useful open-source projects with real usage.
  Not an established fit for a private pilot lacking demonstrated adoption.

**Thailand NIA / depa**
- Official portals: https://www.nia.or.th/ and https://www.depa.or.th/
- Program-specific corporate registration, residence, matching costs and
  cohort windows must be checked individually. No current individual
  eligibility is established by this technical repository.

## Required owner decisions / evidence; cannot be auto-completed

1. Identity, residence, age/contractual capacity, bank/payment/tax readiness.
2. Confirm whether public disclosure of the repo is appropriate, including
   rights to third-party code, history, prior secrets, dependency and license.
3. Specify intended users and obtain **actual** feedback; mark all synthetic
   cases as synthetic.
4. Supply real cost quotes, time capacity and funding amount; select one fund
   and align the budget with its eligible expense categories.
5. Check disclosure rules regarding AI-supported development/application
   writing before authoring/submitting an external proposal.
6. Obtain independent external security/reliability findings if making those
   claims. Document any failures as well as positive results.

**Application gate:** until these owner-dependent items are resolved, status
is **PREPARATION**, not `READY_TO_SUBMIT`.
