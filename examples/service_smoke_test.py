"""Check a running Neuron Flow service from the outside, over HTTP (standard library only).

CI runs it against the Docker container; you can point it at the online service too:

    python -m examples.service_smoke_test --url https://<your-service>.onrender.com --key <access key>

First run: submit a case, check duplicates and conflicts, wait for the result, save its job id.
With ``--after-restart``: check that the saved job is still there and that new work still runs.
With ``--first-case-only``: submit one case to a service that has just started and report how long it
took (effectiveness plan E1). That mode reports and never fails on a time or on the case's outcome.
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


def first_run(client, state_file, timeout_s, summary=None):
    status, _ = client.call("GET", "/", key=False)
    check(status == 200, "the web page loads")
    status, _ = client.call("GET", "/v1/status", key=False)
    check(status == 401, "the API refuses requests without the access key")
    info = wait_for_runner(client, timeout_s)
    print(f"     ai={info['ai']['provider']}/{info['ai']['model']} storage={info['storage']['kind']}")
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
    if state_file:
        Path(state_file).write_text(json.dumps({"job_id": job["job_id"], "apply_job_id": applied}), encoding="utf-8")


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


def after_restart(client, state_file, timeout_s):
    saved = json.loads(Path(state_file).read_text(encoding="utf-8"))
    wait_for_runner(client, timeout_s)
    status, job = client.call("GET", f"/v1/jobs/{saved['job_id']}")
    check(status == 200 and job["status"] == "REVIEW_REQUIRED", "the case from before the restart is still stored")
    if saved.get("apply_job_id"):
        status, applied = client.call("GET", f"/v1/jobs/{saved['apply_job_id']}")
        check(status == 200 and applied["status"] == "COMPLETED" and applied["handoff"]["from"] is not None,
              "the apply job and its handoff survive the restart")
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
    parser.add_argument("--label", default="this service", help="names the service in the --first-case-only report")
    parser.add_argument("--summary", help="append the first case's time here (e.g. $GITHUB_STEP_SUMMARY)")
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args(argv)
    client = Client(args.url, args.key)
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
    if args.after_restart:
        if not args.state:
            parser.error("--after-restart needs --state")
        after_restart(client, args.state, args.timeout)
    else:
        first_run(client, args.state, args.timeout, args.summary)
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
