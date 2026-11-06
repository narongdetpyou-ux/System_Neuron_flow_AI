# CLAUDE.md — how to work on System Neuron Flow AI

> **สำหรับเจ้าของโปรเจกต์:** Claude Code อ่านไฟล์นี้เองทุกครั้งที่เปิดโปรเจกต์ ไฟล์นี้บอกว่าโปรเจกต์คืออะไร Claude ต้องทำงาน
> และคุยกับคุณอย่างไร มีกติกาอะไรที่ห้ามละเมิด และงานถัดไปคืออะไร ลำดับงานระยะยาวแบบละเอียดอยู่ใน
> [docs/ROADMAP.md](docs/ROADMAP.md)

## 1. The project in one paragraph

`neuron_flow/` (Core) is a small supervised workflow engine. It validates a job spec, runs a static DAG of
trusted agents in bounded child processes, retries, recovers after a crash and writes verified receipts.
`app/` is built on top of it without changing Core. It contains:
- a case-triage domain: keyword rules make the official suggestion, an AI gives a second opinion
  (shadow mode), and a person always decides;
- an AI gateway (an offline mock, Claude, or Typhoon: SCB 10X's Thai-first model, free within rate limits;
  ADR-021);
- a scorecard on 61 synthetic cases;
- Sentry reporting, and tracing to Honeycomb (one trace per case; off until a key is set);
- since round 2, an HTTP API, a durable job queue, a single Runner with crash recovery and a Thai web page,
  shipped as one container for Render;
- a second domain, the study guide (`study_guide.v1`): a versioned topic catalog, a verified resource
  library with a weekly link check, and a five-step workflow that answers a plain-language request with at
  most 5 library resources in study order (roadmap 3.1, 3.2). It ends `COMPLETED` without review (ADR-018).
  The API accepts it; the page has no box for it yet (3.4).

All data is synthetic. Milestones A, A2 and B are done.

Read in this order when you need depth:
1. [docs/ROADMAP.md](docs/ROADMAP.md): what to do next, in order, and how to know each step is done.
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
- **Honesty about evidence.**
  - Mock-AI scores are not accuracy, and hashes prove bytes, not authorship.
  - The only live-model measurement is Typhoon's on the synthetic sets (first runs 2026-11-06,
    `docs/evidence/2026-11-06-first-live-typhoon.md`). There is none for Claude, and no security review or
    user study yet. A Typhoon result describes that model only; never present it as Claude's.
  - Never write a number you did not measure. Record failures as well as successes.
- **The philosophy covers how you talk, too.** Plain language outside, careful work inside, and small
  measured steps instead of perfection. When the owner brings up a technology or a logic system in everyday
  or metaphorical words, follow the first-response rule in design_philosophy.md alongside the work:
  - a few checked study resources;
  - what each one is for;
  - what to study first.

## 3. Rules you must not break

