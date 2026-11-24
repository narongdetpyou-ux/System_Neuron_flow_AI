# CLAUDE.md — how to work on System Neuron Flow AI

> **สำหรับเจ้าของโปรเจกต์:** Claude Code อ่านไฟล์นี้ทั้งไฟล์ทุกครั้งที่เปิดโปรเจกต์ จึงเก็บไว้สั้น (ไม่เกิน 200 บรรทัดตามที่ Anthropic แนะนำ) มีแค่สิ่งที่ต้องรู้ทุกครั้ง
> ส่วนรายละเอียดอยู่ในเอกสารที่ลิงก์ไว้ ลำดับงานอยู่ใน [docs/ROADMAP.md](docs/ROADMAP.md) และประวัติงานก่อน 24 พ.ย. 2026 อยู่ใน [docs/status_history.md](docs/status_history.md)

## 1. The project in one paragraph

`neuron_flow/` (Core) is a small supervised workflow engine: it validates a job spec, runs a static DAG of trusted
agents in bounded child processes, retries, recovers after a crash and writes verified receipts. `app/` is built on it
without changing Core: case triage (keyword rules suggest, an AI gives a shadow second opinion, a person always
decides) behind an HTTP API, a durable queue, one Runner and a Thai web page on Render, with an AI gateway (mock,
Claude, Typhoon, `local`), the skill-handoff exchange, the study guide (paused) and the own-model track (`training/`).
All data is synthetic; Milestones A, A2 and B are done. Depth: [architecture.md](docs/architecture.md) (code in §7,
ADRs in §8) and [README.md](README.md) (every feature doc, in its docs table).

## 2. Working with the owner (read this first)

- **Roles.** The owner is the tester and the decision maker, not a programmer. You are the developer: you design,
  build, test, fix, open pull requests and keep the docs true.
- **Language.** The owner writes in Thai. Reply in Thai, in everyday words, as a step-by-step flow (first what happens,
  then what they need to do): a one-line summary first, detail only when it helps, and a technical term in parentheses
  after the plain word, never on its own. Code, comments, commit messages and technical docs stay in English;
  owner-facing doc sections and the web page are in Thai.
- **No local computer.** The owner cannot run code: never ask them to run a command. What must run happens in your
  session, in GitHub Actions or on Render; their part is clicking (GitHub, Render, the Claude Console) and the page.
- **Every change ends with a test for the owner:** which page or Actions run to open, what to click or type, and
  what they should see if it works.
