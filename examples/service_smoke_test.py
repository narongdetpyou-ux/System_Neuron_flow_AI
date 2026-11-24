"""Check a running Neuron Flow service from the outside, over HTTP (standard library only).

CI runs it against the Docker container; you can point it at the online service too:

    python -m examples.service_smoke_test --url https://<your-service>.onrender.com --key <access key>

First run: read the frame (roadmap 4.1), ask the router (4.2), submit a case, check duplicates and conflicts, wait for the result, approve a case and follow its
handoff, issue a reviewer token, decide with it and revoke it (roadmap 2.1), check that the scorecard counts both
decisions against the rules and the AI (roadmap 2.8), and save the job and token ids.
With ``--after-restart``: check that the saved job is still there, that the revoked token is still revoked, that the
scorecard still counts both decisions and that new work still runs.
With ``--first-case-only``: submit one case to a service that has just started and report how long it
took (effectiveness plan E1). That mode reports and never fails on a time or on the case's outcome.
Storage and readiness, checked rather than assumed (roadmap 1.7):
* ``--expect-storage CHECK`` makes the first run and ``--after-restart`` also check what the start found about the
  data folder (``confirmed`` with a volume);
* ``--storage-check CHECK`` only checks that, and what a new case's reply says about how long it is kept;
* ``--blocked`` expects a Runner whose AI settings cannot work: ``/healthz`` 200, ``/readyz`` 503 ``blocked_config``, a
  case still admitted and waiting; ``--after-fix`` then expects ``/readyz`` 200 and that case worked.
Every run except ``--blocked`` and ``--first-case-only`` also waits for ``/readyz`` to answer 200 before it starts.
It only uses synthetic text, and it never prints the access key.
"""

import argparse
import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request
import uuid

TERMINAL = {"REVIEW_REQUIRED", "COMPLETED", "FAILED", "DELIVERY_FAILED"}
STORAGE_CHECKS = ("confirmed", "root_filesystem", "temporary_filesystem", "not_configured")
# What the owner reads on the run page about each storage check (Thai).
STORAGE_WORDS = {"confirmed": "ถาวร", "root_filesystem": "ชั่วคราว (โฟลเดอร์อยู่ในตัวระบบเอง ไม่ใช่ดิสก์ที่ต่อแยก)",
                 "temporary_filesystem": "ชั่วคราว (โฟลเดอร์อยู่บนพื้นที่ในหน่วยความจำ)",
                 "not_configured": "ชั่วคราว (ไม่ได้ตั้งที่เก็บข้อมูล)"}
LOST_ON = ["sleep", "restart", "deploy"]


class Client:
    def __init__(self, url, key):
        self.url, self.key = url.rstrip("/"), key

    def call(self, method, path, body=None, *, key=True):
        headers = {"Accept": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {self.key}"
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self.url + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as exc:
            with exc:
                raw, status = exc.read(), exc.code
        try:
            return status, json.loads(raw) if raw else {}
        except ValueError:
            return status, {"raw": raw[:200].decode("utf-8", "replace")}


def check(condition, message):
    if not condition:
        raise SystemExit(f"FAILED: {message}")
    print(f"ok   {message}")


def wait_until_healthy(client, timeout_s):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            status, _ = client.call("GET", "/healthz", key=False)
            if status == 200:
                return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(1)
    raise SystemExit(f"FAILED: the service did not become healthy in {timeout_s}s")


def wait_for_result(client, job_id, timeout_s):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status, job = client.call("GET", f"/v1/jobs/{job_id}")
        if status == 200 and job["status"] in TERMINAL:
            return job
        time.sleep(0.5)
    raise SystemExit(f"FAILED: job {job_id} did not finish in {timeout_s}s")


def wait_for_runner(client, timeout_s):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status, info = client.call("GET", "/v1/status")
        if status == 200 and info["runner"]["alive"]:
            return info
        time.sleep(1)
    raise SystemExit(f"FAILED: the Runner did not report alive in {timeout_s}s")


def wait_for_ready(client, timeout_s):
    """``/readyz`` (roadmap 1.7, no key): wait until it answers 200, that is until the Runner can work cases."""
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        try:
            last = client.call("GET", "/readyz", key=False)
            if last[0] == 200:
                check(last[1].get("ok") is True and last[1].get("state") in ("idle", "running"),
                      f"/readyz answers 200 ({last[1].get('state')})")
                return last[1]
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.5)
    raise SystemExit(f"FAILED: /readyz did not answer 200 in {timeout_s}s (last: {last})")