1. **Core stays unchanged.**
   - `neuron_flow/` has changed once since commit `09100f7`: the planned telemetry fix (ROADMAP 1.1,
     PR #21), with tests. No other Core change is planned; any new one needs an ADR first.
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
9. **Synthetic data only.** Personal data is masked before every AI call (ROADMAP 7.1, `app/llm/redaction.py`),
   but the masking is pattern-based and misses names without a title, addresses and more. Real data waits
   for the owner's decision D4, after 7.2 and 7.3.
10. **Do not build P2 items early.** That means multi-tenancy, distributed workers, Postgres, object
    storage, SLAs, a hosted dashboard, and DAGs that change shape inside Core.

If a task seems to need breaking a rule:
1. Stop.
2. Write the trade-off in the PR, and as a new ADR in architecture.md §8.
3. Ask the owner, in plain Thai.

## 4. Checking your work

```bash
python -m unittest discover -s tests -v        # all tests (267 on 2026-11-06); Python 3.10–3.13
python -m examples.case_triage_demo            # v1 rules, one synthetic case
python -m examples.case_triage_shadow_demo     # v2 shadow mode with the offline mock AI
python -m examples.study_guide_demo            # the study guide's answers to four synthetic requests
python -m app.eval.triage_shadow_eval --compare-with tests/baselines/shadow_eval_mock.json  # scorecard + eval gate
python -m app.eval.study_guide_eval --compare-with tests/baselines/study_guide_eval_mock.json  # study guide's
NEURON_FLOW_ACCESS_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(24))") python -m app.serve
```

GitHub Actions (the owner can open these; the first three run on every push and pull request):
- *Core logic tests* (`core-tests.yml`) runs every test on Python 3.10 and 3.12, the demos (the study guide
  demo writes its four answers to the run summary) and both scorecards, then the eval gates: they fail when
  any case answers differently from `tests/baselines/shadow_eval_mock.json` (roadmap 5.2) or
  `tests/baselines/study_guide_eval_mock.json` (roadmap 3.3), and the study guide's also fails when an answer
  has a link outside the library or more than 5 resources.
- *Service container* (`service-container.yml`):
  - checks `render.yaml` against Render's schema;
  - builds the same container as Render and submits cases over HTTP;
  - restarts it and checks that nothing was lost;
  - checks that it runs without root and stops cleanly.
- *Tracing check* (`tracing-check.yml`) runs the service with tracing sent to the OpenTelemetry Collector
  (`.github/otel/collector.yaml`), submits cases, and checks with `.github/scripts/check_traces.py` that each
  case is one trace with its steps and that no case text or key was sent (roadmap 5.1).
- *Sentry smoke test* checks that error reporting reaches Sentry. It reads the DSN only from the repository
  secret `SENTRY_DSN` and skips with a notice when it is missing (roadmap 7.4).
- *Secret scan* (`secret-scan.yml`) runs gitleaks over every commit of every branch on every push and pull
  request, with the rules in `.github/gitleaks.toml`. Reviewed findings are listed with a reason in
  `.github/.gitleaksignore`; a second pass fails if an entry there is no longer found.
- *Study library link check* (`study-links.yml`) opens every link in the study-guide library every Monday,
  by hand, and on every push or pull request that changes `app/domains/study_guide/`. It fails on a broken
  link, warns on a moved or bot-blocked one, and never edits the library. This session cannot reach most
  of those sites, so read this check's summary instead of fetching the links yourself.
- *Shadow eval with Typhoon (manual)* and *Study guide eval with Typhoon (manual)* run the two scorecards
  against Typhoon (default `typhoon-v2.5-30b-a3b-instruct`) and need the repository secret `TYPHOON_API_KEY` (set by the
  owner on 2026-11-06). Typhoon's hosted API is free, rate-limited (about 200 requests a minute, 5 a second)
  and collects usage data, so synthetic data only. Each run first sends one fixed sentence and shows the raw
  reply (`.github/scripts/llm_probe.py`), then paces cases 1 s apart (ADR-021). This session cannot reach
  `api.opentyphoon.ai`; read the run page instead. Nor can it download a run's artifacts (their storage
  host is refused), so the run page is the record; the scorecards list their mistakes there.
- *Shadow eval with Claude (manual)* and *Study guide eval with Claude (manual)* run the two scorecards
  against real Claude and need the repository secret `ANTHROPIC_API_KEY`.