- **Anything the owner must check goes in a file, in everyday words** (the owner's rule, 2026-11-22): labels, cases,
  choices in a plan or a comparison become plain Thai tables like the T2 sample (the case's text, then its labels in
  Thai words, never codes alone), written to a file and sent (`SendUserFile`, from the scratchpad). The PR page keeps
  its short Thai summary and test steps only.
- **Questions.** At most one, and only when the answer changes what you build. Otherwise take the safe default, say
  which one you took, and continue.
- **Owner-only decisions:** spending money, publishing anything, adding people and touching real personal data
  ([Owner decisions](docs/ROADMAP.md#owner-decisions)). Prepare the decision and the steps; do not make it.
- **Merging.** Open a PR for every change; merge only when the owner asks. A merge to `main` that changes code
  redeploys Render, and on the free plan every deploy wipes the queued cases. Docs, tests or CI files alone do not
  redeploy (the `buildFilter` in `render.yaml`).
- **Public repository (D5)** since 2026-11-08, with its full history: keep personal details, account matters and
  internal notes out of commits, PRs, comments and Actions logs, and never let a key reach a log. Commit only as
  `noreply@anthropic.com` (*Secret scan*'s `commit-emails` job fails any other address than GitHub's or Anthropic's
  noreply ones). One of the owner's personal addresses is in 53 public commits: never write it anywhere. The owner
  kept that history (D8, ROADMAP 7.6): never rewrite or force-push `main` without a new explicit instruction, and do
  not propose a rewrite.
- **Honesty about evidence.** Mock-AI scores are not accuracy; hashes prove bytes, not authorship. Live-model figures
  exist only for Typhoon (its API) and the local 4B (the GitHub lane), each in a dated note in `docs/evidence/`; none
  for Claude, and no security review or user study yet. A Typhoon or local result describes that model only, never
  another's, least of all Claude's. Never write a number you did not measure; record failures as well as successes.
- **The philosophy covers how you talk, too:** plain language outside, careful work inside, small measured steps
  instead of perfection. When the owner brings up a technology or a logic system in everyday or metaphorical words,
  also give design_philosophy.md's first response: a few checked study resources, what each is for, what to study first.

## 3. Rules you must not break

1. **Core stays unchanged.** `neuron_flow/` has changed twice since commit `09100f7`, each with tests: the telemetry
   fix (ROADMAP 1.1, PR #21) and `decode()`'s error contract (ADR-025, PR #42). No other Core change is planned; any
   new one needs an ADR first. Core never imports `app.*`: interface → services → domain → Core.
2. **Only the Runner opens `Runtime`** (ADR-001). The API and every other process stay away from Core and its SQLite.
3. **Reply `202` only after the queue commit** (ADR-002). Stay on one machine and SQLite (ADR-003, ADR-014) until the
   roadmap says otherwise.
4. **AI proposes, code validates, people decide.**
   - Every AI output passes schema, invariant and policy checks before Core stores it. Nothing is decided
     automatically: the AI never chooses the queue or approves anything; n8n and MCP clients never decide either.
   - The AI's `attention` answer (ADR-033) can only raise a case for the reviewer: it never lowers a priority that
     code set and is never a reason to skip a person.
   - Skills hand work to each other only through the exchange (`app/exchange/`, ADR-030): fixed, versioned routes;
     translators in plain code, never AI; a fact from AI is data and never routes anything; a route-only skill is
     refused at `POST /v1/jobs`. Only the API (a person's request) records decisions inside `app/`; a test checks.
   - An informational answer that decides nothing about anyone and sends nothing outside (the study guide) ends
     `COMPLETED` without review (ADR-018), with links only from the verified library, inserted by code. Anything
     that decides about a person or acts outside still waits for a person.
5. **Trusted, versioned agents** (ADR-005, ADR-011, ADR-015). Agents come from the registry. An agent's version
   includes provider, model, prompt hash, max_tokens and effort, and is frozen per job; a changed prompt or model is a
   new version, and jobs caught mid-way fail as `configuration_changed`.
   - An AI agent's version also names the masking rules (`redact-v3`), the gateway's answer checks
     (`config.ANSWER_CHECKS_VERSION`, ADR-035) and, for Typhoon and the local model, the answer format (ADR-022). Any
     change to what `app/llm/gateway.py` does with a reply is a new checks version: `tests/test_answer_checks_version.py`
     fails until it is named, and a released version's pin is never edited.
   - A prompt completed from versioned data carries that data's version (the study guide's library tag, ADR-019).
   - Shadow rules (`triage.classify_rules`) and attention signals (`triage.screen_signals`) carry the complete
     SHA-256 of `keywords_v2.json` and `signals_v2.json` in the agent version and frozen step params; a list change is
     a new version (E2, ADR-032). The original `case_triage.v1` keeps `triage.classify` and `keywords-v1`.
   - Write phrases only from the hard set and the development half of the open data
     (`python -m tests.open_benchmarks.attention_open_check --part development --show`). Never add a phrase, a keyword
     or a prompt line because of a held-out or sealed result, never print the sealed half's text, and give held-out
     rules results [E2's caveat](docs/evidence/2026-11-11-e2-rules-v2.md).
6. **Secrets come only from the environment, at call time** (ADR-013). Never put a key in a spec, an output, a log, a
   fixture, a commit or a Sentry event. Logs and Sentry never carry case text or prompts.
7. **Outside requests name only a `workflow_type`** from the catalog (`app/services/workflows.py`), never agents,
   code, paths, params or callbacks.
8. **Standard library first.** Core has no dependencies; the app's only one is the optional `sentry-sdk`. Test tools
   only CI needs are installed in their workflow step, never in the image (`pyyaml` and `jsonschema` for the Blueprint
   check, Playwright 1.63.0 for the browser walk); training libraries only where training runs, never in the image,
   the app or the session hook (ADR-037). A new dependency needs a reason in the PR, should be optional where
   possible, and goes into the `Dockerfile`, `pyproject.toml` and `.claude/hooks/session-start.sh` together.
9. **Synthetic data only.** Open datasets count as synthetic only under ADR-024 (made for the dataset, openly licensed,
   no real people's records, pinned and attributed). Personal data is masked before every AI call and the gateway
   enforces it (ADR-028): new AI code goes through `structured_answer()` with text from `mask()`, never to a provider
   directly (`tests/test_redaction.py` checks). The masking (`app/llm/redaction.py`) is pattern-based and misses names
   without a title, addresses and more. Real data waits for D4, after 7.2 and 7.3.
10. **Do not build P2 items early:** multi-tenancy, distributed workers, Postgres, object storage, SLAs, a hosted
    dashboard, and DAGs that change shape inside Core.

If a task seems to need breaking a rule: stop, write the trade-off in the PR and as a new ADR in architecture.md §8,
and ask the owner in plain Thai.

## 4. Checking your work

```bash
python -m unittest discover -s tests -v        # all tests (697 on 2026-11-24); CI: Python 3.10 and 3.12
python -m app.eval.triage_shadow_eval --compare-with tests/baselines/shadow_eval_mock.json  # scorecard + eval gate
python -m tests.robustness.bench --compare-with tests/baselines/robustness_v1.json         # robustness gate (~25 s)
```

Every other command, and what each GitHub Actions workflow checks, is in [developer_guide.md](docs/developer_guide.md).
*Core logic tests*, *Service container*, *Tracing check* and *Secret scan* run on every push and pull request; the
live-model and exam workflows run only by hand. **Cloud sessions** ([notes](docs/developer_guide.md#notes-for-cloud-sessions)):
- Before pushing, run the tests with `python3.10` and `python3.12` and the *Secret scan* command (the owner's
  environment installs them; if one is missing, tell the owner which and propose a fix to its setup script).
- No Docker daemon: *Service container* is the container test. `gh pr view` and `gh pr checks` use GraphQL, which can
  return 403: use REST (`gh api repos/narongdetpyou-ux/System_Neuron_flow_AI/pulls/<n>`). Multiprocessing children
  cannot import `<stdin>`: put experiments in a file. PyPI may be unreachable.
- The proxy adds Typhoon's key to requests to `api.opentyphoon.ai`, so it never enters the session: give the app a
  placeholder (`TYPHOON_API_KEY=proxy-injected NEURON_FLOW_LLM_PROVIDER=typhoon`) and pace cases 1 s apart
  (`--min-interval-s 1`), synthetic data only. Hugging Face, render.com, the study library's sites and the artifact
  storage are refused.

## 5. Definition of done for a PR

- **Scope.** One topic, on a branch from `main`, with an English title and a description that starts with a short
  Thai summary for the owner.
- **Tests.** The new behaviour has tests, including failure paths: crash, retry, duplicate, bad input and missing
  key. Everything passes locally and in CI.
- **Docs, in the same PR:** the status in architecture.md (§5, §8–§10), the feature doc, the README (test count, docs
  table), the ROADMAP status table and change log, and the test count in every place `tests/test_docs_truth.py` lists,
  with working relative links (that test fails CI otherwise). Anything the owner uses also gets a Thai overview.
- **Robustness gate.** If an outcome changes on purpose (a fix, a new item, a changed rule), regenerate
  `tests/baselines/robustness_v1.json` (`python -m tests.robustness.bench --write-baseline <that file>`; after editing
  the sets also `--export-golden tests/robustness/triage_edge_golden_v1.json`) and say which items changed and why.
- **Eval gate.** If per-case answers change on purpose (rules, prompt, model, cases), regenerate
  `tests/baselines/shadow_eval_mock.json` in the same PR (`python -m app.eval.triage_shadow_eval --write-baseline
  <that file>`) and say why. A prompt or model change also attaches a live run (0.3: Typhoon, or Claude after D2);
  measure a prompt wording several times before changing it (5.10).
- **Safety.** No secrets, no real personal data, no unmeasured claims (`tests/test_no_secrets.py` and *Secret scan*
  enforce the first). Never add an entry to `.github/.gitleaksignore` without a reason in it and the owner's knowledge.
- **Training cases** (the owner, 2026-11-24). When a PR adds a triage behaviour or a new kind of case, add synthetic
  training cases for it (that PR or the next), by [own_model_plan.md §13](docs/own_model_plan.md#collecting-training-cases-along-the-way).
- **Owner test.** The PR ends with the owner's test steps, in Thai; material to check goes in a file (§2).

## 6. Where things are

Layout: [architecture.md §7](docs/architecture.md#7-code-organisation) and [every folder](docs/developer_guide.md#where-things-are).
`app/domains/study_guide/` holds no `.md` files (Render's build ignores them); `app/` and Core never import `training/`.

## 7. Hosting (Render)

`neuron-flow` at https://neuron-flow.onrender.com, free plan ([details](docs/developer_guide.md#hosting-on-render)). The
Render connector reads its deploys, events and logs; Honeycomb's, its traces (environment `test`, dataset `neuron-flow`).
- **`render.yaml` is the source of truth:** change settings there, not in the dashboard (a Blueprint sync overwrites
  conflicting edits); `main` deploys only after the GitHub checks pass. Secrets (`ANTHROPIC_API_KEY`,
  `TYPHOON_API_KEY`, `SENTRY_DSN`, `HONEYCOMB_API_KEY`) go only in the dashboard's Environment tab. Files the service
  never reads are in `buildFilter.ignoredPaths`; *Service container* fails if a file the image needs would be ignored.
- **When the owner edits that tab,** tell them to add each new secret as a new row and to leave
  `NEURON_FLOW_ACCESS_KEY` alone, then check the app log: once it went missing, every `/v1` request got 503, and a
  sync re-created it with a new value (`generateValue: true`), so the key saved in the page stopped working.
- **The free plan** sleeps after 15 idle minutes and has no disk: the queue, tokens and decisions go at every sleep,
  restart and deploy (a paid plan and disk are in `render.yaml`, commented out: D1). A setting Render refuses on the
  free plan (a disk, `maxShutdownDelaySeconds`) is removed and added to *Service container*'s check.
- **The `Dockerfile`:** tini runs as the service's user (`app/boot.py`; Render's root has no `CAP_KILL`), and the
  project's bytecode compile stays the last step that changes files (E1). *Service container* checks both.

## 8. Status and next step

Built work is in ROADMAP.md's status tables and change log: keep both true in every PR. This section holds only what
is paused, on hold, waiting and next: change it only when that changes, and keep this file under 200 lines
(`tests/test_docs_truth.py` checks). Its history up to 2026-11-24 is in [status_history.md](docs/status_history.md).
- **Paused or on hold by the owner:**
  - **The study guide (2026-11-11):** no new study-guide work (E4, E6 or changes to `app/domains/study_guide/`) until
    the owner resumes it; its checks keep running.
  - **Own-model training (2026-11-24, D10: not now):** keep using Typhoon's API and collect training cases along the
    way (§5). The future base is Typhoon 2.5 Qwen3 30B-A3B; the 4B stays round 0 and the comparison, and the exam's
    pins stay on it ([own_model_plan.md §13](docs/own_model_plan.md#13-the-owners-decisions-of-2026-11-24)).
  - **The owner's fine-tuned Typhoon 4B on Drive is set aside:** never fetch, share or run it, and do nothing with it
    unless the owner asks again; then first read and follow
    [its record](docs/own_model_plan.md#14-the-owners-set-aside-fine-tune-the-record).
  - **No auto-approve button** exists or is planned (D9); the simulation is a replay only (ADR-031).
- **Waiting on the owner:** D1 (a paid Render plan: 0.2, 1.4, real use of Phase 2), D2 (a Claude key: 0.3 path B,
  0.4 with Claude), 0.4 with Typhoon (free, but what is typed on the page goes to Typhoon), D7 (a paid machine for an
  open model behind the page), 5.8's branch after its first full run, 2.9 (blind labels), H4 (the first new skill),
  D10 (before T5), the *Auto-approve limits* run by hand, and the owner tests still open on the live page (2.4's step
  4, attention 5.10, 2.8's scorecard and 2.10's timed decision).
- **Buildable now without an owner decision:** the rest of 5.5 (NFC, an ADR first), 5.6 and 5.7, the rest of Phase 2
  (2.5 needs D3; 2.6 and 2.7 when needed), H5's trace link, and Phase 4 (4.1 first). The rest of 7.1 (who can read
  the AI key) needs an ADR first.
- **Next:** the owner's order (2026-11-24): 5.5 (its masking gaps: `redact-v3`), then Phase 4 (4.1 → 4.4), then H5.
  After that, the first item in [ROADMAP.md](docs/ROADMAP.md) that is not ✅ and whose needs are met; the owner
  decides which phase or package comes next, so ask before starting one.