def storage_is(client, expected):
    """What the start found about the data folder (roadmap 1.7): persistent only when ``confirmed``."""
    status, info = client.call("GET", "/v1/status")
    storage = info.get("storage") or {}
    persistent = expected == "confirmed"
    check(status == 200 and storage.get("check") == expected and storage.get("persistent") is persistent,
          f"the storage check at start found {expected}, so persistent is {persistent}"
          f" (filesystem: {storage.get('filesystem')})")
    return storage


def storage_line(label, expected, storage):
    """One Thai line for the run page about what the storage check found."""
    return (f"- {label}: ระบบเรียกที่เก็บข้อมูลว่า **{STORAGE_WORDS[expected]}** (ผลตรวจ `{expected}`,"
            f" ระบบไฟล์ `{storage.get('filesystem')}`) ✓")


def finished_v2_jobs(client):
    """How many finished case_triage.v2 jobs the status figures count, if they also carry a run time."""
    status, info = client.call("GET", "/v1/status")
    timing = ((info.get("metrics") or {}).get("workflows") or {}).get("case_triage.v2") or {}
    run = timing.get("run_s") or {}
    return timing.get("jobs", 0) if status == 200 and run.get("max", -1) >= 0 else 0


def run_time(client, workflow_type="case_triage.v2"):
    """The status figures' queue wait and run time for a workflow type: ``(wait_s, run_s)``, the longest
    of each, which is the first job's while it is the only one. ``None`` where there is no figure."""
    status, info = client.call("GET", "/v1/status")
    timing = ((info.get("metrics") or {}).get("workflows") or {}).get(workflow_type) or {}
    return ((timing.get("wait_s") or {}).get("max"), (timing.get("run_s") or {}).get("max"))


def first_case_line(label, outcome, wait_s, run_s):
    """One line for the job summary (Thai, for the owner) about the first case after a start."""
    took = "ไม่มีตัวเลข" if run_s is None else f"{run_s:.1f} วินาที"
    waited = "" if wait_s is None else f" (รอในคิวก่อนเริ่ม {wait_s:.1f} วินาที)"
    return f"- เคสแรกหลังบริการเริ่มทำงาน — {label}: ใช้เวลา **{took}**{waited} ผลลัพธ์ `{outcome}`"


def write_summary(path, line):
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def first_case_only(client, timeout_s, label, summary):
    """Time the first case after a start. A report: it does not fail on the time or on the outcome."""
    outcome, wait_s, run_s = "ไม่เสร็จภายในเวลาที่รอ", None, None
    try:
        wait_for_runner(client, timeout_s)
        body = {"workflow_type": "case_triage.v2", "idempotency_key": f"first-case-{uuid.uuid4()}",
                "input": {"case_id": "SMOKE-FIRST-01", "summary": "I cannot sign in to my account"}}
        status, job = client.call("POST", "/v1/jobs", body)
        if status == 202:
            outcome = wait_for_result(client, job["job_id"], timeout_s)["status"]
            wait_s, run_s = run_time(client)
        else:
            outcome = f"HTTP {status}"
    except SystemExit as exc:  # a wait ran out; say so and keep the report
        print(f"::warning::first case ({label}): {exc}")
    if outcome != "REVIEW_REQUIRED":
        print(f"::warning::first case ({label}) ended as {outcome}, not REVIEW_REQUIRED")
    line = first_case_line(label, outcome, wait_s, run_s)
    print(line)
    print("first-case " + json.dumps({"label": label, "outcome": outcome, "wait_s": wait_s, "run_s": run_s}))
    write_summary(summary, line)