Notes for cloud sessions (claude.ai/code):
- `.claude/hooks/session-start.sh` installs `sentry-sdk`; nothing else is needed.
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
| `app/llm/` | AI gateway, prompt library (prompt + answer schema, one hash), personal-data masking, mock, Claude and Typhoon providers (`providers/openai_compat.py` serves OpenAI-format services and states the answer format in words for Typhoon, ADR-022; `providers/_http.py` refuses redirects for both real clients) |
| `app/eval/` | the two scorecards (triage: 61 labelled cases; study guide: 67 labelled requests) and the eval gate's shared code (`common.py`) |
| `app/observability/sentry.py` | Sentry reporting: step failures, degraded AI, Runner recoveries |
| `app/observability/tracing.py`, `job_spans.py` | tracing: the OTLP/JSON exporter with its attribute allow-list, and a finished job's spans (ADR-017) |
| `app/persistence/queue_store.py` | the application queue in its own SQLite file (`<data>/app/queue.sqlite3`) |
| `app/services/` | workflow catalog, admission, Runner with reconciliation, result summaries, queue and run-time figures |
| `app/api/`, `app/web/` | standard-library HTTP API and the Thai web page (chat layout, Flow and Trace, read-only settings) |
| `app/boot.py` | the image's process 1: takes the data folder as root, switches to `neuron`, becomes tini |
| `app/settings.py`, `app/serve.py` | settings from the environment; the launcher (API + supervised Runner) |
| `Dockerfile`, `render.yaml`, `railway.json` | the container, the Render Blueprint, the Railway config kept for later |
| `tests/`, `examples/`, `.github/` | tests (`tests/baselines/` holds the eval gate's baseline), demos and smoke tests, CI (`.github/scripts/` holds the `render.yaml` and trace checks, `.github/otel/` the tracing check's collector; `.github/gitleaks.toml` and `.github/.gitleaksignore` the secret scan's rules and reviewed findings) |
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
    roadmap 7.4, the preparation part; the rest of 7.4 waits for the owner's decision D5).
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
    `COMPLETED` (ADR-018) and its prompts are completed from the library (ADR-019). Mock AI only (PR #33,
    roadmap 3.2).
  - The study guide's scorecard: 67 synthetic requests (Thai and English, metaphors, out of scope,
    injection), run in CI with the mock as an eval gate that also fails on a link outside the library or more
    than 5 resources; a manual workflow runs it with Claude (PR #34, roadmap 3.3). Mock: topic correct 2/48.
  - A free real model for roadmap 0.3, because the owner's Anthropic account asked for card verification:
    GitHub Models first (ADR-020, PR #35, #36), but GitHub had retired it on 2026-07-30, so the first run got
    only "OK" back; replaced by Typhoon (ADR-021, PR #37), with a connection check on every live run and run
    pages that count why the AI gave no answer.
  - The first live runs, with Typhoon (roadmap 0.3 path A, this PR; evidence note
    `docs/evidence/2026-11-06-first-live-typhoon.md`). The owner's first run got 0/5 answers: Typhoon
    ignores `response_format` and answered in plain `key: value` lines. The client now also states the
    answer format in words and reads the one JSON object; the format version is part of the agent version
    (ADR-022). On the full synthetic sets: triage AI correct 60/61 in two runs (rules 29/61), study guide
    topic correct 46/48 with 0 of 142 links outside the library. Developer-labelled cases and few runs:
    a first measurement of that model, not accuracy.
  - The web page's chat layout from the owner's "Nocturne" mockup (PR #18, roadmap 1.6; live and
    owner-tested on 2026-11-03). Parts of the mockup that would break the rules in §3 (key and provider
    fields, editing steps, a "never ask" policy) are shown read-only or left out on purpose; see
    intake_queue.md, "หน้าเว็บ: ใช้อย่างไร".
- **Not done yet:**
  - Claude has never been run (D2). Typhoon has run only on the synthetic sets (two full triage runs, one
    full study guide run).
  - Review decisions and per-person identity (Milestone C) are not built.
  - The study guide's page (roadmap 3.4) is not built.
  - The rest of the roadmap is open.
- **Next:** [docs/ROADMAP.md](docs/ROADMAP.md), the first item that is not ✅ and whose needs are met.
  - Waiting on the owner: 0.2 and 1.4 (D1, paid Render plan), 0.3 path B and 0.4 with Claude (D2, Claude
    API key).
  - Buildable now without an owner decision: Phase 3, 3.4 next (the owner chose Phase 3 before Phase 2 on
    2026-11-05), and Phase 2 (2.1 first). The rest of 7.1 (who can read the AI key) needs an ADR first.
  - The owner decides which phase comes next; ask before starting a new phase.
- Keep this section and the ROADMAP status table true in every PR.
