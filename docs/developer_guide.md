# Developer guide: commands, CI workflows, cloud sessions and hosting

Moved from CLAUDE.md on 2026-11-24, word for word, so that CLAUDE.md stays short. Claude Code loads CLAUDE.md in full
at the start of every session, and Anthropic's guide targets under 200 lines for it, because longer files consume more
context and reduce adherence ([Claude Code memory docs](https://code.claude.com/docs/en/memory)). CLAUDE.md keeps the
rules and points here for the details. Links were rewritten for this folder. Keep this file true from now on, as any
other doc.

## สรุปสำหรับเจ้าของโปรเจกต์

ไฟล์นี้เป็นคู่มือของผู้พัฒนา ย้ายมาจาก CLAUDE.md เพื่อให้ไฟล์นั้นสั้นลง เนื้อหาเหมือนเดิมทุกคำ ส่วนที่คุณใช้มีดังนี้
- **ช่องตรวจที่รันเองทุกครั้งที่ส่งงาน (push และ pull request):** *Core logic tests*, *Service container*, *Tracing check*
  และ *Secret scan* ถ้าเป็นสีเขียวทุกช่องแปลว่าผ่าน ([รายละเอียด](#github-actions))
- **ช่องตรวจที่คุณกดเองได้ (Run workflow):** วัดผลกับ Typhoon, กับ Claude (ต้องมีคีย์ก่อน), กับโมเดลที่รันเอง,
  ด่านสอบ AI ของเราเอง และการจำลองปุ่มอนุมัติเอง บางช่องใช้เวลานานกว่าหนึ่งชั่วโมง
- **Render:** แก้การตั้งค่าใน `render.yaml` ไม่ใช่ในหน้า dashboard ถ้าเพิ่มคีย์ในแท็บ Environment ให้เพิ่มเป็นแถวใหม่
  และอย่าแตะ `NEURON_FLOW_ACCESS_KEY` ([รายละเอียด](#hosting-on-render))

## Commands

```bash
python -m unittest discover -s tests -v        # all tests (the count is in CLAUDE.md §4); CI: Python 3.10 and 3.12
python -m examples.case_triage_demo            # v1 rules, one synthetic case
python -m examples.case_triage_shadow_demo     # v2 shadow mode with the offline mock AI
python -m examples.study_guide_demo            # the study guide's answers to four synthetic requests
python -m examples.intake_route_demo           # the router's answers to five synthetic messages (roadmap 4.2)
python -m app.eval.triage_shadow_eval --compare-with tests/baselines/shadow_eval_mock.json  # scorecard + eval gate
python -m app.eval.study_guide_eval --compare-with tests/baselines/study_guide_eval_mock.json  # study guide's
python -m app.eval.intake_route_eval --compare-with tests/baselines/intake_route_mock.json  # the router's gate
python -m tests.robustness.bench --compare-with tests/baselines/robustness_v1.json  # robustness gate (~25 s)
python -m tests.handoff_check                  # skill handoffs over all 217 triage cases, end to end (~16 s)
python -m app.eval.triage_shadow_eval --golden app/eval/golden/case_triage_autosend_hard_v1.json --out hard.json \
    --compare-with tests/baselines/autosend_hard_mock.json   # the hard auto-send set and its gate
python -m app.eval.autosend_sim --report hard.json --report shadow.json  # simulate the button on saved answers
python -m app.eval.triage_shadow_eval --golden app/eval/golden/case_triage_attention_heldout_v1.json \
    --compare-with tests/baselines/attention_heldout_mock.json   # the held-out attention set and its gate
python -m app.eval.attention_replay --pair old-report.json cases.json  # the "look first" flag before/after signals
python -m tests.open_benchmarks.attention_open_check --cache ~/open-bench-cache --part sealed  # signals on open data (counts)
python -I tests/open_benchmarks/build_sets.py --out open-sets --cache ~/open-bench-cache --check  # open sets (network)
python -m examples.skill_handoff_demo          # one case step by step through the exchange
python -m tests.browser_walk --url http://127.0.0.1:<port> --key <key> --out walk  # the page on a phone (Playwright; CI)
python -m training.check_set                   # the training set: records, manifest, no overlap with any exam set (T2)
python -m training.train_qlora --dry-run       # plan a training round without training (T3; real runs need a GPU, D10)
python -m training.exam compare --baseline reports/r0 --candidate reports/cand  # criteria v1 against round 0 (T4)
NEURON_FLOW_ACCESS_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(24))") python -m app.serve
```

## GitHub Actions

The owner can open these; the first three run on every push and pull request.

- *Core logic tests* (`core-tests.yml`) runs every test on Python 3.10 and 3.12, the demos (the study guide
  demo writes its four answers to the run summary) and both scorecards, then the eval gates: they fail when
  any case answers differently from `tests/baselines/shadow_eval_mock.json` (roadmap 5.2) or
  `tests/baselines/study_guide_eval_mock.json` (roadmap 3.3), and the study guide's also fails when an answer
  has a link outside the library or more than 5 resources. Last, the robustness benchmark (roadmap 5.4) fails when
  any item's outcome or sweep differs from `tests/baselines/robustness_v1.json`; its Thai summary lists the
  open bugs. Then the skill-handoff demo (one case step by step) and the handoff check over every case of the
  three triage sets (ADR-030), which fails on any broken check; both write Thai summaries to the run page.
  Before the study guide's scorecard, the 128 hard auto-send cases run with the mock against
  `tests/baselines/autosend_hard_mock.json`, and the auto-approve simulation replays them with the 61 development
  cases (ADR-031); its Thai summary is on the run page and it fails only if a real job did not wait for a person.
  Before the simulation, the 64 held-out attention cases run with the mock against
  `tests/baselines/attention_heldout_mock.json` (ADR-032); the scorecard on the run page shows how many cases a
  person should see first were raised, and names the misses. The mock AI's `attention` is always `none`, so
  these CI figures are the code's signals alone (ADR-033).
- *Service container* (`service-container.yml`):
  - checks `render.yaml` against Render's schema;
  - builds the same container as Render and submits cases over HTTP;
  - restarts it and checks that nothing was lost;
  - checks that it runs without root and stops cleanly;
  - checks the storage check and readiness (roadmap 1.7): a volume must read `confirmed`, a folder with no disk
    `root_filesystem` and a tmpfs `temporary_filesystem`; Typhoon chosen without a key must give `/healthz` 200,
    `/readyz` 503 `blocked_config` and a case that waits, and the same volume with the mock must work that case;
    the Thai lines are on the run page;
  - fails when a file under `app/` or `neuron_flow/` or in the installed packages, or a module the Runner
    imports, has no bytecode cache in the image or one that does not match its source
    (`.github/scripts/check_image_bytecode.py`, run inside the image; effectiveness plan E1);
  - reports, without gating on a time, how long a process start and the first case after a start take, at
    the runner's full speed and held to 0.1 CPU (an imitation of Render's free instance, not Render). The
    figures are on the run page and in the job log (`bytecode-report`, `first-case` and `image-size` lines);
  - walks the page in a browser on a phone-sized screen (`tests/browser_walk.py`, roadmap 1.8): sign in, send and
    confirm a case, open it from the drawer's "รอรีวิว", approve it, open the linked job, find the decision counted
    in the settings tab, then the same over the API; it fails on a sideways scroll, a script error, a 5xx reply or
    an element it cannot click. Playwright 1.63.0 is installed in that step only, its headless Chromium cached; a
    picture of each screen is in the `browser-walk` artifact and a Thai line per step on the run page.
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
  sessions may need to use Actions instead. CLI artifact downloads can fail because their storage host
  changes from run to run (`productionresultssa<N>.blob.core.windows.net`). On 2026-11-11 the GitHub
  connector downloaded the E2 artifact and supplied a reusable file URL; its ZIP hash was verified and
  all three reports replayed locally. Prefer that supported route when available; otherwise the run page
  records the scorecards and their mistakes.
- *Auto-approve limits (open benchmarks + hard set)* (`autosend-limits.yml`, ADR-031, roadmap 5.6 and 5.9) builds
  the open-benchmark sets from their pinned sources (checked against `tests/open_benchmarks/manifest_v1.json`),
  runs the shadow scorecard on them, the hard auto-send set and the three existing sets (`sets`: `all`, `hard`,
  `open` or `existing`), then the auto-approve simulation on every saved answer. *Run workflow* uses Typhoon by
  default (`TYPHOON_API_KEY`, cases 1 s apart; about 1,800 cases with the held-out attention set and the sealed
  half of the open data, ADR-032); pull requests that change this lane get a run with the mock. This session can build the sets itself: `raw.githubusercontent.com` and MASSIVE's S3 archive
  are reachable from its network, Hugging Face is not.
- *Local open model eval* (`local-model-eval.yml`, ADR-026, roadmap 5.8) runs both scorecards against an
  open-weight model that the job runs itself: llama.cpp's server built from a pinned commit (cached), serving
  Typhoon 2.5 Qwen3 4B from a Hugging Face file checked against its SHA-256 (`.github/scripts/fetch_model.py`),
  on 127.0.0.1 with greedy decoding. No secret; nothing goes to an AI company. Pull requests that change
  `app/llm/`, the workflow or its scripts get a smoke run (5 cases, 5 requests); *Run workflow* runs
  everything. CPU only, so it is slow: the first full run took about 66 minutes, 55 of them the study guide.
  This session cannot reach Hugging Face: the model file's commit, size and SHA-256 are on the run page.
  GitHub's terms allow hosted runners only for building and testing the project, so this lane measures and
  never serves the web page.
- *Training set check* (`training-set.yml`, own-model track T2, ADR-037) runs on every push and pull request that
  changes `training/`, and by hand: it builds the open-benchmark sets and the sealed half, then runs
  `training.check_set` against every exam set, the sealed half as counts only; a Thai table is on the run page.
  Nothing is trained there. The unit tests check the committed exam sets on every push as well.
- *Own model exam* (`own-model-exam.yml`, own-model track T4, ADR-037): *Run workflow* with no candidate examines round 0
  (the local lane's pinned 4B) on six sets, 484 cases, through the real service code; with a candidate (a public
  Hugging Face GGUF pinned by commit and SHA-256) it examines round 0 and then the candidate on the same runner and
  applies criteria v1 (`training/exam.py`). An 8-case probe runs before each exam. Per-case answers are printed as
  `EXAM-CASE` lines in the job log (ids and labels only), which this session can read with
  `gh api repos/<owner>/<repo>/actions/jobs/<id>/logs`. Pull requests that change the exam get 3 cases per set.
  CPU only: a full round 0 is over an hour. No secret; nothing trained or served.
- *Shadow eval with Claude (manual)* and *Study guide eval with Claude (manual)* run the two scorecards
  against real Claude and need the repository secret `ANTHROPIC_API_KEY`.

## Notes for cloud sessions

For sessions on claude.ai/code.

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
- A session outside that environment (a claude.ai project session, 2026-11-24) had neither `python3.10` nor
  `gitleaks`. `uv python install 3.10 --system-certs` installed Python 3.10.20. `go install` could not reach
  `proxy.golang.org`, but gitleaks 8.30.1's release archive from GitHub (`gitleaks_8.30.1_linux_x64.tar.gz`,
  checked against the release's `gitleaks_8.30.1_checksums.txt`) worked.

## Where things are

| Path | What it is |
|---|---|
| `neuron_flow/` | Core (rule 1) |
| `app/domains/case_triage/` | v1 rules, the input contract, the v2 shadow agents and workflow, and the attention signals (`signals.py`, `signals_v2.json`, ADR-032) |
| `app/domains/intake/` | the plain-language router `intake.route.v1` (roadmap 4.2, ADR-039): its input contract and steps (`workflow.py`), its three agents, `understand` (AI), `check` and `respond` (rules) (`agents.py`), its fixed vocabulary (`contracts.py`) and its mock (`mock_answers.py`); it gets the frame as plain data and never imports `app.services` |
| `app/domains/study_guide/` | the study guide: topic catalog and verified resource library (`catalog/*_v1.json`), their checks and hash (`library.py`), the link check (`link_check.py`), and the `study_guide.v1` workflow (`workflow.py`, `agents.py`, `planning.py`, `ai_prompts.py`, `mock_answers.py`); no `.md` files here, because the Render build filter ignores them |
| `app/llm/` | AI gateway, prompt library (prompt + answer schema, one hash), personal-data masking, mock, Claude, Typhoon and local providers (`providers/openai_compat.py` serves OpenAI-format services, Typhoon and a server we run ourselves, and states the answer format in words for both, ADR-022, ADR-026; `providers/_http.py` refuses redirects for every real client) |
| `app/exchange/` | the skill-handoff exchange (ADR-030): the common language (`common.py`, `vocabulary_v2.json`; v2 lets a reviewer approve, ADR-034), translators (`translators/`, one module per skill, outside `app/domains/`), the route table (`routes.py`, `routes_v1.json`) and `exchange.py`, which checks the table at start and prepares each handoff for the queue store |
| `app/eval/` | the two scorecards (triage: 61 labelled cases; study guide: 67 labelled requests), the eval gate's shared code and per-category scores (`common.py`), the rules v1/v2 replay (`rules_comparison.py`) the auto-approve simulation (`autosend_sim.py`, ADR-031: a replay only, never imported by the service) and the attention replay (`attention_replay.py`, ADR-032: the flag before and after the signals on saved answers); `golden/` holds the case sets, among them the 128-case hard auto-send set and the 64-case held-out attention set |
| `app/observability/sentry.py` | Sentry reporting: step failures, degraded AI, Runner recoveries |
| `app/observability/tracing.py`, `job_spans.py` | tracing: the OTLP/JSON exporter with its attribute allow-list, and a finished job's spans (ADR-017) |
| `app/persistence/queue_store.py` | the application queue in its own SQLite file (`<data>/app/queue.sqlite3`, schema 5): jobs, events, the Runner heartbeat, reviews and append-only decisions (with each decision card's open time, `card_open_s`, since schema 5; roadmap 2.10), skill handoffs, personal access tokens (the secret's SHA-256, never the secret; ADR-034), and the store id that shows when the queue started empty |
| `app/services/` | workflow catalog, the frame (`frame.py` + `frame_v1.json`: what the system can do in plain words, roadmap 4.1, ADR-038), admission, Runner with reconciliation, result summaries, queue and run-time figures, review decisions (`reviews.py`), the rules and the AI against people's decisions and reviewer time per group (`review_labels.py`, roadmap 2.8 and 2.10: counts only, nothing reads it to decide), who may call the API and what each role may do (`access.py`: the shared key, personal tokens and the role table, ADR-034) |
| `app/api/`, `app/web/` | standard-library HTTP API and the Thai web page (chat layout with a case / study-question switch, the study guide's layered answer, Flow and Trace, read-only settings); `tests/test_web_page.py` holds the page to its contracts |
| `app/boot.py` | the image's process 1: takes the data folder as root, switches to `neuron`, becomes tini |
| `app/settings.py`, `app/serve.py` | settings from the environment, with the start's storage check from the mount table (roadmap 1.7, ADR-036); the launcher (API + supervised Runner) |
| `Dockerfile`, `render.yaml`, `railway.json` | the container, the Render Blueprint, the Railway config kept for later |
| `training/` | the own-model track (ADR-037, [docs/own_model_plan.md](own_model_plan.md)): `check_set.py` (the training set's record checks, its manifest and the overlap check `overlap-v1` against every exam set), `render.py` (training examples from the service's own request builder), `receipt.py` (recipe checks, the training receipt and the serving contract), `train_qlora.py` (the GPU script; its libraries, pinned in `requirements-train.txt`, only inside its functions), `exam.py` (the exam: six sets, the probe and criteria v1 against round 0), `recipe_v1.json` and `data/triage_train_v1.json` with its manifest (240 synthetic cases with their answers). Never copied into the image and ignored by Render's build filter; nothing in `app/` or `neuron_flow/` imports it (rule 8) |
| `tests/open_benchmarks/` | stage 2 of the benchmarking plan (roadmap 5.6): `build_sets.py` builds the CLINC150, BANKING77, MASSIVE th/en and BIPIA case sets at run time from pinned sources (standard library, run with `python -I`; refuses any SHA-256 it does not expect), `manifest_v1.json` (the sources and every built file's SHA-256; `--check`), `NOTICE.md` (licences), and `attention_open_check.py` (the development and sealed halves of the same sources for the attention signals; the sealed half prints counts only and can be written as a case file at run time). Nothing downloaded is committed |
| `tests/robustness/` | the robustness benchmark (docs/benchmarking.md): the synthetic set, the pinned open extract with its licences (`NOTICE.md`), the runner `bench.py`, the extract builder (`build_open_extract.py verify` re-checks the upstream files) and the 116-case file for live runs |
| `tests/`, `examples/`, `.github/` | tests (`tests/baselines/` holds the eval gate's baseline; `tests/browser_walk.py` is the CI walk of the page on a phone-sized screen, not a unit test), demos and smoke tests, CI (`.github/scripts/` holds the `render.yaml` and trace checks and the image's bytecode-cache check, `.github/otel/` the tracing check's collector; `.github/gitleaks.toml` and `.github/.gitleaksignore` the secret scan's rules and reviewed findings; `.github/ISSUE_TEMPLATE/` the issue templates and `.github/pull_request_template.md` the pull request template, which mirrors §5) |
| `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md` | the community files GitHub's community standards checklist looks for; the code of conduct adopts the Contributor Covenant 2.1 and, since no e-mail address is published, takes reports through the Security tab's private form |
| `.claude/` | the session-start hook for Claude Code cloud sessions |

## Hosting on Render

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