def first_run(client, state_file, timeout_s, summary=None, expect_storage=None):
    status, _ = client.call("GET", "/", key=False)
    check(status == 200, "the web page loads")
    status, _ = client.call("GET", "/v1/status", key=False)
    check(status == 401, "the API refuses requests without the access key")
    info = wait_for_runner(client, timeout_s)
    print(f"     ai={info['ai']['provider']}/{info['ai']['model']} storage={info['storage']['kind']}")
    wait_for_ready(client, timeout_s)
    if expect_storage:
        storage_is(client, expect_storage)
    status, frame = client.call("GET", "/v1/frame")
    check(status == 200 and str(frame.get("frame_version", "")).startswith("frame-v1@sha256:")
          and [task.get("id") for task in frame.get("tasks") or []] == ["case_triage", "study_guide"],
          "the frame lists what the system can do: 2 tasks in plain words (roadmap 4.1)")
    router_reads(client, timeout_s)
    key = f"smoke-{uuid.uuid4()}"
    body = {"workflow_type": "case_triage.v2", "idempotency_key": key,
            "input": {"case_id": "SMOKE-TH-01", "summary": "อัปโหลดไฟล์แนบไม่ได้ ค้างที่ 99%"}}
    status, job = client.call("POST", "/v1/jobs", body)
    check(status == 202 and job.get("status") == "QUEUED", "a new case is admitted (202 QUEUED)")
    status, again = client.call("POST", "/v1/jobs", body)
    check(status == 200 and again.get("job_id") == job["job_id"], "the same request again returns the same job (200)")
    changed = dict(body, input={"case_id": "SMOKE-TH-01", "summary": "a different problem altogether"})
    status, conflict = client.call("POST", "/v1/jobs", changed)
    check(status == 409 and conflict.get("error") == "idempotency_conflict", "the same key with other text is a conflict (409)")
    status, invalid = client.call("POST", "/v1/jobs", dict(body, idempotency_key=key + "-x",
                                                           input={"case_id": "SMOKE-2", "summary": "short"}))
    check(status == 400 and invalid.get("error") == "invalid_input", "invalid input is refused (400)")
    result = wait_for_result(client, job["job_id"], timeout_s)
    review = (result.get("result") or {}).get("review") or {}
    check(result["status"] == "REVIEW_REQUIRED", "the Runner finished the case, waiting for a person")
    check(review.get("decision") == "PENDING_HUMAN_REVIEW", "the AI never decides (PENDING_HUMAN_REVIEW)")
    check((review.get("suggested_queue"), review.get("agreement"), review.get("review_priority"))
          == ("upload_review", "agree", "normal"), "Thai upload rules agree with the mock without a needless raise")
    status, events = client.call("GET", f"/v1/jobs/{job['job_id']}/events?limit=100")
    kinds = [event["kind"] for event in events.get("events", [])]
    check(kinds[:2] == ["job.queued", "job.claimed"] and kinds[-1] == "job.review_required", "the job history is complete")
    check(finished_v2_jobs(client) >= 1, "the status figures count the finished case and its run time (roadmap 5.3)")
    # The first case after a start is the slow one (effectiveness plan E1). Reported, never gated.
    wait_s, run_s = run_time(client)
    print(f"     first case after the start: run {run_s} s, queue wait {wait_s} s")
    write_summary(summary, first_case_line("ความเร็วเต็มของเครื่อง GitHub", result["status"], wait_s, run_s))
    if state_file:
        Path(state_file).write_text(json.dumps({"job_id": job["job_id"]}), encoding="utf-8")
    # Whole-word rules reject the city name; the unchanged substring mock mistakes it for billing.
    disagreement = {"workflow_type": "case_triage.v2", "idempotency_key": f"smoke-{uuid.uuid4()}",
                    "input": {"case_id": "SMOKE-DISAGREE-01",
                              "summary": "Please add dark mode for users in Billings."}}
    status, mismatch = client.call("POST", "/v1/jobs", disagreement)
    check(status == 202, "a case with a real rules/mock disagreement is admitted")
    mismatched = wait_for_result(client, mismatch["job_id"], timeout_s)
    mismatch_review = (mismatched.get("result") or {}).get("review") or {}
    check(mismatched["status"] == "REVIEW_REQUIRED"
          and (mismatch_review.get("suggested_queue"), mismatch_review.get("agreement"),
               mismatch_review.get("review_priority"), mismatch_review.get("decision"))
          == ("general_review", "disagree", "elevated", "PENDING_HUMAN_REVIEW"),
          "a real rules/mock disagreement is still raised and waits for a person")
    applied = approval_hands_on(client, mismatch["job_id"], timeout_s)
    token_id = personal_tokens(client, timeout_s)
    reviewer_labels(client, "after the two decisions")
    if state_file:  # ids only: the token itself is never written down or printed
        Path(state_file).write_text(json.dumps({"job_id": job["job_id"], "apply_job_id": applied,
                                                "token_id": token_id}), encoding="utf-8")


