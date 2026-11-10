# CLAUDE.md — how to work on System Neuron Flow AI

> **สำหรับเจ้าของโปรเจกต์:** Claude Code อ่านไฟล์นี้เองทุกครั้งที่เปิดโปรเจกต์ ไฟล์นี้บอกว่าโปรเจกต์คืออะไร Claude ต้องทำงาน
> และคุยกับคุณอย่างไร มีกติกาอะไรที่ห้ามละเมิด และงานถัดไปคืออะไร ลำดับงานระยะยาวแบบละเอียดอยู่ใน
> [docs/ROADMAP.md](docs/ROADMAP.md)

## 1. The project in one paragraph

`neuron_flow/` (Core) is a small supervised workflow engine. It validates a job spec, runs a static DAG of
trusted agents in bounded child processes, retries, recovers after a crash and writes verified receipts.
`app/` is built on top of it without changing Core. It contains:
- a case-triage domain: keyword rules make the official suggestion, an AI gives a second opinion
  (shadow mode), and a person always decides: since 2026-11-10 on the page's decision card or through
  `POST /v1/reviews/{review_id}/decisions` (roadmap 2.2, 2.4; ADR-027: the owner's shared key is the only
  reviewer credential until per-person tokens, 2.1);
- an AI gateway (an offline mock, Claude, Typhoon: SCB 10X's Thai-first model, free within rate limits;
  ADR-021, or `local`: an open-weight model on a server we run ourselves, today llama.cpp with Typhoon 2.5 4B
  on the GitHub runner; ADR-026);
- triage scorecards on 61 development cases, 116 robustness cases and 40 held-out cases; E2 compares the
  original `keywords-v1` with versioned Thai/English `keywords-v2` using the same saved AI answers;
- Sentry reporting, and tracing to Honeycomb (one trace per case; off until a key is set);
- since round 2, an HTTP API, a durable job queue, a single Runner with crash recovery and a Thai web page,
  shipped as one container for Render;
- a second domain, the study guide (`study_guide.v1`): a versioned topic catalog, a verified resource
  library with a weekly link check, and a five-step workflow that answers a plain-language request with at
  most 5 library resources in study order (roadmap 3.1, 3.2). It ends `COMPLETED` without review (ADR-018).
  The page has a box for it (3.4): a switch above the message box chooses a case or a study question, and a
  question is sent without the confirm card that cases have (ADR-023), then answered in layers.
