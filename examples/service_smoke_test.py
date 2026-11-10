"""Check a running Neuron Flow service from the outside, over HTTP (standard library only).

CI runs it against the Docker container; you can point it at the online service too:

    python -m examples.service_smoke_test --url https://<your-service>.onrender.com --key <access key>

First run: submit a case, check duplicates and conflicts, wait for the result, save its job id.
With ``--after-restart``: check that the saved job is still there and that new work still runs.
With ``--cold-start``: measure a start instead of checking it (roadmap E1): how long until the service answers,
and how long the first and the second case take. It reports and never fails, because times depend on the machine.
It only uses synthetic text, and it never prints the access key.
"""

import argparse
from datetime import datetime
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


def job_times(job):
    """(seconds waiting in the queue, seconds running) from the job's own timestamps, or None when one is missing."""
    def moment(name):
        value = job.get(name)
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ") if value else None

    created, started, finished = moment("created_at"), moment("started_at"), moment("finished_at")
    wait = (started - created).total_seconds() if created and started else None
    run = (finished - started).total_seconds() if started and finished else None
    return wait, run


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


def first_run(client, state_file, timeout_s):
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
    wait, run = job_times(result)
    if wait is not None and run is not None:
        print(f"     first case after the start: waited {wait:.2f} s, ran {run:.2f} s")
    check(review.get("decision") == "PENDING_HUMAN_REVIEW", "the AI never decides (PENDING_HUMAN_REVIEW)")
    check(review.get("review_priority") == "elevated", "the Thai case missed by the rules is raised for review")
    status, events = client.call("GET", f"/v1/jobs/{job['job_id']}/events?limit=100")
    kinds = [event["kind"] for event in events.get("events", [])]
    check(kinds[:2] == ["job.queued", "job.claimed"] and kinds[-1] == "job.review_required", "the job history is complete")
    check(finished_v2_jobs(client) >= 1, "the status figures count the finished case and its run time (roadmap 5.3)")
    if state_file:
        Path(state_file).write_text(json.dumps({"job_id": job["job_id"]}), encoding="utf-8")


def after_restart(client, state_file, timeout_s):
    saved = json.loads(Path(state_file).read_text(encoding="utf-8"))
    wait_for_runner(client, timeout_s)
    status, job = client.call("GET", f"/v1/jobs/{saved['job_id']}")
    check(status == 200 and job["status"] == "REVIEW_REQUIRED", "the case from before the restart is still stored")
    body = {"workflow_type": "case_triage.v2", "idempotency_key": f"smoke-{uuid.uuid4()}",
            "input": {"case_id": "SMOKE-EN-02", "summary": "I cannot sign in to my account"}}
    status, fresh = client.call("POST", "/v1/jobs", body)
    check(status == 202, "a new case is admitted after the restart")
    result = wait_for_result(client, fresh["job_id"], timeout_s)
    check(result["status"] == "REVIEW_REQUIRED", "the restarted Runner finishes new work")
    check(finished_v2_jobs(client) >= 2, "the status figures still count the case from before the restart")


def _quiet_call(client, method, path, body=None, *, key=True):
    """Like ``Client.call``, but a refused connection or a timeout is (None, {}): a slow start is expected here."""
    try:
        return client.call(method, path, body, key=key)
    except (urllib.error.URLError, OSError):
        return None, {}


def _wait_quietly(probe, deadline):
    """Seconds (on this machine's clock) until ``probe()`` returns something true, or None at the deadline."""
    while time.time() < deadline:
        value = probe()
        if value:
            return time.time(), value
        time.sleep(0.5)
    return None, None


def measure_cold_start(client, started, timeout_s):
    """Times of one start: until healthy, until the Runner is alive, then the first and the second case.
    Every value may be None when that stage was not reached in time. Nothing here raises for a slow service."""
    deadline = started + timeout_s
    report = {"healthy_s": None, "runner_s": None, "cases": []}
    at, _ = _wait_quietly(lambda: _quiet_call(client, "GET", "/healthz", key=False)[0] == 200, deadline)
    if at is None:
        return report
    report["healthy_s"] = at - started
    at, _ = _wait_quietly(lambda: (_quiet_call(client, "GET", "/v1/status")[1].get("runner") or {}).get("alive"),
                          deadline)
    if at is None:
        return report
    report["runner_s"] = at - started
    for case_id, summary in (("COLD-TH-01", "อัปโหลดไฟล์แนบไม่ได้ ค้างที่ 99%"),
                             ("COLD-EN-02", "I cannot sign in to my account")):
        body = {"workflow_type": "case_triage.v2", "idempotency_key": f"cold-{uuid.uuid4()}",
                "input": {"case_id": case_id, "summary": summary}}
        status, job = _quiet_call(client, "POST", "/v1/jobs", body)
        entry = {"admitted": status == 202, "status": None, "wait_s": None, "run_s": None, "failure": None}
        report["cases"].append(entry)
        if status != 202:
            break

        def finished(job_id=job["job_id"]):
            code, view = _quiet_call(client, "GET", f"/v1/jobs/{job_id}")
            return view if code == 200 and view.get("status") in TERMINAL else None

        _, view = _wait_quietly(finished, deadline)
        if view is None:
            break
        entry["status"] = view["status"]
        entry["wait_s"], entry["run_s"] = job_times(view)
        failure = view.get("failure")
        entry["failure"] = failure.get("reason") if isinstance(failure, dict) else failure
    return report