def router_reads(client, timeout_s):
    """Roadmap 4.2 (ADR-039): a plain-language message to the router ends COMPLETED with a proposal of the case task in
    the person's own words, and creates no other job: a person confirms first."""
    text = "ลูกค้าบอกว่าอัปโหลดไฟล์แนบไม่ได้ ค้างที่ 99%"
    _, before = client.call("GET", "/v1/jobs?limit=100")
    status, routed = client.call("POST", "/v1/jobs", {"workflow_type": "intake.route.v1",
                                                     "idempotency_key": f"smoke-route-{uuid.uuid4()}",
                                                     "input": {"message": text}})
    check(status == 202, "a plain-language message is admitted to the router (roadmap 4.2)")
    answered = wait_for_result(client, routed["job_id"], timeout_s)
    reply = (answered.get("result") or {}).get("output") or {}
    _, after = client.call("GET", "/v1/jobs?limit=100")
    check(answered["status"] == "COMPLETED" and answered.get("human_review") is None
          and (reply.get("kind"), reply.get("task"), reply.get("input")) == ("proposal", "case_triage", {"summary": text})
          and len(after.get("jobs", [])) == len(before.get("jobs", [])) + 1,
          "the router proposes the case task in the person's own words and creates no job itself (roadmap 4.2)")


def personal_tokens(client, timeout_s):
    """Roadmap 2.1 (ADR-034): the owner issues a reviewer token, the reviewer decides with it, the owner revokes it."""
    status, issued = client.call("POST", "/v1/tokens", {"display_name": "smoke reviewer", "role": "reviewer"})
    check(status == 201 and issued.get("shown_once") is True and str(issued.get("token", "")).startswith("nf_"),
          "the owner issues a reviewer token, shown once")
    reviewer = Client(client.url, issued["token"])
    status, me = reviewer.call("GET", "/v1/me")
    check(status == 200 and me.get("role") == "reviewer" and me["can"]["review"] and not me["can"]["submit"],
          "the token signs in as a reviewer")
    body = {"workflow_type": "case_triage.v2", "idempotency_key": f"smoke-{uuid.uuid4()}",
            "input": {"case_id": "SMOKE-TOKEN-01", "summary": "I was charged twice this month, please refund"}}
    status, refused = reviewer.call("POST", "/v1/jobs", body)
    check(status == 403 and refused.get("error") == "forbidden", "a reviewer's token cannot send cases (403)")
    status, job = client.call("POST", "/v1/jobs", body)
    waiting = wait_for_result(client, job["job_id"], timeout_s)
    check(waiting["status"] == "REVIEW_REQUIRED", "the owner's case waits for a person")
    decision = {"decision": "APPROVE", "reason": "smoke test: approved by a reviewer token", "expected_version": 1,
                "idempotency_key": f"smoke-decide-{uuid.uuid4()}"}
    status, decided = reviewer.call("POST", f"/v1/reviews/rev_{job['job_id'][len('job_'):]}/decisions", decision)
    who = (decided.get("decision") or {}).get("reviewer") or {}
    check(status == 201 and (who.get("role"), who.get("token_id")) == ("reviewer", issued["token_info"]["token_id"])
          and [h.get("state") for h in decided.get("handoffs") or []] == ["STARTED"],
          "the reviewer's decision records the token and hands on like the owner's")
    token_id = issued["token_info"]["token_id"]
    status, revoked = client.call("POST", f"/v1/tokens/{token_id}/revoke", {})
    check(status == 200 and revoked.get("changed") is True, "the owner revokes the token")
    status, _ = reviewer.call("GET", "/v1/me")
    check(status == 401, "the revoked token is refused at once (401)")
    return token_id


