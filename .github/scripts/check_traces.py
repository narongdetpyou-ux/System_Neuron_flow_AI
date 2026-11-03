"""Check what the OpenTelemetry Collector received from the service in CI (roadmap 5.1).

Usage: python .github/scripts/check_traces.py <collector file> <smoke state file>

The collector (.github/otel/collector.yaml) is the reference OTLP receiver: if it accepted and stored our
requests, their encoding is right. This script then checks the content:
1. every span comes from the service ``neuron-flow`` in the ``ci`` environment, from the API and the Runner;
2. the case the smoke test submitted is one trace: the request that admitted it, the job, the queue wait,
   the run, each step and the AI call, linked parent to child, with the steps inside the run;
3. the health check and the page are not traced; the refused requests (401, 400, 409) are;
4. no case text, case id or key appears anywhere in what was sent.
It writes the trace as a table to the job summary (in Thai and English) so it can be read without Honeycomb.
"""

import json
import os
from pathlib import Path
import sys

EXPECTED = ["POST /v1/jobs", "job case_triage.v2", "queue wait", "run", "step classify_rules",
            "step classify_llm", "step compare", "step prepare", "chat mock-keyword-1"]
PARENT = {"job case_triage.v2": "POST /v1/jobs", "queue wait": "job case_triage.v2", "run": "job case_triage.v2",
          "step classify_rules": "run", "step classify_llm": "run", "step compare": "run", "step prepare": "run",
          "chat mock-keyword-1": "step classify_llm"}
# What the smoke test sent (examples/service_smoke_test.py) and must never come back out.
PRIVATE = ["อัปโหลดไฟล์แนบไม่ได้ ค้างที่ 99%", "อัปโหลด", "SMOKE-TH-01", "SMOKE-2", "a different problem altogether"]


def attributes(item):
    values = {}
    for attribute in item.get("attributes") or []:
        (kind, value), = attribute["value"].items()
        values[attribute["key"]] = int(value) if kind == "intValue" else value
    return values


def load(path):
    spans = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        for resource_spans in json.loads(line).get("resourceSpans") or []:
            resource = attributes(resource_spans.get("resource") or {})
            for scope in resource_spans.get("scopeSpans") or []:
                spans += [dict(item, resource=resource) for item in scope.get("spans") or []]
    return spans


def fail(problems):
    for problem in problems:
        print(f"::error::{problem}")
    raise SystemExit(1)


def main(collector_file, state_file):
    raw = Path(collector_file).read_text(encoding="utf-8")
    spans = load(collector_file)
    job_id = json.loads(Path(state_file).read_text(encoding="utf-8"))["job_id"]
    problems = []
    if not spans:
        fail(["the collector received no spans"])

    resources = {json.dumps(item["resource"], sort_keys=True) for item in spans}
    for resource in map(json.loads, resources):
        if (resource.get("service.name"), resource.get("deployment.environment.name")) != ("neuron-flow", "ci"):
            problems.append(f"unexpected service or environment: {resource}")
    processes = {item["resource"].get("neuron_flow.process") for item in spans}
    if processes != {"api", "runner"}:
        problems.append(f"expected spans from the API and the Runner, got {sorted(map(str, processes))}")

    jobs = [item for item in spans if attributes(item).get("neuron_flow.job.id") == job_id
            and item["name"] == "job case_triage.v2"]
    if len(jobs) != 1:
        fail(problems + [f"expected one job span for the smoke case, found {len(jobs)}"])
    trace = [item for item in spans if item["traceId"] == jobs[0]["traceId"]]
    names = sorted(item["name"] for item in trace)
    if names != sorted(EXPECTED):
        problems.append(f"the case's trace has {names}, expected {sorted(EXPECTED)}")
    named = {item["name"]: item for item in trace}
    for child, parent in PARENT.items():
        if child in named and parent in named and named[child].get("parentSpanId") != named[parent]["spanId"]:
            problems.append(f"'{child}' is not a child of '{parent}'")
    root = named.get("POST /v1/jobs")
    if root is not None and root.get("parentSpanId"):
        problems.append("the request that admitted the case should be the root of its trace")
    run = named.get("run")
    for name, item in named.items():
        if name.startswith("step ") and run is not None and not (
                int(run["startTimeUnixNano"]) <= int(item["startTimeUnixNano"])
                and int(item["endTimeUnixNano"]) <= int(run["endTimeUnixNano"])):
            problems.append(f"'{name}' is not inside the run")

    routes = sorted((attributes(item).get("http.route"), attributes(item).get("http.response.status_code"))
                    for item in spans if attributes(item).get("http.request.method"))
    for expected in (("/v1/status", 401), ("/v1/jobs", 202), ("/v1/jobs", 200), ("/v1/jobs", 409), ("/v1/jobs", 400)):
        if expected not in routes:
            problems.append(f"no span for {expected}")
    if any(route in ("/healthz", "/") for route, _status in routes):
        problems.append("the health check or the page was traced")

    for text in PRIVATE + [os.environ.get("ACCESS_KEY", ""), os.environ.get("HONEYCOMB_API_KEY", "placeholder")]:
        if text and (text in raw or json.dumps(text)[1:-1] in raw):
            problems.append("private text or a key reached the collector")
    if problems:
        fail(problems)

    start = int(root["startTimeUnixNano"]) if root else min(int(item["startTimeUnixNano"]) for item in trace)
    rows = sorted(trace, key=lambda item: (int(item["startTimeUnixNano"]), EXPECTED.index(item["name"])))
    lines = ["## เส้นทางงาน (trace) ของเคสตัวอย่าง: ผ่าน", "",
             f"One trace with {len(trace)} spans for `{job_id}`; {len(spans)} spans in total, none with case text "
             "or keys. Times are from this CI machine.", "",
             "| span | starts at | lasts |", "|---|---|---|"]
    for item in rows:
        depth, parent = 0, item
        while parent.get("parentSpanId") and any(other["spanId"] == parent["parentSpanId"] for other in trace):
            parent = next(other for other in trace if other["spanId"] == parent["parentSpanId"])
            depth += 1
        begins = (int(item["startTimeUnixNano"]) - start) / 1e6
        lasts = (int(item["endTimeUnixNano"]) - int(item["startTimeUnixNano"])) / 1e6
        lines.append(f"| {'&nbsp;' * 4 * depth}{item['name']} | +{begins:.1f} ms | {lasts:.1f} ms |")
    print("\n".join(lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__.split("\n\n")[1])
    sys.exit(main(sys.argv[1], sys.argv[2]))