- a robustness benchmark (`tests/robustness/`, roadmap 5.4; plan in
  [docs/benchmarking.md](docs/benchmarking.md)): 270 hard synthetic edge cases and four pinned open datasets
  (BLNS, JSONTestSuite, CLINC150, BANKING77; ADR-024) through every layer. It is a CI gate on every outcome,
  failures included; its first run found 8 bugs, all fixed in 5.5 (PR #42).

All data is synthetic. Milestones A, A2 and B are done.

Read in this order when you need depth:
1. [docs/ROADMAP.md](docs/ROADMAP.md): what to do next, in order, and how to know each step is done. Its
   effectiveness track (E1 to E6) is written out in [docs/effectiveness_plan.md](docs/effectiveness_plan.md),
   with the measures it follows.
2. [docs/architecture.md](docs/architecture.md): layers, Core constraints, decisions (ADRs), acceptance
   gates and status.
3. [docs/design_philosophy.md](docs/design_philosophy.md): the owner's compass for every feature (mostly Thai).
4. Feature docs: [intake_queue.md](docs/intake_queue.md) (API, queue, Runner, web page, Render setup),
   [case_triage_v2_shadow.md](docs/case_triage_v2_shadow.md) (the AI second opinion),
   [observability_sentry.md](docs/observability_sentry.md),
   [observability_tracing.md](docs/observability_tracing.md) (traces to Honeycomb),
   [study_guide.md](docs/study_guide.md) (the study guide: workflow, scorecard, topic catalog, library, link check).

## 2. Working with the owner (read this first)

- **Roles.** The owner is the tester and the decision maker, not a programmer. You are the developer. You
  design, build, test, fix, open pull requests and keep the docs true.
- **Language.** The owner writes in Thai.
  - Reply in Thai, in everyday words.
  - Explain as a step-by-step flow: first what happens, then what they need to do.
  - Put a technical term in parentheses after the plain word, never on its own.
  - Start with a one-line summary; add detail only when it helps.
  - Code, comments, commit messages and technical docs stay in English. Owner-facing doc sections and the
    web page are in Thai.
- **No local computer.** The owner cannot run code. Never ask them to run a command.
  - Anything that must run happens in your session, in GitHub Actions or on Render.
  - Their part is clicking (GitHub, the Render dashboard, the Claude Console) and trying the web page.
- **Every change ends with a test for the owner.** Say:
  - which page or Actions run to open;
  - what to click or type;
  - what they should see if it works.
- **Questions.** Ask at most one question, and only when the answer changes what you build. Otherwise take
  the safe default, say which one you took, and continue.
- **Owner-only decisions.** Spending money, publishing anything, adding people and touching real personal
  data belong to the owner (see [Owner decisions](docs/ROADMAP.md#owner-decisions)). Prepare the decision
  and the steps, but do not make it.
- **Merging.** Open a PR for every change, and merge only when the owner asks. A merge to `main` that
  changes code redeploys Render, and on the free plan every deploy wipes the queued cases. A merge that
  changes only docs, tests or CI files does not redeploy (the `buildFilter` in `render.yaml`).
- **Public repository (D5).** This repository has been public since 2026-11-08, with its full history.
  Commits, PRs, comments and Actions logs are public: keep personal details,
  account matters and internal notes out of them, and never let a key reach a log.
  - Commit only as `noreply@anthropic.com` (this session's git identity). The `commit-emails` job of *Secret
    scan* fails a pull request whose commits carry any other address than GitHub's or Anthropic's noreply ones.
  - One of the owner's personal addresses is in 53 public commits, mostly merges made on github.com. Never
    write it anywhere. Removing it from the history is owner decision D8 (ROADMAP 7.6); never rewrite or
    force-push `main` without the owner's explicit permission.
- **Honesty about evidence.**
  - Mock-AI scores are not accuracy, and hashes prove bytes, not authorship.
  - The live-model measurements are Typhoon's on the synthetic sets (first runs 2026-11-06,
    `docs/evidence/2026-11-06-first-live-typhoon.md`) and on the 116 robustness edge cases (one run from a
    cloud session, `docs/evidence/2026-11-10-effectiveness-baseline.md`), and the local 4B model's: a smoke run on the first 5
    items of each set, twice, and one full run of both sets (2026-11-08,
    `docs/evidence/2026-11-08-first-local-model-smoke.md`, `docs/evidence/2026-11-08-first-local-model-full.md`).
    There is none for Claude, and no security review or user study yet. A Typhoon or local result describes
    that model only; never present it as another model's, least of all Claude's.
  - Never write a number you did not measure. Record failures as well as successes.
- **The philosophy covers how you talk, too.** Plain language outside, careful work inside, and small
  measured steps instead of perfection. When the owner brings up a technology or a logic system in everyday
  or metaphorical words, follow the first-response rule in design_philosophy.md alongside the work:
  - a few checked study resources;
  - what each one is for;
  - what to study first.

## 3. Rules you must not break

1. **Core stays unchanged.**
   - `neuron_flow/` has changed twice since commit `09100f7`, each with tests: the planned telemetry fix
     (ROADMAP 1.1, PR #21) and `decode()`'s error contract (ADR-025, ROADMAP 5.5, PR #42). No other Core change
     is planned; any new one needs an ADR first.
   - Core never imports `app.*`. Dependencies point one way: interface → services → domain → Core.
2. **Only the Runner opens `Runtime`** (ADR-001). The API and every other process stay away from Core and
   its SQLite files.
3. **Reply `202` only after the queue commit** (ADR-002). Stay on one machine and SQLite (ADR-003,
   ADR-014) until the roadmap says otherwise.
4. **AI proposes, code validates, people decide.**
   - Every AI output passes schema, invariant and policy checks before Core stores it.
   - Nothing is decided automatically. The AI never chooses the queue or approves anything.
   - n8n and MCP clients never decide either.
   - An informational answer that decides nothing about anyone and sends nothing outside (the study guide)
     ends `COMPLETED` without review (ADR-018). Its links come only from the verified library, inserted by
     code. Anything that decides about a person or acts outside still waits for a person.
5. **Trusted, versioned agents** (ADR-005, ADR-011, ADR-015).
   - Agents come from the registry.
   - An agent's version includes provider, model, prompt hash, max_tokens and effort, and is frozen per
     job. A changed prompt or model is a new version.
   - A prompt completed from versioned data (the study guide's catalog) also carries that data's version,
     here the library tag (ADR-019).
   - Shadow triage rules use `triage.classify_rules` with the complete SHA-256 of `keywords_v2.json` in
     the agent version and frozen step params; a list change is a new rules version (E2). The original
     `case_triage.v1` demonstration keeps `triage.classify` and `keywords-v1`.
   - Jobs caught mid-way by a change fail as `configuration_changed`.
6. **Secrets come only from the environment, at call time** (ADR-013).
   - Never put a key in a spec, an output, a log, a fixture, a commit or a Sentry event.
   - Logs and Sentry never carry case text or prompts.
7. **Outside requests name only a `workflow_type`** from the catalog (`app/services/workflows.py`). They
   never name agents, code, paths, params or callbacks.
8. **Standard library first.**
   - Core has no dependencies. The app's only dependency is the optional `sentry-sdk`.
   - A new dependency needs a reason in the PR, should be optional where possible, and is added to the
     `Dockerfile`, `pyproject.toml` and `.claude/hooks/session-start.sh` together.
9. **Synthetic data only.** Open datasets count as synthetic only under ADR-024 (written for the dataset, openly
   licensed, no real people's records, pinned and attributed). Personal data is masked before every AI call (ROADMAP 7.1, `app/llm/redaction.py`),
   and the gateway enforces it (ADR-028): new AI code goes through `structured_answer()` with text from
   `mask()`, never to a provider directly (a static test in `tests/test_redaction.py` checks). The masking is
   pattern-based and misses names without a title, addresses and more. Real data waits
   for the owner's decision D4, after 7.2 and 7.3.
10. **Do not build P2 items early.** That means multi-tenancy, distributed workers, Postgres, object
    storage, SLAs, a hosted dashboard, and DAGs that change shape inside Core.

If a task seems to need breaking a rule:
1. Stop.
2. Write the trade-off in the PR, and as a new ADR in architecture.md §8.
3. Ask the owner, in plain Thai.

## 4. Checking your work

```bash
python -m unittest discover -s tests -v        # all tests (411 on 2026-11-11); CI: Python 3.10 and 3.12
python -m examples.case_triage_demo            # v1 rules, one synthetic case
python -m examples.case_triage_shadow_demo     # v2 shadow mode with the offline mock AI
python -m examples.study_guide_demo            # the study guide's answers to four synthetic requests
python -m app.eval.triage_shadow_eval --compare-with tests/baselines/shadow_eval_mock.json  # scorecard + eval gate
python -m app.eval.study_guide_eval --compare-with tests/baselines/study_guide_eval_mock.json  # study guide's
python -m tests.robustness.bench --compare-with tests/baselines/robustness_v1.json  # robustness gate (~25 s)
NEURON_FLOW_ACCESS_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(24))") python -m app.serve
```

GitHub Actions (the owner can open these; the first three run on every push and pull request):
- *Core logic tests* (`core-tests.yml`) runs every test on Python 3.10 and 3.12, the demos (the study guide
  demo writes its four answers to the run summary) and both scorecards, then the eval gates: they fail when
  any case answers differently from `tests/baselines/shadow_eval_mock.json` (roadmap 5.2) or
  `tests/baselines/study_guide_eval_mock.json` (roadmap 3.3), and the study guide's also fails when an answer
  has a link outside the library or more than 5 resources. Last, the robustness benchmark (roadmap 5.4) fails when
  any item's outcome or sweep differs from `tests/baselines/robustness_v1.json`; its Thai summary lists the
  open bugs.
- *Service container* (`service-container.yml`):
  - checks `render.yaml` against Render's schema;
  - builds the same container as Render and submits cases over HTTP;
  - restarts it and checks that nothing was lost;
  - checks that it runs without root and stops cleanly;
  - fails when a file under `app/` or `neuron_flow/` or in the installed packages, or a module the Runner
    imports, has no bytecode cache in the image or one that does not match its source
    (`.github/scripts/check_image_bytecode.py`, run inside the image; effectiveness plan E1);
  - reports, without gating on a time, how long a process start and the first case after a start take, at
    the runner's full speed and held to 0.1 CPU (an imitation of Render's free instance, not Render). The
    figures are on the run page and in the job log (`bytecode-report`, `first-case` and `image-size` lines).
- *Tracing check* (`tracing-check.yml`) runs the service with tracing sent to the OpenTelemetry Collector
  (`.github/otel/collector.yaml`), submits cases, and checks with `.github/scripts/check_traces.py` that each
  case is one trace with its steps and that no case text or key was sent (roadmap 5.1).
- *Sentry smoke test* checks that error reporting reaches Sentry. It reads the DSN only from the repository
  secret `SENTRY_DSN` and skips with a notice when it is missing (roadmap 7.4).
- *Secret scan* (`secret-scan.yml`) runs gitleaks over every commit of every branch on every push and pull
  request, with the rules in `.github/gitleaks.toml`. Reviewed findings are listed with a reason in
  `.github/.gitleaksignore`; a second pass fails if an entry there is no longer found. Its `commit-emails` job
  (`.github/scripts/check_commit_emails.py`) checks the new commits' author and committer addresses: a pull
  request fails on a personal address, a push only warns (so Render's deploy-after-checks is never blocked),
  and the summary counts the commits in the whole history that carry one (53 on 2026-11-10).
- *Study library link check* (`study-links.yml`) opens every link in the study-guide library every Monday,
  by hand, and on every push or pull request that changes `app/domains/study_guide/`. It fails on a broken
  link, warns on a moved or bot-blocked one, and never edits the library. This session cannot reach most
  of those sites, so read this check's summary instead of fetching the links yourself.
- *Shadow eval with Typhoon (manual)* and *Study guide eval with Typhoon (manual)* run the two scorecards
  against Typhoon (default `typhoon-v2.5-30b-a3b-instruct`) and need the repository secret `TYPHOON_API_KEY` (set by the
  owner on 2026-11-06). The shadow eval's `case_set` can be `robustness_edge_v1` (116 cases),
  `heldout_v1` (40 cases), or `all_e2` (all three triage sets, with the v1/v2 comparison). Typhoon's hosted API is free, rate-limited (about 200 requests a minute, 5 a second)
  and collects usage data, so synthetic data only. Each run first sends one fixed sentence and shows the raw
  reply (`.github/scripts/llm_probe.py`), then paces cases 1 s apart (ADR-021). A session on this
  repository's cloud environment can call Typhoon itself (see the notes for cloud sessions below); other
  sessions cannot reach `api.opentyphoon.ai`, so read the run page instead. No session can download a run's
  artifacts: their storage host changes from run to run (`productionresultssa<N>.blob.core.windows.net`) and
  the network refuses it, so the run page is the record; the scorecards list their mistakes there.
- *Local open model eval* (`local-model-eval.yml`, ADR-026, roadmap 5.8) runs both scorecards against an
  open-weight model that the job runs itself: llama.cpp's server built from a pinned commit (cached), serving
  Typhoon 2.5 Qwen3 4B from a Hugging Face file checked against its SHA-256 (`.github/scripts/fetch_model.py`),
  on 127.0.0.1 with greedy decoding. No secret; nothing goes to an AI company. Pull requests that change
  `app/llm/`, the workflow or its scripts get a smoke run (5 cases, 5 requests); *Run workflow* runs
  everything. CPU only, so it is slow: the first full run took about 66 minutes, 55 of them the study guide.
  This session cannot reach Hugging Face: the model file's commit, size and SHA-256 are on the run page.
  GitHub's terms allow hosted runners only for building and testing the project, so this lane measures and
  never serves the web page.
- *Shadow eval with Claude (manual)* and *Study guide eval with Claude (manual)* run the two scorecards
  against real Claude and need the repository secret `ANTHROPIC_API_KEY`.

Notes for cloud sessions (claude.ai/code):
- The owner's cloud environment for this repository, `System_Neuron_flow_AI` (set up on 2026-11-08), runs a
  setup script whenever a new session's container is built. It installs `sentry-sdk`, Python 3.10
  (`python3.10`, from uv) and gitleaks v8.30.1 (`gitleaks`, built with Go as in *Secret scan*); the image
  already has Python 3.11, 3.12 and 3.13. So before pushing, run the tests with `python3.10` and
  `python3.12` (CI's matrix) and the *Secret scan* command. Each step only warns when it fails, so a session
  still starts: if a tool is missing, tell the owner which one, and propose a fix to the script with the
  environment tools. `.claude/hooks/session-start.sh` still installs `sentry-sdk` if the script did not.
  - The script's output is in the session's `env_manager_log` events (`list_events`).
  - The script runs before the session's proxy and its settings exist (`/etc/profile.d/ccr-agent-proxy-ca.sh`,
    which tells uv to trust the system certificates), so the script passes uv `--system-certs` itself.
  - In the first session (2026-11-08) uv got no Python 3.10 and `--quiet` hid why. Later in that session
    uv's download host `releases.astral.sh` was refused, and GitHub, its fallback, worked once and then
    answered 504. The script and the network were fixed that day. In the next new session (2026-11-09)
    the fixed script had worked: `python3.10` is 3.10.20, `gitleaks` and `sentry-sdk` are there, and the
    tests pass on 3.10 and 3.12.
- That environment's network allows package registries, `releases.astral.sh` (uv's Python downloads, added
  on 2026-11-08), and `api.opentyphoon.ai` because Typhoon's key is saved on it as a network secret
  (2026-11-08). The session's proxy adds the key to each request to that host, so the key never enters the
  session, a log or a file. The app still wants the variable, so give it a placeholder for that one command:

  ```bash
  TYPHOON_API_KEY=proxy-injected NEURON_FLOW_LLM_PROVIDER=typhoon PYTHONPATH=. python3 .github/scripts/llm_probe.py probe.md
  ```

  Then a scorecard the same way, with `--min-interval-s 1` as the manual workflows do. Synthetic data only
  (Typhoon collects usage data), and a live result names Typhoon. Hugging Face, render.com, the study
  library's sites and the artifact storage are refused there.
- There is no Docker daemon. The *Service container* workflow is the container test.
- `gh pr view` and `gh pr checks` use GraphQL, which can return 403 here. Use REST instead, for example
  `gh api repos/narongdetpyou-ux/System_Neuron_flow_AI/pulls/<n>` and `.../commits/<sha>/check-runs`.
- Multiprocessing children cannot import `<stdin>`. Put experiments in a file instead of using
  `python - <<EOF`.
- PyPI may be unreachable. That is one more reason to stay on the standard library.

## 5. Definition of done for a PR

- **Scope.** One topic, on a branch from `main`, with an English title and a description that starts with a
  short Thai summary for the owner.
- **Tests.** The new behaviour has tests, including failure paths: crash, retry, duplicate, bad input and
  missing key. Everything passes locally and in CI.
- **Docs, in the same PR:**
  - the status in architecture.md (§5, §8–§10);
  - the feature doc;
  - the README (test count, docs table);
  - the test count in every place `tests/test_docs_truth.py` lists, and working relative links: that
    test fails CI otherwise (roadmap 1.5);
  - the status table in docs/ROADMAP.md.
  - Anything the owner uses also gets a Thai overview section.
- **Robustness gate.** If a robustness outcome changes on purpose (a fix, a new item, a changed rule), regenerate
  `tests/baselines/robustness_v1.json` (`python -m tests.robustness.bench --write-baseline
  tests/baselines/robustness_v1.json`), and after editing the sets also `--export-golden
  tests/robustness/triage_edge_golden_v1.json`; say in the description which items changed and why.
- **Eval gate.** If the scorecard's per-case answers change on purpose (rules, prompt, model, cases),
  regenerate `tests/baselines/shadow_eval_mock.json` in the same PR
  (`python -m app.eval.triage_shadow_eval --write-baseline tests/baselines/shadow_eval_mock.json`) and say
  why in the description. A prompt or model change also attaches a live run (roadmap 0.3: Typhoon, or Claude after D2).
- **Safety.** No secrets, no real personal data, no unmeasured claims. `tests/test_no_secrets.py` and
  *Secret scan* enforce the first. Never add an entry to `.github/.gitleaksignore` without a reason in the
  file and the owner's knowledge.
- **Owner test.** The PR ends with the owner's test steps, in Thai.

## 6. Where things are

| Path | What it is |
|---|---|
| `neuron_flow/` | Core (rule 1) |
| `app/domains/case_triage/` | v1 rules, the input contract, the v2 shadow agents and workflow |
| `app/domains/study_guide/` | the study guide: topic catalog and verified resource library (`catalog/*_v1.json`), their checks and hash (`library.py`), the link check (`link_check.py`), and the `study_guide.v1` workflow (`workflow.py`, `agents.py`, `planning.py`, `ai_prompts.py`, `mock_answers.py`); no `.md` files here, because the Render build filter ignores them |
| `app/llm/` | AI gateway, prompt library (prompt + answer schema, one hash), personal-data masking, mock, Claude, Typhoon and local providers (`providers/openai_compat.py` serves OpenAI-format services, Typhoon and a server we run ourselves, and states the answer format in words for both, ADR-022, ADR-026; `providers/_http.py` refuses redirects for every real client) |
| `app/eval/` | the two scorecards (triage: 61 labelled cases; study guide: 67 labelled requests) and the eval gate's shared code (`common.py`) |
| `app/observability/sentry.py` | Sentry reporting: step failures, degraded AI, Runner recoveries |
| `app/observability/tracing.py`, `job_spans.py` | tracing: the OTLP/JSON exporter with its attribute allow-list, and a finished job's spans (ADR-017) |
| `app/persistence/queue_store.py` | the application queue in its own SQLite file (`<data>/app/queue.sqlite3`, schema 2): jobs, events, the Runner heartbeat, reviews and append-only decisions, and the store id that shows when the queue started empty |
| `app/services/` | workflow catalog, admission, Runner with reconciliation, result summaries, queue and run-time figures, review decisions (`reviews.py`) |
| `app/api/`, `app/web/` | standard-library HTTP API and the Thai web page (chat layout with a case / study-question switch, the study guide's layered answer, Flow and Trace, read-only settings); `tests/test_web_page.py` holds the page to its contracts |
| `app/boot.py` | the image's process 1: takes the data folder as root, switches to `neuron`, becomes tini |
| `app/settings.py`, `app/serve.py` | settings from the environment; the launcher (API + supervised Runner) |
| `Dockerfile`, `render.yaml`, `railway.json` | the container, the Render Blueprint, the Railway config kept for later |
| `tests/robustness/` | the robustness benchmark (docs/benchmarking.md): the synthetic set, the pinned open extract with its licences (`NOTICE.md`), the runner `bench.py`, the extract builder (`build_open_extract.py verify` re-checks the upstream files) and the 116-case file for live runs |
| `tests/`, `examples/`, `.github/` | tests (`tests/baselines/` holds the eval gate's baseline), demos and smoke tests, CI (`.github/scripts/` holds the `render.yaml` and trace checks and the image's bytecode-cache check, `.github/otel/` the tracing check's collector; `.github/gitleaks.toml` and `.github/.gitleaksignore` the secret scan's rules and reviewed findings) |
| `.claude/` | the session-start hook for Claude Code cloud sessions |

## 7. Hosting (Render)

- **Host.** Render. Railway paused new sign-ups on 22 Oct 2026 after a security incident; `railway.json` is
  kept in case it reopens.
- **`render.yaml` is the source of truth.** It defines one Docker web service, `neuron-flow`:
  - free plan, Singapore;
  - health check at `/healthz`;
  - `main` deploys only after the GitHub checks pass;
  - a merge that changes only files the running service never reads (`*.md`, `docs/`, `tests/`,
    `examples/`, `.github/`, `.claude/`) does not deploy (`buildFilter.ignoredPaths`). The *Service
    container* check fails if a file the image is built from would be ignored; keep it that way when
    adding folders;
  - Render generates `NEURON_FLOW_ACCESS_KEY`.
- **Where to change settings.** Change them in `render.yaml`, not in the dashboard: a Blueprint sync
  overwrites dashboard edits that conflict with the file. Secrets (`ANTHROPIC_API_KEY`, `TYPHOON_API_KEY`,
  `SENTRY_DSN`, `HONEYCOMB_API_KEY`) go in the dashboard's Environment tab, never in a file.
- **When the owner edits the Environment tab,** tell them to add each new secret as a new row and to leave
  `NEURON_FLOW_ACCESS_KEY` alone. On 2026-11-03 it went missing while a key was added: the API answered
  503 to every `/v1` request (`serve: NEURON_FLOW_ACCESS_KEY is missing` in the log) until it was set
  again, and once a Blueprint sync re-created it with a new value (`generateValue: true`), so the key saved
  in the page stopped working. Check the app log after such edits.
- **Honeycomb's Ingest key** is the full 64-character value shown once at creation (key ID followed by the
  secret). The 32-character key ID alone gets 401; the page's tracing panel says so.
- **No `CAP_KILL` on Render.** Root in Render's containers may not signal another user's processes, so
  tini must run as the same user as the service (`app/boot.py`). A root tini logged `[FATAL tini (1)]
  Unexpected error when forwarding signal: 'Operation not permitted'`, and every stop killed the service.
  The *Service container* job runs with `--cap-drop KILL` and fails if process 1 is root or a stop is not
  graceful. Keep both when changing the `Dockerfile`. On Render, stops have been graceful since PR #16
  (`docs/evidence/2026-11-03-render-operations.md`).
- **The image carries its bytecode cache (E1).** The base image has none and the service cannot write one
  (`PYTHONDONTWRITEBYTECODE=1`, a code folder `neuron` cannot write to), so the `Dockerfile` compiles the
  standard library and installed packages after `pip install`, and `neuron_flow/` and `app/` after the last
  `COPY`, with `--invalidation-mode unchecked-hash`. Keep the project's compile step last among the steps
  that change files: an unchecked cache of older source would run the older code. The *Service container*
  job compares every cache file with its source. Keep both when changing the `Dockerfile`.
- **Free plan limits.** The service sleeps after 15 idle minutes and has no disk, so the queue is lost on
  every sleep, restart and deploy. Render also refuses some settings on free web services even though its
  schema allows them, for example a disk and `maxShutdownDelaySeconds`. The *Service container* check
  catches those two. If Render reports another one, remove it from `render.yaml` and add it to that check.
- **Paid upgrade.** The `0.5c-512mb` plan, a 1 GB disk at `/var/data` and `NEURON_FLOW_DATA_DIR` are
  already written in `render.yaml`, commented out. Switching is an owner decision (D1).
- **Render connector.** When it is available, it can list services, deploys, logs, events and metrics, and
  set environment variables. As of 2026-11-01 its `create_web_service` can create a Docker web service.
  It cannot set the health check, the deploy-after-checks trigger, a generated secret or a disk, so prefer
  the Blueprint.

## 8. Status and next step

- **Done and merged:**
  - A: v1 rules.
  - A2: AI gateway, v2 shadow mode, scorecard and Sentry (PR #8, #9).
  - Docs refresh and the design philosophy (PR #10).
  - B: intake API, queue, Runner and web page (PR #11).
  - The Claude Code session hook (PR #12).
  - Render hardening: docs, tests and CI-only merges do not deploy (PR #15) and stops are graceful
    (PR #16); both confirmed on Render (roadmap 0.1, 0.5).
  - CI on the Node 24 action versions (PR #20, roadmap 0.6).
  - Neutral telemetry phase names, the one planned Core change (PR #21, roadmap 1.1).
  - Request ids from the access log to the job record (PR #22, roadmap 1.2).
  - Cancel a job that is still queued, from the API and the page (PR #23, roadmap 1.3).
  - Docs truth checks: links, anchors and stated test counts are tested (PR #24, roadmap 1.5).
  - Queue and run-time figures in `/v1/status` and on the page (PR #26, roadmap 5.3).
  - The eval gate: CI fails when any per-case answer of the mock scorecard changes (PR #27, roadmap 5.2).
  - Personal data masked before every AI call; the AI step records what it masked (PR #28, roadmap 7.1;
    narrowing who can read the AI key is a design note in 7.1, not built).
  - Secret scan of the whole history in CI, and the Sentry DSN only from a repository secret (PR #29,
    roadmap 7.4, the preparation part). On 2026-11-08 the owner chose D5: publish this repository with its
    full history. The history was audited (one known secret, the old DSN; personal e-mail addresses in 51
    commits stay visible by that choice), the 7 run logs that could print the old DSN were deleted, every
    workflow's token is read-only (`tests/test_workflow_permissions.py`), and the README has a section
    for visitors and `SECURITY.md` (PR #44). The same day the owner replaced the Sentry DSN, deleted the
    merged branches and switched the repository to public, with secret scanning, push protection and
    private vulnerability reporting on.
  - Tracing to Honeycomb: one trace per case, checked against the OpenTelemetry Collector in CI (PR #30,
    roadmap 5.1). On since `HONEYCOMB_API_KEY` went into Render; the first trace was seen in Honeycomb on
    2026-11-03 (`docs/evidence/2026-11-03-first-trace-honeycomb.md`). The Honeycomb connector reads it:
    environment `test`, dataset `neuron-flow` (`get_workspace_context` gives the team).
  - The Render service `neuron-flow` exists and is live at https://neuron-flow.onrender.com (free plan,
    first deploy 2026-11-01). Use the Render connector to read its deploys, events and logs; this
    session's network may not reach `onrender.com` or `render.com` directly.
  - The study guide's topic catalog (11 topics) and verified resource library (17 links), with checks, one
    SHA-256 over both files for agent versions, and a weekly link check in CI (PR #32, roadmap 3.1).
  - The `study_guide.v1` workflow: topic detection (AI), at most 5 library resources picked and ordered by
    rules, a plain-language explanation (AI), and a layered answer whose links code inserts; it ends
    `COMPLETED` (ADR-018) and its prompts are completed from the library (ADR-019). Built with the mock AI; first live run with Typhoon in PR #38 (PR #33,
    roadmap 3.2).
  - The study guide's scorecard: 67 synthetic requests (Thai and English, metaphors, out of scope,
    injection), run in CI with the mock as an eval gate that also fails on a link outside the library or more
    than 5 resources; a manual workflow runs it with Claude (PR #34, roadmap 3.3). Mock: topic correct 2/48.
  - A free real model for roadmap 0.3, because the owner's Anthropic account asked for card verification:
    GitHub Models first (ADR-020, PR #35, #36), but GitHub had retired it on 2026-07-30, so the first run got
    only "OK" back; replaced by Typhoon (ADR-021, PR #37), with a connection check on every live run and run
    pages that count why the AI gave no answer.
  - The first live runs, with Typhoon (roadmap 0.3 path A, PR #38; evidence note
    `docs/evidence/2026-11-06-first-live-typhoon.md`). The owner's first run got 0/5 answers: Typhoon
    ignores `response_format` and answered in plain `key: value` lines. The client now also states the
    answer format in words and reads the one JSON object; the format version is part of the agent version
    (ADR-022). On the full synthetic sets: triage AI correct 60/61 in two runs (rules 29/61), study guide
    topic correct 46/48 with 0 of 142 links outside the library. Developer-labelled cases and few runs:
    a first measurement of that model, not accuracy.
  - The robustness benchmark, stage 1 of the 3-stage plan the owner asked for (roadmap 5.4, PR #41, built on
    2026-11-07): 270 synthetic items and BLNS, JSONTestSuite, CLINC150 and BANKING77 (ADR-024), a CI gate on
    every outcome. First run: 206/270 own items pass, 8 bugs (a 500 for huge integers or a lone surrogate, and
    a whole case failing when the AI's text holds a lone surrogate), 45 gaps, 0 of 4,680 sweep checks broken
    (`docs/evidence/2026-11-07-robustness-stage1.md`). The owner checked the run page and asked to merge.
  - The 8 bugs stage 1 found, fixed (roadmap 5.5, PR #42):
    - a number too long to read, or half of an emoji (a lone surrogate), gets 400 instead of 500;
    - AI text holding half of an emoji is cleaned (U+FFFD), so the case still reaches review;
    - Core's `decode()` refuses everything it cannot read with `SpecError` (ADR-025, the second Core change).
    The gate now shows 0 bugs and 215/270 own items passing. Merged on 2026-11-08; after the deploy the
    owner's case on the live page still reached review.
  - The web page's chat layout from the owner's "Nocturne" mockup (PR #18, roadmap 1.6; live and
    owner-tested on 2026-11-03). Parts of the mockup that would break the rules in §3 (key and provider
    fields, editing steps, a "never ask" policy) are shown read-only or left out on purpose; see
    intake_queue.md, "หน้าเว็บ: ใช้อย่างไร".
  - The study guide on the web page (roadmap 3.4, PR #39, merged 2026-11-07): a switch above the box ("เคสลูกค้า" /
    "อยากเรียน"); a question is sent without the confirm card (ADR-023) and answered in layers (summary,
    what it understood with "เข้าใจถูกไหม", where to start and the most important resource; then the study
    steps; then the details); out of scope lists the 11 topics. `/v1/status` gives the question limits, and
    the settings tab explains how to switch the online page to Typhoon or Claude. `tests/test_web_page.py`
    holds the page to its contracts. Zero Core changes, so Phase 3 is built. The owner tried it on the live
    page on 2026-11-08 (with the mock AI) and it passed.
  - A local open-model lane, asked for by the owner on 2026-11-08 (roadmap 5.8, ADR-026, PR #46): the `local`
    provider (OpenAI format, `http://127.0.0.1:8080/v1` by default, no key needed on this machine, a model id
    `<name>:<first 12 hex digits of the file's SHA-256>`), the model fetcher, and the *Local open model eval*
    workflow (llama.cpp from a pinned commit, Typhoon 2.5 Qwen3 4B Q4_K_M on the GitHub runner, the file
    pinned by commit and SHA-256). The PR's smoke runs (first 5 items of each set): the AI answered 5/5 and was
    correct 5/5 in triage (rules 3/5, both rule mistakes raised), topic correct 5/5 with 0 of 10 links outside
    the library, and the connection check got valid JSON at once; the rerun with the pinned file gave the same
    rates and token counts, while the median latency per triage case was 2.7 s on one runner and 6.5 s on
    another (`docs/evidence/2026-11-08-first-local-model-smoke.md`). The page names the provider but the Render
    service has no model server, so the page stays on the mock.
  - The local model's first full run, started by the owner on `main` after the merge (run 42453956630,
    2026-11-08, about 66 minutes; `docs/evidence/2026-11-08-first-local-model-full.md`). Every item answered;
    every triage case and topic step on the first attempt. Triage: rule mistakes raised 32/32 (Typhoon
    32/32), 3 needless raises (Typhoon 1), AI correct 58/61 (Typhoon 60/61). Study guide: topic correct 44/48
    (Typhoon 46/48), all correct 61/67 (Typhoon 62/67), 0 of 142 links outside the library; one injection (`TH-ATK-02`) chose the
    topic it asked for, while the links still came only from the library. All 67 topic answers said `high`
    confidence. Median latency about 7 times Typhoon's API. The owner got the JSON reports from the run's
    artifact, because this session cannot download artifacts.
  - E1 of the effectiveness track, built on 2026-11-10 after the owner said to plan the work and carry it
    out without asking first (PR #60; `docs/evidence/2026-11-10-e1-bytecode-cache.md`). The image had no
    bytecode cache at all (0 of the 141 modules the Runner imports, the standard library included), so every
    process compiled everything it imported at each start. The `Dockerfile` now compiles it once and
    *Service container* requires it. On GitHub's runners, one run each: the first case after a start
    0.989 s before and 0.256 s after; with the container held to 0.1 CPU, 14.4 s before and 3.1 s after.
    **Not measured on Render yet**: after the merge, read the `run` span of the first job after the deploy
    and after one sleep in Honeycomb, and fill in the table at the end of the evidence note (E1, task 4).
  - The answer to the first independent review (2026-11-10, of `main` @ `f38c926`; all four findings, one PR;
    `docs/evidence/2026-11-10-independent-review-response.md`):
    - review decisions (2.2) and the page's decision card and "รอรีวิว" list (2.4), built before 2.1 with the
      owner's shared key as the only reviewer (ADR-027; queue schema 2 with a tested upgrade);
    - the gateway enforces the masking (ADR-028); building it found three inputs where `redact-v1` changed on
      a second pass, two of them letting a glued name or phone number through; `redact-v2` fixes them with no
      change to any scorecard or robustness outcome;
    - retention stated at every write and on the page, which counts the cases lost after a wipe (ADR-029);
    - the `commit-emails` check, and roadmap 7.6 with owner decision D8 for the address already public (a
      local dry run of a rewrite is in the evidence note).
- **Not done yet:**
  - Claude has never been run (D2). Typhoon has run only on the synthetic sets (two full triage runs, one
    full study guide run) and once on the 116 robustness edge cases (2026-11-10: AI correct 104/116, rules
    48/116). The local 4B model has had one full run of each set (2026-11-08) besides the PR's
    two smoke runs.
  - Per-person reviewer identity (2.1), the linked job after an approval (2.3) and the n8n intake (2.5) are not
    built; review decisions are (ADR-027).
  - The live page uses the mock AI unless the owner adds Typhoon (or Claude) in Render's Environment tab
    (roadmap 0.4).
  - The rest of the roadmap is open.
- **Next:** [docs/ROADMAP.md](docs/ROADMAP.md), the first item that is not ✅ and whose needs are met.
  - Waiting on the owner: 0.2 and 1.4 (D1, paid Render plan), 0.3 path B and 0.4 with Claude (D2, Claude
    API key); 0.4 with Typhoon is free but sends what is typed on the page to Typhoon, so it is the owner's
    choice too; an open model behind the page needs a paid machine (D7); the owner test of 2.4 on the live page
    after the merge. D8 is decided (2026-11-10): the e-mail history stays as it is; do not propose a rewrite.
  - **E2 continues in PR #64 (2026-11-11)** from PR #62's held-out-set commit `a30de92`, preserved in
    history before changing any rule. Thai/English rules, versioned keyword data, frozen-job checks,
    integration tests, both regenerated gates and a same-answer v1/v2 comparison are built. The original
    `case_triage.v1` demonstration stays on `keywords-v1`; this replaces PR #62's unbuilt plan to move it too.
    Measurement and gap dispositions: [E2 evidence](docs/evidence/2026-11-11-e2-rules-v2.md).
    The earlier v1 scorecard printed held-out mistakes to the previous developer; disclose that limitation
    and never add a keyword because of a held-out result. A change to the rules after measurement requires
    another version and new evidence. Main has not been merged or deployed by this work.
  - 5.8's first full run is recorded: the owner chooses its branch (not good enough, close or good enough;
    roadmap 5.8, "After the first full run", step 2), then follow it.
  - Buildable now without an owner decision: the rest of 5.5 (decide and fix the stage-1 gaps), 5.6 and 5.7,
    the rest of Phase 2 (2.1 next, then 2.3; 2.2 and 2.4 are built) and Phase 4 (4.1 first; Phase 3, which it
    needs, is built). The rest of 7.1 (who can read the AI key) needs an ADR first.
  - The effectiveness track (2026-11-10, PR #50, [docs/effectiveness_plan.md](docs/effectiveness_plan.md)): E1
    is built (PR #60) and waits for its measurement on Render (9.0 to 10.5 s before); E2 (Thai/English
    rules v2) is implemented in PR #64, with measurement status in its evidence note; E3 (a real model
    behind the page) is the owner's decision; E4 needs an ADR, E5 needs 5.6, E6 needs the owner to read
    each candidate.
  - The owner decides which phase or package comes next; ask before starting one.
- Keep this section and the ROADMAP status table true in every PR.