def reviewer_labels(client, when):
    """Roadmap 2.8: the two decisions of the first run are counted against the rules and the AI (counts only).

    The approval in ``approval_hands_on`` keeps the rules' "other" where the mock said billing; the reviewer's approval
    in ``personal_tokens`` keeps billing, where both agreed. So: 2 labels, rules 2 of 2, the mock 1 of 2."""
    status, card = client.call("GET", "/v1/reviews/scorecard")
    totals, groups = card.get("totals") or {}, card.get("groups") or []
    group = groups[0] if len(groups) == 1 else {}
    figures = [(group.get(key) or {}).get(part) for key in ("rules_match", "ai_match") for part in ("numerator", "denominator")]
    check(status == 200 and (totals.get("decided"), totals.get("labelled")) == (2, 2) and figures == [2, 2, 1, 2]
          and (group.get("ai") or {}).get("simulated") is True
          # One AI version, recorded with each result by the Runner (ADR-035), the gateway's checks included.
          and (group.get("ai") or {}).get("version_known") is True
          and ";checks=" in str((group.get("ai") or {}).get("agent_version"))
          and group.get("when_disagreeing") == {"total": 1, "ai_match": 0, "rules_match": 1, "neither": 0},
          f"the scorecard counts both decisions against the rules and the mock AI, one AI version ({when})")


def approval_hands_on(client, job_id, timeout_s):
    """Skill handoff (ADR-030): an approval starts exactly one apply job, which records it with a Core receipt."""
    decision = {"decision": "APPROVE", "final_category": "other", "reason": "smoke test: approved as other",
                "expected_version": 1, "idempotency_key": f"smoke-decide-{uuid.uuid4()}"}
    status, decided = client.call("POST", f"/v1/reviews/rev_{job_id[len('job_'):]}/decisions", decision)
    handoffs = decided.get("handoffs") or []
    check(status == 201 and [h.get("state") for h in handoffs] == ["STARTED"],
          "an approval hands the case on through the exchange (one STARTED handoff)")
    status, again = client.call("POST", f"/v1/reviews/rev_{job_id[len('job_'):]}/decisions", decision)
    check(status == 200 and again.get("handoffs") == handoffs, "the same click again hands on nothing more")
    applied = wait_for_result(client, handoffs[0]["target_job_id"], timeout_s)
    record = (applied.get("result") or {}).get("output") or {}
    check(applied["status"] == "COMPLETED" and record.get("final_queue") == "general_review"
          and record.get("decision_id") == decided["decision"]["decision_id"]
          and len(((applied.get("result") or {}).get("receipt") or {}).get("sha256", "")) == 64,
          "the apply job recorded the approval with a Core receipt")
    status, forged = client.call("POST", "/v1/jobs", {"workflow_type": "case_triage.v2.apply",
                                                      "idempotency_key": f"smoke-{uuid.uuid4()}",
                                                      "input": applied.get("input")})
    check(status == 400 and forged.get("error") == "unknown_workflow_type", "nobody can start the apply skill directly")
    return applied["job_id"]


