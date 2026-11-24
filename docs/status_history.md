# Status history: CLAUDE.md §8 up to 2026-11-24

This is CLAUDE.md §8 ("Status and next step") as it stood on 2026-11-24. It was moved here word for word when CLAUDE.md
was shortened: the file had grown to 839 lines, 369 of them in that section. It is a record and is no longer updated.
- What is built next goes into [ROADMAP.md](ROADMAP.md): its status tables and its change log.
- The current state is in [CLAUDE.md §8](../CLAUDE.md#8-status-and-next-step): what is paused, on hold, waiting and next.

Two things changed in the move:
- links were rewritten for this folder;
- the record of the owner's set-aside fine-tune moved to
  [own_model_plan.md §14](own_model_plan.md#14-the-owners-set-aside-fine-tune-the-record).

## สรุปสำหรับเจ้าของโปรเจกต์

ไฟล์นี้คือประวัติงานที่เคยอยู่ใน CLAUDE.md หัวข้อ 8 ย้ายมาเก็บไว้เหมือนเดิมทุกคำ ไม่มีอะไรหาย
งานใหม่จากนี้ไปบันทึกในบันทึกการเปลี่ยนแปลง (change log) ท้าย [ROADMAP.md](ROADMAP.md)

## The section as it stood

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
    On Render (2026-11-16, the owner's case, read from Honeycomb): the first job after a free-plan sleep ran in
    3.2 s (`run` 3,158 ms; 9.0 to 10.5 s before), one observation; no case was sent right after a deploy.
  - Personal access tokens and roles (roadmap 2.1, ADR-034), built on 2026-11-16 when the owner said to start
    2.1 right after the merge of PR #71. The shared key stays the owner's bootstrap credential; the owner issues
    tokens (`nf_<id>_<secret>`, shown once) for `reviewer` or `submitter` in the settings tab's "จัดการผู้ใช้" or
    `POST /v1/tokens`, lists and revokes them; the queue database (schema 4) keeps the secret's SHA-256, never the
    secret; every request reads the row again, so a revocation applies at once; a fixed role table is checked on
    every route (403 `forbidden`); decisions record the token id and role; the exchange's `vocabulary-v2` lets a
    reviewer's approval hand on. On Render's free plan the tokens go with the queue at every sleep, restart and
    deploy (they fail closed). Checked by `tests/test_service_access.py`, the page's contract tests, the container
    smoke test (issue, decide, revoke, and the revocation kept across a restart) and a headless-browser walk as
    owner, reviewer and submitter. The owner's test on the live page passed every step on 2026-11-16 (confirmed by
    the owner on 2026-11-19); its steps 4 and 5 also passed 2.4's step 1.
  - The reviewer-label scorecard (roadmap 2.8), built on 2026-11-19 as the next item of Phase 2 whose needs were met,
    after the owner said "ทำต่อ" (continue). `app/services/review_labels.py` reads the newest 500 decided reviews
    in one snapshot (`QueueStore.decided_reviews`) and counts how often the rules' suggestion and the AI's opinion
    named the category the person recorded: one group per proposal version (workflow, rules with the keyword list's
    SHA-256, AI provider, model and prompt hash; never added together), split by Thai text or not, every rate as
    numerator/denominator with a 95% Wilson interval. A rejection without a category is `unlabelled`, never a miss.
    `GET /v1/reviews/scorecard` serves it to the owner and reviewers (403 for a submitter); the settings tab shows it
    in Thai with its limits: the labels lean towards the proposal (the person saw it first; approving as proposed
    keeps the rules' category), the cases are synthetic, the mock's figures are a keyword simulation's, and on the
    free plan the decisions vanish at every sleep, so they cannot add up to D6's evidence without D1. No case text,
    reason or token in the reply; no workflow, agent, translator or the Runner reads it (a test). Checked by
    `tests/test_service_review_labels.py`, the page's contract tests, the container smoke test (before and after the
    restart) and a headless-browser walk as owner, reviewer and submitter.
  - 5.5's invisible-text gaps, fixed on 2026-11-19 after the owner said "ทำต่อ" again: a case summary with bidi
    controls (U+202E and the like) is refused at admission, its minimum length counts only characters that are not
    invisible format characters (Cf), and it needs one letter, digit or sign (`app/domains/case_triage/workflow.py`);
    the gateway removes Cf characters from the AI's free text and refuses a field left empty, so an empty rationale
    is asked once more and then the case goes on with the rules alone (`app/llm/gateway.py`). Zero-width spaces
    inside real Thai text and emoji joined by U+200D are kept. Robustness gate 246/270, 0 bugs, 13 gaps (239 and 20
    before); SYN-E2E-002/003/004/016 now expect `REFUSED`, which the benchmark can express since then. No golden
    case is refused, so every eval baseline is unchanged. The study guide's `message` was left alone (paused).
  - The answer to the quality report of 2026-11-19 (of `main` @ `3a4b97f`, 7 pages in Thai, shared by the owner with
    "read it point by point and plan to start work"; `docs/evidence/2026-11-19-quality-report-response.md`). Every
    point was checked against the code and agrees. Its three code findings (page 5) are fixed in one PR:
    - the gateway's answer checks are part of every AI agent's version (`;checks=answer-checks-v3`, ADR-035) and
      pinned by a hash of 31 fixed replies and 7 stop reasons; reproduced first: an interrupted job resumed under
      other checks finished as `REVIEW_REQUIRED`, and now fails as `configuration_changed`;
    - the Runner records the AI step's version as Core checked it (`result.ai.agent_version`); the reviewer-label
      scorecard groups by it, and a result without one is its own group, shown as "ไม่ทราบรุ่น";
    - a case counts as Thai only when it holds a Thai letter (not ฿, Thai digits or tone marks alone).
    No answer changed: every eval gate and the robustness gate are as before. Page 4's two findings (storage marked
    persistent from the settings alone; `/healthz` 200 while the Runner is `blocked_config`) were reproduced on a
    local service and are roadmap 1.7; the other points became 1.8, 2.9, 2.10 and additions to 1.4, 5.7, 7.2 and 7.5.
  - Roadmap 1.7, the rest of that report's page 4, built on 2026-11-21 after the owner asked to have the next work
    explained ("อธิบายงาน") and approved its plan (ADR-036;
    [evidence](evidence/2026-11-21-readiness-and-storage-check.md)):
    - `app.settings.check_storage` reads `/proc/self/mountinfo` at start; the storage is persistent only when the
      data folder's mount is its own and not `overlay`, `aufs`, `tmpfs`, `ramfs` or `devtmpfs`; `/v1/status` gives
      `storage.check` and `storage.filesystem` (never a path), and the page says why a folder that is set is not
      "ถาวร". Settings built by hand are `not_checked`, never persistent; the test fixture passes a confirmed disk;
    - `GET /readyz` (no key, a code only): 200 `idle` or `running`; 503 `blocked_config`, `starting`, `not_alive` or
      `queue_unavailable`. Only heartbeats written since this API process started count; `serve.main` builds the API
      before it starts the Runner. `/healthz` is unchanged and stays `healthCheckPath`;
    - a Runner blocked by its AI settings sends one Sentry event per start (`report_runner_blocked`, the class name
      only); checked with a stub SDK, since CI has no DSN;
    - on Render's free plan nothing the owner sees changes except the new `/readyz`. No Render disk has been seen yet:
      the first deploy after D1 must show "ถาวร" in the settings tab;
    - merged as PR #76 the same day; the owner then confirmed the owner test on the live page (their screenshot of
      the settings tab after the deploy: storage "ชั่วคราว … (Render แผนฟรี)", the Runner ready).
  - Roadmap 1.8, built on 2026-11-21 after the owner said "ทำขั้น 1.8 ต่อได้เลย": `tests/browser_walk.py` clicks
    through the page like a person with Playwright's "Pixel 7" against a fresh container of the image, at the end of
    the *Service container* job, so a page that cannot be used blocks Render's deploy. It signs in, sends and confirms
    a case, opens it from the drawer's "รอรีวิว", approves it, opens the linked job until it has recorded the
    approval, finds the decision counted in the settings tab, and then checks the same over the API. Every screen:
    no sideways scroll, no script error, no 5xx reply. Pictures in the `browser-walk` artifact. Playwright 1.63.0 is a
    CI-only test dependency (released 2026-09-15; the session's preinstalled browser is the one it expects, so a
    venv with `pip install "playwright==1.63.0"` runs the walk here too). `tests/test_web_page.py` holds the page to
    the ids, actions, classes and texts the walk relies on. Not covered: WebKit and Firefox, the study box, tokens.
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
  - Community files, added on 2026-11-22 after the owner asked why GitHub's community standards checklist was
    incomplete (42%): `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1 by reference), two issue
    templates with a private security link, and a pull request template that mirrors §5. Docs only; it does not
    redeploy. The repository's description is a setting only the owner can fill in (the About box's gear).
    Merged as PR #78 the same day; the owner filled in the description and the checklist is complete.
  - Reviewer time per case (roadmap 2.10), built on 2026-11-22 after the owner asked what came next and chose it among
    three buildable items: the decision card notes when it appeared (`performance.now()`), and the decision carries
    `card_open_s` (0 to 86,400 s, a tenth of a second; measured once per idempotency key, left out of the request
    fingerprint, never shown in a view of a decision). Queue schema 5 adds the column, with a tested 4 → 5 upgrade.
    Each scorecard group has `review_time`: timed and untimed decisions, the median and the 95th percentile by
    nearest rank, overall and by priority; never per person, role or credential. Checked by
    `tests/test_service_review_time.py`, the page's contract tests and the browser walk (run in this session too, with
    a Playwright 1.63.0 venv: the timed decision appears in the settings tab and over the API). Real figures need D3
    and D1.
    Merged as PR #79 the same day at the owner's request.
  - The same day the owner asked whether the system could have an AI of its own that "learns along with developing
    the system", then said to merge 2.10 and write the plan. Written, docs only: [docs/own_model_plan.md](own_model_plan.md),
    roadmap track T1–T6, ADR-037 (proposed) and owner decision D10 (where training runs). Fine-tuning an open-weight
    model in measured rounds (the owner approves each training set by hash; an overlap check keeps every exam set
    out; an exam on the local lane by criteria written first; the owner decides each switch), never a model that
    learns while it serves. Nothing trained or downloaded. Merged as PR #80 the same day; the owner then chose the
    base and round 0: the publisher's 4B that the local lane pins, instead of the owner's fine-tuned file on Drive
    ("too troublesome"), which is set aside. Merged as PR #81.
  - T2 of the own-model track, built on 2026-11-22 after the owner said "เริ่ม T2 ต่อเลย": `training/data/triage_train_v1.json`,
    240 synthetic cases written for training (120 Thai, 120 English; 60 per category; per language 84 ordinary, 10
    security, 10 instruction, 8 distress, 8 legal or privacy), each with the answer `triage_classify_v2` should give, and a
    manifest pinning its SHA-256. `training/check_set.py` checks every record (admission, the case's language, nothing
    left to mask, an answer the gateway accepts unchanged), the manifest and the overlap rule `overlap-v1` (4-character
    pieces; Jaccard >= 0.6, or containment >= 0.9) against every exam set; `tests/test_training_set.py` (25 tests) and
    the *Training set check* workflow run it. The first draft collided with exam texts in 7 cases (rewritten without
    reading the exams); then 0 exact and 0 near, the four open sets and the sealed half included (checked in this
    session). `training/` is in Render's ignored paths and `.dockerignore`, so this merge redeploys once (`render.yaml`
    changed) and later training-data changes do not. ADR-037 is in force from T2. Next in the track: T3 (the recipe,
    needs nothing to write; D10 to run) or T4 (the criteria to confirm).
  - T3, built on 2026-11-22 after the owner dropped the idea of changing Core (Core never touches a model's answers;
    the real risk is training on other text than is served) and said to start: `training/recipe_v1.json`
    (`triage_qlora_v1`: the set by SHA-256, the base `typhoon-ai/typhoon2.5-qwen3-4b` by revision copied by program,
    QLoRA starting values, loss on the answer only, 20 of 240 held out, GGUF Q4_K_M with the lane's llama.cpp pins,
    serving as the lane does), `render.py` (every example from `build_request_body` for `local`; a test compares all
    240 with serving byte for byte), `receipt.py` (receipt, `validate`, `serving_mismatches`) and `train_qlora.py`
    (dry run in CI; transformers 4.51.3, peft 0.15.2, bitsandbytes 0.45.5 and accelerate 1.6.0 pinned in
    `requirements-train.txt`, imported only inside its functions, never in the image). 18 new tests. Nothing trained:
    a real run needs D10, and the pins and the chat-template prefix check are first exercised there. Merged as PR #84.
  - T4, built on 2026-11-22 after the owner said "เริ่ม T4 ต่อเลย": `training/exam.py` (six sets: development 61,
    held-out 40, hard 128, attention 64, robustness edges 116, BIPIA 75; the 8-case probe, A2; digest lines; criteria
    v1 `exam-criteria-v1`) and the *Own model exam* workflow with `.github/scripts/run_exam.sh` (the lane's llama.cpp
    and round 0 pins, kept equal by a test; the recipe's serving flags; the 300 s wait, A3; round 0 and a candidate
    on one runner). 22 tests; the script was run here end to end against a stand-in server that answers like the
    mock. Merged as PR #85.
  - Round 0's first full exam, started by the owner on `main` on 2026-11-23 (run 45080841395, 65 minutes): 484 of 484
    cases answered, the probe 8 of 8; AI correct 58/61 development, 37/40 held-out, 104/128 hard, 57/64 attention,
    98/116 edges and 70/75 BIPIA; `needs_person` raised 38/38 and 32/32, BIPIA attacks raised 51/75, 38 needless
    raises. Read from the log's `EXAM-CASE` lines, recomputed in the session (equal to the printed `EXAM-METRICS`),
    and kept as printed in `docs/evidence/2026-11-23-own-model-round0.json`
    ([evidence](evidence/2026-11-23-own-model-round0.md)). It is the baseline for T5's comparison, which runs
    round 0 again beside the candidate. T5 needs D10.
  - On 2026-11-24 the owner paused training (D10: not now; the resources are not ready), said to keep relying on
    Typhoon's API during development and to build training sets along the way, and chose Typhoon 2.5 Qwen3 30B-A3B
    as the base of a future round. The 4B stays round 0 and the comparison; the exam's pins are unchanged, because
    the 30B (a Q4_K_M file of about 19 GB) does not fit GitHub's free runner (16 GB of memory, 14 GB of SSD). Docs
    only ([decisions](own_model_plan.md#13-the-owners-decisions-of-2026-11-24)).
- **Not done yet:**
  - Claude has never been run (D2). Typhoon has run on the synthetic sets and the 116 robustness edges,
    plus all three E2 triage sets (2026-11-11, 217/217 answered/completed): AI correct 60/61 development,
    103/116 edge and 40/40 held-out. The earlier edge run was 104/116; the E2 rules comparison reuses the
    same answers for v1 and v2, rather than comparing separate model runs. Eight edge cases remain wrong
    for both and unflagged; fewer flags do not fix that risk (E5). The local 4B model has had one full run
    of each set (2026-11-08) besides the PR's two smoke runs, and, as round 0, one exam run of the six triage sets
    with today's prompt (2026-11-23).
  - The auto-approve limits run (2026-11-11, ADR-031) answered the owner's "how far could a button go that sends a
    case without a person?" on paper only: on the 128-case hard set Typhoon said `high` on 122 answers and was
    wrong on 13, 12 of them `high`, so its own confidence cannot carry a button; no policy holds the cases that
    must see a person ([evidence](evidence/2026-11-11-autosend-limits.md)). No real button exists or is planned
    (D9).
  - The n8n intake (2.5) is not built; review decisions (ADR-027), personal tokens and roles (2.1, ADR-034), the
    linked job after an approval (2.3, ADR-030) and the reviewer-label scorecard (2.8) are.
  - The first new skill on the exchange (H4) waits for the owner's choice; the link between two handed-off jobs'
    traces (H5) is not built.
  - The live page uses the mock AI unless the owner adds Typhoon (or Claude) in Render's Environment tab
    (roadmap 0.4).
  - The rest of the roadmap is open.
- **Next:** [docs/ROADMAP.md](ROADMAP.md), the first item that is not ✅ and whose needs are met.
  - **The owner's fine-tuned Typhoon 4B is set aside by the owner.** Its record and the steps before touching it
    again moved to [own_model_plan.md §14](own_model_plan.md#14-the-owners-set-aside-fine-tune-the-record).
  - **Attention was built and measured in PR #67, merged on 2026-11-11** (ADR-032, ADR-033, roadmap 5.10).
    The owner said to plan anew, not from the repository's plan, with one expectation: better effectiveness; after
    the first version (signals v1) the owner said it was not enough and asked for more capability. Built:
    signals v2 (wording from the development half of the open data, measured once on the sealed half) and the
    AI's `attention` flag (prompt `triage_classify_v2`, `shadow-3`). One live Typhoon run of ten sets, 1,780 cases
    from commit `1e5d13c`, every case waiting for a person: `needs_person` raised 38/38 on the hard set (6/38
    before), 32/32 on the developer's held-out set (12/32 before), 183/196 on sealed open security requests
    (labels by the datasets); BIPIA 51/75 (0/75 before; sealed half 14/30). Costs, all recorded: raised cases
    234 → 379 of 1,320, about twice the input tokens, the AI's category right 1,157 → 1,147 of 1,513 (one run
    each), AI flags on 12 of 200 ordinary sealed requests
    ([evidence](evidence/2026-11-11-attention-signals.md)). The first live runs found two prompt defects (an
    attention value written as the category; a worse category on injected instructions), fixed from development
    cases only. Its merge redeployed Render (live at 18:06 UTC that day). The
    page's mock AI always answers `none`: the page gets the AI's flag only with a real model (0.4, the owner's
    choice). Next after it: roadmap 5.10, "Next"; measure a prompt wording several times before changing it.
  - **The auto-approve limits were built in PR #66, merged on 2026-11-11** (ADR-031, roadmap 5.6, 5.9 and the
    first injection measurement of 5.7): the hard set, the open-benchmark builder, the simulation, the CI step with
    the mock, the manual workflow and the first Typhoon run. Left: the owner's run of *Auto-approve limits* by hand
    (not started as of 2026-11-16). Its merge redeployed Render; the service never imports the simulation, so what
    the page does is unchanged.
  - **The skill-handoff exchange was built in PR #65 and merged on 2026-11-11** (ADR-030, roadmap
    H1–H3 and H5's page part). The owner paused new study-guide work, asked for skills that stay separate and pass
    work through a go-between with a translator on the way, then asked for it to be built and shown working, and to
    be tested with a new suite and the existing ones. Built: `app/exchange/`, the route-only `case_triage.v2.apply`
    (roadmap 2.3), queue schema 3 with the `handoffs` ledger, the handoff inside the decision's transaction, the API
    fields and the page. 37 new tests (448 in all); `tests/handoff_check.py` ran all 217 existing triage cases end
    to end with 0 problems; every earlier gate unchanged
    ([evidence](evidence/2026-11-11-skill-handoff.md)). The owner's test on the live page passed on 2026-11-16.
  - Waiting on the owner: 0.2 and 1.4 (D1, paid Render plan), 0.3 path B and 0.4 with Claude (D2, Claude
    API key); 0.4 with Typhoon is free but sends what is typed on the page to Typhoon, so it is the owner's
    choice too; an open model behind the page needs a paid machine (D7); the rest of the owner tests on the live
    page (2.4's step 4, attention 5.10, 2.8's scorecard after its merge, and 2.10's timed decision); the first new skill
    (H4); where our own model is trained and where a 30B exam runs (D10: the owner chose not now on 2026-11-24, so T5
    is paused). The owner's first case since 2026-11-10, on 2026-11-16, passed H3 and 2.4's steps 2 and 3 and
    gave E1's Render figure; the
    same day 2.1's owner test passed every step, 2.4's step 1 with it (confirmed by the owner on 2026-11-19).
    D8 is decided (2026-11-10): the e-mail history stays as it is; do not propose a rewrite.
  - **The study guide is paused (owner, 2026-11-11):** no new study-guide work (E4, E6 or changes to
    `app/domains/study_guide/`) until the owner resumes it; its checks keep running.
  - **E2 is built and measured in PR #64, merged on 2026-11-11**, from PR #62's held-out-set commit `a30de92`, preserved in
    history before changing any rule. Thai/English rules, versioned keyword data, frozen-job checks,
    integration tests, both regenerated gates and a same-answer v1/v2 comparison are built. The original
    `case_triage.v1` demonstration stays on `keywords-v1`; this replaces PR #62's unbuilt plan to move it too.
    Rules correct: 61/61 development, 105/116 edge, 22/40 held-out. Typhoon answered and completed all
    217 cases; no case v1 got right regressed, and code checks passed. The same-answer replay matched the
    saved artifact exactly. Measurement and gap dispositions: [E2 evidence](evidence/2026-11-11-e2-rules-v2.md).
    The earlier v1 scorecard printed held-out mistakes to the previous developer; disclose that limitation
    and never add a keyword because of a held-out result. A change to the rules after measurement requires
    another version and new evidence.
  - 5.8's first full run is recorded: the owner chooses its branch (not good enough, close or good enough;
    roadmap 5.8, "After the first full run", step 2), then follow it.
  - **From the quality report of 2026-11-19: 1.7 and 1.8 are built (2026-11-21), and 2.10 (2026-11-22).** 2.9
    (blind labels) waits for the owner's go-ahead. Never "fix" the report's held-out example `HO-TH-UPL-05` with a
    keyword (rule 5).
  - Buildable now without an owner decision: the rest of 5.5 (the ten masking gaps, which
    need new masking rules, and NFC, which needs an ADR; the invisible-text gaps were fixed on 2026-11-19), 5.6 and
    5.7, the rest of Phase 2 (2.1 to 2.4, 2.8 and 2.10 are built; 2.5 needs D3, 2.6 and 2.7 when needed), H5's trace link,
    and Phase 4 (4.1 first; Phase 3, which it needs, is built). The rest of 7.1 (who can read the AI key) needs an
    ADR first.
  - The effectiveness track (2026-11-10, PR #50, [docs/effectiveness_plan.md](effectiveness_plan.md)): E1
    is built (PR #60) and measured on Render (3.2 s after a sleep, 9.0 to 10.5 s before; its task 5 only if the
    owner still finds the first case slow); E2 (Thai/English
    rules v2) is built and measured in PR #64, merged on 2026-11-11, with results and limits in its evidence note; E3 (a real model
    behind the page) is the owner's decision; E4 and E6 are paused with the study guide; E5 needs 5.6.
  - The owner decides which phase or package comes next; ask before starting one.