def cold_start_summary(report, label):
    """The measurement as Markdown (Thai first, as on the other run pages)."""
    def seconds(value):
        return "ไม่ถึงขั้นนี้ในเวลาที่กำหนด (not reached in time)" if value is None else f"{value:.1f} s"

    lines = [f"### เคสแรกหลังระบบเริ่มทำงาน: {label} (first case after a start)", "",
             "| สิ่งที่วัด (measure) | ผล (result) |", "|---|---|",
             f"| ระบบตอบ `/healthz` หลังสั่งเริ่ม (healthy after the start) | {seconds(report['healthy_s'])} |",
             f"| ตัวรันงานพร้อม (Runner alive) | {seconds(report['runner_s'])} |"]
    names = ("เคสแรก (first case)", "เคสที่สอง (second case)")
    for name, case in zip(names, report["cases"]):
        if not case["admitted"]:
            lines.append(f"| {name} | ระบบไม่รับเคส (not admitted) |")
        elif case["status"] is None:
            lines.append(f"| {name} | ไม่จบในเวลาที่กำหนด (did not finish in time) |")
        else:
            timing = (f"รอคิว (waited) {case['wait_s']:.2f} s · ทำงาน (ran) **{case['run_s']:.2f} s**"
                      if case["wait_s"] is not None and case["run_s"] is not None else "ไม่มีเวลา (no times)")
            failure = f" · สาเหตุ (reason) `{case['failure']}`" if case["failure"] else ""
            lines.append(f"| {name} | {timing} · `{case['status']}`{failure} |")
    for name in names[len(report["cases"]):]:
        lines.append(f"| {name} | ไม่ได้ส่ง (not sent) |")
    lines += ["", "รายงานอย่างเดียว ไม่ทำให้ช่องตรวจแดง เพราะเวลาขึ้นกับเครื่องทดสอบ เวลาทำงานของเคสมาจากเวลาที่ระบบบันทึกเอง "
                  "(Report only: times depend on the runner. Case times come from the service's own timestamps.)"]
    return "\n".join(lines) + "\n"


def cold_start(client, started, timeout_s, summary_file, label):
    report = measure_cold_start(client, started, timeout_s)
    text = cold_start_summary(report, label)
    print(text)
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as stream:
            stream.write(text + "\n")
    slow = [case for case in report["cases"] if case["status"] != "REVIEW_REQUIRED"]
    if report["runner_s"] is None or len(report["cases"]) < 2 or slow:
        print(f"::warning::cold start ({label}): the measurement did not complete; see the table in the summary")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True)
    parser.add_argument("--key", required=True, help="the service's NEURON_FLOW_ACCESS_KEY")
    parser.add_argument("--state", help="file that remembers the job between the two runs")
    parser.add_argument("--after-restart", action="store_true")
    parser.add_argument("--cold-start", action="store_true",
                        help="measure a start (report only): time until healthy, then the first and second case")
    parser.add_argument("--started", type=float,
                        help="with --cold-start: when the service was started, in seconds since the epoch (default: now)")
    parser.add_argument("--label", default="ไม่จำกัดเครื่อง (no limit)", help="with --cold-start: what the run page calls this start")
    parser.add_argument("--summary", help="with --cold-start: append the Markdown table here (e.g. $GITHUB_STEP_SUMMARY)")
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args(argv)
    client = Client(args.url, args.key)
    if args.cold_start:
        started = args.started if args.started is not None else time.time()
        return cold_start(client, started, args.timeout, args.summary, args.label)
    wait_until_healthy(client, args.timeout)
    if args.after_restart:
        if not args.state:
            parser.error("--after-restart needs --state")
        after_restart(client, args.state, args.timeout)
    else:
        first_run(client, args.state, args.timeout)
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