def storage_only(client, expected, timeout_s, summary, label):
    """Roadmap 1.7: what the start found about the data folder, and what a new case's reply says about it."""
    wait_for_runner(client, timeout_s)
    wait_for_ready(client, timeout_s)
    storage = storage_is(client, expected)
    persistent = expected == "confirmed"
    body = {"workflow_type": "case_triage.v2", "idempotency_key": f"smoke-{uuid.uuid4()}",
            "input": {"case_id": "SMOKE-STORAGE-01", "summary": "I cannot sign in to my account"}}
    status, job = client.call("POST", "/v1/jobs", body)
    retention = job.get("retention") or {}
    check(status == 202 and retention.get("persistent") is persistent
          and retention.get("lost_on") == ([] if persistent else LOST_ON),
          "a new case's reply says how long it is kept, as the check found")
    write_summary(summary, storage_line(label, expected, storage))


def blocked(client, state_file, timeout_s, summary):
    """Roadmap 1.7, from the quality report of 2026-11-19 (page 4): AI settings that cannot work. ``/healthz`` stays
    200, so the host never restarts the service (on the free plan that empties the queue); ``/readyz`` answers 503
    ``blocked_config``; a case is still admitted and waits."""
    status, health = client.call("GET", "/healthz", key=False)
    check(status == 200 and health.get("ok") is True, "/healthz answers 200: the host has no reason to restart it")
    deadline = time.monotonic() + timeout_s
    while True:  # "starting" until the Runner's first heartbeat
        status, ready = client.call("GET", "/readyz", key=False)
        if ready.get("state") == "blocked_config" or time.monotonic() > deadline:
            break
        time.sleep(0.5)
    check(status == 503 and ready == {"ok": False, "state": "blocked_config"},
          "/readyz answers 503 blocked_config, a code without any detail")
    status, info = client.call("GET", "/v1/status")
    check(status == 200 and info["runner"]["state"] == "blocked_config" and info["runner"]["alive"],
          "/v1/status shows a live Runner blocked by its AI settings")
    body = {"workflow_type": "case_triage.v2", "idempotency_key": f"smoke-{uuid.uuid4()}",
            "input": {"case_id": "SMOKE-BLOCKED-01", "summary": "I cannot upload an attachment"}}
    status, job = client.call("POST", "/v1/jobs", body)
    check(status == 202 and job.get("status") == "QUEUED", "a case is still admitted (202 QUEUED)")
    time.sleep(3)
    status, again = client.call("GET", f"/v1/jobs/{job['job_id']}")
    check(status == 200 and again.get("status") == "QUEUED",
          "the case waits in the queue: nothing runs, nothing is dropped")
    Path(state_file).write_text(json.dumps({"job_id": job["job_id"]}), encoding="utf-8")
    write_summary(summary, "- ตัวรันงานติดเพราะตั้งค่า AI ไม่ครบ (เลือก Typhoon แต่ไม่มีคีย์): `/healthz` ตอบ 200"
                           " (Render ไม่รีสตาร์ท), `/readyz` ตอบ 503 `blocked_config` และเคสยังรับเข้าคิวได้ ✓")


def after_fix(client, state_file, timeout_s, summary):
    """After ``--blocked``: the same data folder with settings that work. The case that waited is worked."""
    saved = json.loads(Path(state_file).read_text(encoding="utf-8"))
    wait_for_ready(client, timeout_s)
    result = wait_for_result(client, saved["job_id"], timeout_s)
    check(result["status"] == "REVIEW_REQUIRED", "the case that waited is worked and waits for a person")
    write_summary(summary, "- แก้ค่าแล้วเริ่มใหม่บนดิสก์เดิม: `/readyz` ตอบ 200 และเคสที่รออยู่ถูกทำจนถึง"
                           " \"รอคนตรวจ\" ✓")


def after_restart(client, state_file, timeout_s, expect_storage=None):
    saved = json.loads(Path(state_file).read_text(encoding="utf-8"))
    wait_for_runner(client, timeout_s)
    wait_for_ready(client, timeout_s)
    if expect_storage:
        storage_is(client, expect_storage)
    status, job = client.call("GET", f"/v1/jobs/{saved['job_id']}")
    check(status == 200 and job["status"] == "REVIEW_REQUIRED", "the case from before the restart is still stored")
    if saved.get("apply_job_id"):
        status, applied = client.call("GET", f"/v1/jobs/{saved['apply_job_id']}")
        check(status == 200 and applied["status"] == "COMPLETED" and applied["handoff"]["from"] is not None,
              "the apply job and its handoff survive the restart")
    if saved.get("token_id"):
        status, listed = client.call("GET", "/v1/tokens")
        kept = [item for item in listed.get("tokens", []) if item.get("token_id") == saved["token_id"]]
        check(status == 200 and len(kept) == 1 and kept[0]["active"] is False,
              "the revoked token is still revoked after the restart (persistent storage)")
        reviewer_labels(client, "after the restart")
    body = {"workflow_type": "case_triage.v2", "idempotency_key": f"smoke-{uuid.uuid4()}",
            "input": {"case_id": "SMOKE-EN-02", "summary": "I cannot sign in to my account"}}
    status, fresh = client.call("POST", "/v1/jobs", body)
    check(status == 202, "a new case is admitted after the restart")
    result = wait_for_result(client, fresh["job_id"], timeout_s)
    check(result["status"] == "REVIEW_REQUIRED", "the restarted Runner finishes new work")
    check(finished_v2_jobs(client) >= 2, "the status figures still count the case from before the restart")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True)
    parser.add_argument("--key", required=True, help="the service's NEURON_FLOW_ACCESS_KEY")
    parser.add_argument("--state", help="file that remembers the job between the two runs")
    parser.add_argument("--after-restart", action="store_true")
    parser.add_argument("--first-case-only", action="store_true",
                        help="only time the first case after a start; a report that does not fail")
    parser.add_argument("--label", default="this service", help="names the service in the reports")
    parser.add_argument("--summary", help="append the first case's time here (e.g. $GITHUB_STEP_SUMMARY)")
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--expect-storage", choices=STORAGE_CHECKS,
                        help="also check what the start found about the data folder (roadmap 1.7)")
    parser.add_argument("--storage-check", choices=STORAGE_CHECKS,
                        help="only check what the start found about the data folder, and one case's retention")
    parser.add_argument("--blocked", action="store_true",
                        help="expect a Runner blocked by its AI settings; needs --state")
    parser.add_argument("--after-fix", action="store_true",
                        help="after --blocked: expect /readyz 200 and the waiting case worked; needs --state")
    args = parser.parse_args(argv)
    client = Client(args.url, args.key)
    if (args.blocked or args.after_fix) and not args.state:
        parser.error("--blocked and --after-fix need --state")
    if args.first_case_only:
        try:
            wait_until_healthy(client, args.timeout)
        except SystemExit as exc:
            print(f"::warning::first case ({args.label}): {exc}")
            write_summary(args.summary, first_case_line(args.label, "บริการไม่พร้อมภายในเวลาที่รอ", None, None))
            return 0
        first_case_only(client, args.timeout, args.label, args.summary)
        return 0
    wait_until_healthy(client, args.timeout)
    if args.storage_check:
        storage_only(client, args.storage_check, args.timeout, args.summary, args.label)
    elif args.blocked:
        blocked(client, args.state, args.timeout, args.summary)
    elif args.after_fix:
        after_fix(client, args.state, args.timeout, args.summary)
    elif args.after_restart:
        if not args.state:
            parser.error("--after-restart needs --state")
        after_restart(client, args.state, args.timeout, args.expect_storage)
    else:
        first_run(client, args.state, args.timeout, args.summary, args.expect_storage)
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
