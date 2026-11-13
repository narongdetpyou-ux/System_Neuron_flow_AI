"""End-to-end check of case triage with a local model server (ADR-026, ADR-034), over HTTP, through the real service.

The *Local open model eval* workflow runs it against llama.cpp serving a pinned model file (the publisher's Typhoon
2.5 4B, or the owner's fine-tune); the tests run it against ``tests/fake_llama_server.py``. Synthetic cases only.

It starts the service itself, ``python -m app.serve`` (the HTTP API and its supervised Runner, which runs
``case_triage.v2`` on Core), on 127.0.0.1 with a fresh data folder, a throwaway access key and the ``local`` provider
pointed at the model server. Nothing in ``app/`` or Core changes for this; the service is the one Render runs.

Phases (``--phases``, comma-separated):

* ``service``: fixed synthetic cases from the development and hard sets (four categories, Thai and English, attention
  of every kind, cases where the rules are wrong, a case with personal data):
  1. the service says it uses ``local`` with this model id, and is not simulated; the model server serves that id,
     has the pinned file open (re-hashed with ``--model-file``/``--model-sha256``) and names its chat template;
  2. every case reaches REVIEW_REQUIRED with a proposal that keeps the rules official, a second opinion inside the
     answer schema (category, attention, confidence) or ``unavailable`` with a known reason, and review reasons that
     agree with it (a disagreement, a signal or the AI's flag, and only then, raises the priority);
  3. provenance: the AI block names ``local``, the model id, the prompt and its SHA-256, the masking version; the
     masking counted the phone number before the AI call;
  4. audit trail: every step succeeded; Core's receipt is recomputed from the report file on disk (SHA-256 and size)
     and the report holds the same provenance; the job's events are complete and hold no case text;
  5. people decide: the inbox lists raised cases first; an approval as proposed, an approval with another category
     and a rejection apply once each; the same click again changes nothing; a stale version is refused; each approval
     starts exactly one ``case_triage.v2.apply`` job, which completes with its own verified receipt.
* ``failures``: a client timeout shorter than any answer, and a model server that does not answer: the AI step is
  tried twice, then ``unavailable``, and the case still waits for a person with the rules' suggestion.
* ``faults`` (needs ``--fake-control``: only the fake server can misbehave on purpose): prose instead of JSON, a value
  outside the schema, an extra key, a cut-off answer, a refusal, HTTP 500, and one HTTP 503 followed by an answer.

It never fails on a wrong category or attention: accuracy is the scorecards' job. It fails (exit 1) when a promise
above breaks. ``--summary`` appends a Markdown report (Thai first); ``--json`` writes every check and every case.
The access key is never printed.

    python -m tests.local_model_e2e --llm-base-url http://127.0.0.1:8080/v1 --model-id <name>:<12 hex> \
        --model-file ~/models/<file>.gguf --model-sha256 <64 hex> --summary "$GITHUB_STEP_SUMMARY" --json e2e.json
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from app.domains.case_triage.contracts import (AI_FLAG_REASONS, ATTENTION_VALUES, CATEGORIES, CONFIDENCE_LEVELS,
                                               QUEUE_FOR, SIGNAL_REASONS, UNAVAILABLE_REASONS)
from app.domains.case_triage.shadow_workflow import PROMPT_ID
from app.llm import REDACTION_VERSION, load_prompt

ROOT = Path(__file__).resolve().parent.parent
SETS = {"development": ROOT / "app" / "eval" / "golden" / "case_triage_synthetic_v1.json",
        "hard": ROOT / "app" / "eval" / "golden" / "case_triage_autosend_hard_v1.json"}
# Four categories in both languages, an injection, rules mistakes (the AI should disagree), each attention kind,
# and a case with a phone number (masked before the AI call). None is from a held-out set.
SERVICE_CASES = (("development", "EN-ACC-01"), ("development", "TH-UPL-01"), ("development", "EN-BIL-01"),
                 ("development", "TH-OTH-04"), ("development", "EN-ADV-01"), ("hard", "AS-EN-TRP-01"),
                 ("hard", "AS-TH-NEG-03"), ("hard", "AS-EN-SEC-01"), ("hard", "AS-TH-SAF-01"),
                 ("hard", "AS-EN-LEG-01"), ("hard", "AS-TH-INJ-06"), ("hard", "AS-TH-PII-01"))
QUICK_CASES = (("development", "EN-ACC-01"), ("development", "TH-UPL-01"), ("hard", "AS-EN-TRP-01"),
               ("hard", "AS-TH-PII-01"))
FAULTS = (  # (fake server mode, how many chat requests, expected AI status, reason, attempts)
    ("invalid_json", -1, "unavailable", "invalid_model_output", 2),
    ("bad_enum", -1, "unavailable", "invalid_model_output", 2),
    ("wrong_keys", -1, "unavailable", "invalid_model_output", 2),
    ("cut_off", -1, "unavailable", "invalid_model_output", 2),
    ("content_filter", -1, "unavailable", "model_declined", 1),
    ("refusal", -1, "unavailable", "model_declined", 1),
    ("http_500", -1, "unavailable", "provider_unavailable", 2),
    ("http_503", 1, "ok", None, 2),
)
SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|DSN)", re.IGNORECASE)
TERMINAL = {"REVIEW_REQUIRED", "COMPLETED", "FAILED", "DELIVERY_FAILED", "APPROVED", "REJECTED", "CANCELLED"}
STEP_IDS = ("classify_rules", "classify_llm", "screen", "compare", "prepare")
REASON = "ตรวจแล้วในการทดสอบปลายทางกับโมเดลในเครื่อง"  # a fixed synthetic reason


def load_cases(selection):
    by_set = {name: {c["case_id"]: c for c in json.loads(path.read_text(encoding="utf-8"))["cases"]}
              for name, path in SETS.items()}
    return [{"set": name, **by_set[name][case_id]} for name, case_id in selection]


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def http(method, url, body=None, *, key=None, timeout=30):
    """``(status, parsed JSON or None, raw bytes)``; never raises on an HTTP status."""
    headers = {"Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        with exc:
            status, raw = exc.code, exc.read()
    try:
        return status, json.loads(raw) if raw else None, raw
    except ValueError:
        return status, None, raw


def service_environment(base, **values):
    """The service's environment: this one without secrets or other NEURON_FLOW settings, plus ``values``."""
    env = {k: v for k, v in base.items()
           if not k.startswith(("NEURON_FLOW_", "NF_MODEL_")) and not SECRET_NAME.search(k) and k != "PORT"}
    env.update({k: str(v) for k, v in values.items()})
    return env


class Service:
    """``python -m app.serve`` on 127.0.0.1 with its own data folder; ``call`` speaks to its API."""

    def __init__(self, workdir, name, *, model_id, llm_base_url, timeout_s, environ=None):
        self.data_dir = Path(workdir) / f"data-{name}"
        self.log_path = Path(workdir) / f"service-{name}.log"
        self.key = secrets.token_urlsafe(24)
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.env = service_environment(
            os.environ if environ is None else environ,
            NEURON_FLOW_DATA_DIR=self.data_dir, NEURON_FLOW_ACCESS_KEY=self.key, NEURON_FLOW_HOST="127.0.0.1",
            PORT=self.port, NEURON_FLOW_LLM_PROVIDER="local", NEURON_FLOW_LLM_MODEL=model_id,
            NEURON_FLOW_LOCAL_BASE_URL=llm_base_url, NEURON_FLOW_LLM_TIMEOUT_S=timeout_s,
            NEURON_FLOW_RUNNER_POLL_S="0.1", NEURON_FLOW_SUBMIT_PER_MINUTE="600", NEURON_FLOW_MAX_QUEUED="1000")
        self.process = None

    def start(self, timeout_s=90):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._log = open(self.log_path, "wb")
        self.process = subprocess.Popen([sys.executable, "-m", "app.serve"], cwd=ROOT, env=self.env,
                                        stdout=self._log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"the service stopped at start (exit {self.process.returncode}); see {self.log_path}")
            try:
                status, body, _ = self.call("GET", "/v1/status", timeout=5)
                if status == 200 and body["runner"]["alive"]:
                    return self
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(0.2)
        raise RuntimeError(f"the service did not become ready in {timeout_s}s; see {self.log_path}")

    def call(self, method, path, body=None, timeout=30):
        return http(method, self.url + path, body, key=self.key, timeout=timeout)

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
            try:
                self.process.wait(40)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if getattr(self, "_log", None):
            self._log.close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.stop()

    def submit(self, case, key):
        status, body, _ = self.call("POST", "/v1/jobs", {
            "workflow_type": "case_triage.v2", "idempotency_key": key,
            "input": {"case_id": case["case_id"], "summary": case["summary"]}})
        return status, body

    def wait(self, job_id, timeout_s):
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            status, job, _ = self.call("GET", f"/v1/jobs/{job_id}")
            if status == 200 and job["status"] in TERMINAL:
                return job
            time.sleep(0.25)
        raise TimeoutError(f"job {job_id} did not finish in {timeout_s}s")

    def events(self, job_id):
        _status, body, _ = self.call("GET", f"/v1/jobs/{job_id}/events?limit=100")
        return (body or {}).get("events") or []


class Checks:
    def __init__(self):
        self.items = []

    def add(self, phase, check_id, ok, th, en, detail=""):
        self.items.append({"phase": phase, "id": check_id, "ok": bool(ok), "th": th, "en": en,
                           "detail": str(detail)[:300]})
        return bool(ok)

    @property
    def failed(self):
        return [item for item in self.items if not item["ok"]]


# -- the model server -------------------------------------------------------------------------------------

def server_root(llm_base_url):
    return llm_base_url.rstrip("/").removesuffix("/v1")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check_model_server(checks, llm_base_url, model_id, model_file=None, model_sha256=None):
    root = server_root(llm_base_url)
    info = {}
    status, models, _ = http("GET", root + "/v1/models")
    served = [item.get("id") for item in (models or {}).get("data") or [] if isinstance(item, dict)]
    checks.add("service", "server_model_id", status == 200 and model_id in served,
               "เครื่องรันโมเดลบอกชื่อรุ่นตรงกับที่ระบบใช้", "the model server serves this model id", served)
    status, props, _ = http("GET", root + "/props")
    props = props if status == 200 and isinstance(props, dict) else {}
    model_path = props.get("model_path") or ""
    template = props.get("chat_template") or ""
    info.update(model_path_name=Path(model_path).name or None, total_slots=props.get("total_slots"),
                build_info=props.get("build_info"),
                chat_template_sha256=hashlib.sha256(template.encode("utf-8")).hexdigest() if template else None,
                chat_template_chars=len(template))
    if model_file:
        checks.add("service", "server_model_file", Path(model_path).name == Path(model_file).name,
                   "เครื่องรันโมเดลเปิดไฟล์โมเดลที่ตรึงไว้", "the model server has the pinned file open",
                   info["model_path_name"])
        if model_sha256:
            got = sha256_file(model_file)
            info["model_file_sha256"] = got
            checks.add("service", "server_model_sha256", got == model_sha256,
                       "ไฟล์ที่เครื่องรันโมเดลเปิด มี SHA-256 ตรงกับที่ตรึงไว้ (คำนวณใหม่)",
                       "the open file's SHA-256 matches the pin (recomputed)", got[:12])
    checks.add("service", "server_chat_template", bool(template),
               "ไฟล์โมเดลมีแม่แบบบทสนทนา (chat template) ในตัว", "the model file carries a chat template",
               info["chat_template_sha256"])
    return info


# -- one case ---------------------------------------------------------------------------------------------

def expected_provenance(model_id):
    prompt = load_prompt(PROMPT_ID)
    return {"provider": "local", "model": model_id, "prompt_id": prompt.id, "prompt_sha256": prompt.sha256,
            "redaction": REDACTION_VERSION}


def proposal_problems(review):
    """Where a proposal breaks the shadow-mode contract (an empty list when it keeps it)."""
    problems = []
    if review.get("decision") != "PENDING_HUMAN_REVIEW" or review.get("review_required") is not True \
            or review.get("mode") != "shadow":
        problems.append("not pending a person")
    if not str(review.get("suggestion_source") or "").startswith("rules:"):
        problems.append("the official suggestion is not the rules'")
    category = review.get("suggested_category")
    if category not in CATEGORIES or review.get("suggested_queue") != QUEUE_FOR.get(category):
        problems.append("the rules' category or queue is outside the contract")
    second = review.get("second_opinion") or {}
    reasons = review.get("review_reasons") or []
    signalled = any(reason in SIGNAL_REASONS for reason in reasons)
    if second.get("status") == "ok":
        if second.get("category") not in CATEGORIES or second.get("attention") not in ATTENTION_VALUES \
                or second.get("confidence") not in CONFIDENCE_LEVELS:
            problems.append("the AI's answer is outside the answer schema")
        disagree = second.get("category") != category
        if review.get("agreement") != ("disagree" if disagree else "agree"):
            problems.append("agreement does not match the two categories")
        if ("rules_llm_disagree" in reasons) != disagree:
            problems.append("the disagreement reason does not match")
        flags = [reason for reason in reasons if reason in AI_FLAG_REASONS]
        wanted = [] if second.get("attention") == "none" else [f"ai_flag_{second.get('attention')}"]
        if flags != wanted:
            problems.append("the AI's attention flag and the review reasons differ")
        raised = disagree or signalled or bool(wanted)
    else:
        if second.get("status") != "unavailable" or second.get("reason") not in UNAVAILABLE_REASONS:
            problems.append("a missing AI answer has no known reason")
        if review.get("agreement") != "llm_unavailable" or "llm_unavailable" not in reasons:
            problems.append("a missing AI answer is not shown to the reviewer")
        raised = signalled
    if review.get("review_priority") != ("elevated" if raised else "normal"):
        problems.append("the review priority does not follow the reasons")
    return problems


def check_receipt(data_dir, job):
    """``(ok, detail, report)``: Core's report file has the receipt's SHA-256 and size."""
    receipt = (job.get("result") or {}).get("receipt") or {}
    path = Path(data_dir) / "core" / "reports" / f"{job['job_id']}.json"
    if not receipt.get("sha256") or not path.exists():
        return False, "no receipt or no report file", None
    raw = path.read_bytes()
    ok = hashlib.sha256(raw).hexdigest() == receipt["sha256"] and len(raw) == receipt.get("bytes")
    return ok, receipt["sha256"][:12], json.loads(raw)


def check_case(checks, phase, service, case, job, model_id, *, expect_ai=None):
    """The per-case promises; returns the row for the report."""
    result = job.get("result") or {}
    review = result.get("review") or {}
    ai = result.get("ai") or {}
    second = review.get("second_opinion") or {}
    label = f"{case['case_id']}"
    checks.add(phase, f"{label}:waits", job["status"] == "REVIEW_REQUIRED",
               "เคสไปรอคนตัดสิน (REVIEW_REQUIRED)", "the case waits for a person", job["status"])
    problems = proposal_problems(review) if review else ["no proposal"]
    checks.add(phase, f"{label}:proposal", not problems, "ข้อเสนอเป็นไปตามสัญญาของ shadow mode",
               "the proposal keeps the shadow-mode contract", "; ".join(problems))
    provenance = {key: ai.get(key) for key in expected_provenance(model_id)}
    checks.add(phase, f"{label}:provenance", provenance == expected_provenance(model_id),
               "บันทึกที่มาของคำตอบ AI ครบ (local, รุ่น, prompt, การปิดข้อมูล)",
               "the AI block names local, the model id, the prompt and the masking version", provenance)
    if second.get("status") == "ok":
        checks.add(phase, f"{label}:usage", (ai.get("usage") or {}).get("input_tokens", 0) > 0
                   and (ai.get("latency_ms") or 0) > 0 and ai.get("served_model") == model_id,
                   "คำตอบ AI มีจำนวน token เวลา และรุ่นที่ตอบ", "the AI answer records tokens, latency and the served model",
                   ai.get("served_model"))
    if expect_ai is not None:
        status, reason, attempts = expect_ai
        checks.add(phase, f"{label}:ai_outcome", (second.get("status"), second.get("reason")) == (status, reason)
                   and ai.get("attempt") == attempts,
                   "AI ล้มเหลวตามที่คาด แล้วเคสยังไปถึงคน" if status != "ok" else "AI ตอบได้หลังลองใหม่",
                   "the AI outcome is the expected one", (second.get("status"), second.get("reason"), ai.get("attempt")))
    steps = {step["id"]: step["status"] for step in result.get("steps") or []}
    checks.add(phase, f"{label}:steps", steps == {step: "SUCCEEDED" for step in STEP_IDS},
               "ทุกขั้นของงานสำเร็จ (5 ขั้น)", "all five steps succeeded", steps)
    ok, detail, report = check_receipt(service.data_dir, job)
    if report is not None:
        output = (report.get("steps") or {}).get("classify_llm", {}).get("output") or {}
        ok = ok and output.get("provenance") == expected_provenance(model_id) \
            and (report.get("steps") or {}).get("prepare", {}).get("output", {}).get("decision") == "PENDING_HUMAN_REVIEW"
    checks.add(phase, f"{label}:receipt", ok, "ใบรับของ Core ตรงกับไฟล์รายงาน (คำนวณ SHA-256 ใหม่)",
               "Core's receipt matches its report file (SHA-256 recomputed)", detail)
    events = service.events(job["job_id"])
    kinds = [event["kind"] for event in events]
    complete = kinds[:1] == ["job.queued"] and "job.claimed" in kinds and "job.review_required" in kinds \
        and kinds.count("step.succeeded") == len(STEP_IDS)
    checks.add(phase, f"{label}:events", complete and case["summary"] not in json.dumps(events, ensure_ascii=False),
               "บันทึกเหตุการณ์ครบ และไม่มีข้อความของเคส", "the events are complete and hold no case text", kinds)
    return {"set": case["set"], "case_id": case["case_id"], "language": case["language"],
            "expected": case["expected_category"], "needs_person": "needs_person" in case["tags"],
            "status": job["status"], "rules": review.get("suggested_category"),
            "ai_status": second.get("status"), "ai_reason": second.get("reason"), "ai": second.get("category"),
            "attention": second.get("attention"), "confidence": second.get("confidence"),
            "agreement": review.get("agreement"), "priority": review.get("review_priority"),
            "reasons": review.get("review_reasons"), "attempt": ai.get("attempt"), "latency_ms": ai.get("latency_ms"),
            "masked": ai.get("masked"), "tokens": (ai.get("usage") or {}).get("input_tokens")}


# -- phases -----------------------------------------------------------------------------------------------

def run_cases(checks, phase, service, cases, model_id, job_timeout_s, tag):
    rows, jobs = [], []
    for case in cases:
        started = time.monotonic()
        status, body = service.submit(case, f"e2e-{tag}-{case['case_id']}")
        checks.add(phase, f"{case['case_id']}:admitted", status == 202, "ระบบรับเคสเข้าคิว (202)",
                   "the case is admitted (202)", status)
        if status != 202:
            continue
        job = service.wait(body["job_id"], job_timeout_s)
        row = check_case(checks, phase, service, case, job, model_id)
        row["seconds"] = round(time.monotonic() - started, 2)
        rows.append(row)
        jobs.append(job)
    return rows, jobs


def phase_service(checks, workdir, args, cases):
    report = {"cases": [], "decisions": {}}
    with Service(workdir, "service", model_id=args.model_id, llm_base_url=args.llm_base_url,
                 timeout_s=args.timeout_s) as service:
        status, body, _ = service.call("GET", "/v1/status")
        ai = (body or {}).get("ai") or {}
        checks.add("service", "status_ai", status == 200 and ai.get("provider") == "local"
                   and ai.get("model") == args.model_id and ai.get("simulated") is False and not ai.get("problem"),
                   "บริการบอกว่าใช้โมเดลในเครื่องรุ่นนี้ ไม่ใช่ AI จำลอง",
                   "the service reports the local provider, this model id, not simulated", ai)
        report["server"] = check_model_server(checks, args.llm_base_url, args.model_id, args.model_file,
                                              args.model_sha256)
        rows, jobs = run_cases(checks, "service", service, cases, args.model_id, args.job_timeout_s, "service")
        report["cases"] = rows
        again, body = service.submit(cases[0], f"e2e-service-{cases[0]['case_id']}")
        checks.add("service", "duplicate", again == 200 and body["job_id"] == jobs[0]["job_id"],
                   "ส่งเคสเดิมซ้ำ ไม่เกิดงานใหม่", "a repeated submission returns the same job", again)
        pii = next((row for row in rows if row["case_id"] == "AS-TH-PII-01"), None)
        if pii is not None:
            checks.add("service", "masked_before_ai", (pii["masked"] or {}).get("phone", 0) >= 1,
                       "เบอร์โทรถูกปิดก่อนส่งให้ AI", "the phone number was masked before the AI call", pii["masked"])
        report["decisions"] = decide_and_apply(checks, service, jobs, args.job_timeout_s)
    return report


def decide_and_apply(checks, service, jobs, timeout_s):
    status, inbox, _ = service.call("GET", "/v1/reviews?state=PENDING&limit=100")
    listed = [item["job_id"] for item in (inbox or {}).get("reviews") or []]
    priorities = [item["priority"] for item in (inbox or {}).get("reviews") or []]
    ours = {job["job_id"] for job in jobs}
    checks.add("decide", "inbox", status == 200 and ours <= set(listed)
               and priorities == sorted(priorities, key=lambda p: p != "elevated"),
               "กล่องรอตรวจมีทุกเคส และเคสด่วนขึ้นก่อน", "the inbox lists every case, raised ones first", priorities)
    review_of = {job["job_id"]: (job.get("human_review") or {}).get("review_id") for job in jobs}
    plans = []
    if len(jobs) >= 4:
        first, second, third, fourth = jobs[:4]
        changed = next(c for c in CATEGORIES if c != first["result"]["review"]["suggested_category"]
                       and c != second["result"]["review"]["suggested_category"])
        plans = [(first, "APPROVE", None), (second, "APPROVE", changed), (third, "REJECT", None)]
    outcome = {}
    for index, (job, decision, category) in enumerate(plans):
        body = {"decision": decision, "reason": REASON, "expected_version": 1,
                "idempotency_key": f"e2e-decide-{index:03d}-{job['job_id'][-8:]}"}
        if category:
            body["final_category"] = category
        status, reply, _ = service.call("POST", f"/v1/reviews/{review_of[job['job_id']]}/decisions", body)
        decided = (reply or {}).get("decision") or {}
        wanted = category or (job["result"]["review"]["suggested_category"] if decision == "APPROVE" else None)
        handoffs = (reply or {}).get("handoffs") or []
        ok = status == 201 and decided.get("decision") == decision and decided.get("final_category") == wanted \
            and len(handoffs) == (1 if decision == "APPROVE" else 0)
        checks.add("decide", f"decision_{index}", ok,
                   {0: "คนอนุมัติตามข้อเสนอ", 1: "คนอนุมัติแต่เปลี่ยนหมวด", 2: "คนไม่อนุมัติ"}[index],
                   f"a person decides: {decision.lower()}" + (f" as {category}" if category else ""), (status, wanted))
        repeat, reply2, _ = service.call("POST", f"/v1/reviews/{review_of[job['job_id']]}/decisions", body)
        checks.add("decide", f"decision_{index}_repeat", repeat == 200 and (reply2 or {}).get("created") is False
                   and ((reply2 or {}).get("decision") or {}).get("decision_id") == decided.get("decision_id")
                   and len((reply2 or {}).get("handoffs") or []) == len(handoffs),
                   "กดซ้ำแล้วไม่มีอะไรเปลี่ยน", "the same click again changes nothing", repeat)
        outcome[job["job_id"]] = {"decision": decision, "final_category": wanted,
                                  "decision_id": decided.get("decision_id"), "handoffs": handoffs}
    if len(jobs) >= 4:
        status, reply, _ = service.call("POST", f"/v1/reviews/{review_of[jobs[3]['job_id']]}/decisions",
                                        {"decision": "APPROVE", "reason": REASON, "expected_version": 2,
                                         "idempotency_key": "e2e-decide-stale-version"})
        checks.add("decide", "stale_version", status == 409 and (reply or {}).get("error") == "version_conflict",
                   "ตัดสินด้วยข้อมูลเก่าถูกปฏิเสธ (409)", "a stale version is refused (409)", status)
    for job_id, done in outcome.items():
        status, job, _ = service.call("GET", f"/v1/jobs/{job_id}")
        checks.add("decide", f"{job_id[-6:]}:state", job and job["status"] == ("APPROVED" if done["decision"] == "APPROVE"
                                                                                else "REJECTED"),
                   "สถานะงานเปลี่ยนตามที่คนตัดสิน", "the job's state follows the decision", job and job["status"])
        for handoff in done["handoffs"]:
            target = service.wait(handoff["target_job_id"], timeout_s)
            output = (target.get("result") or {}).get("output") or {}
            ok, detail, _report = check_receipt(service.data_dir, target)
            checks.add("decide", f"{job_id[-6:]}:apply", target["status"] == "COMPLETED"
                       and output.get("final_category") == done["final_category"]
                       and output.get("final_queue") == QUEUE_FOR[done["final_category"]]
                       and output.get("decision_id") == done["decision_id"] and ok,
                       "งานบันทึกผลบันทึกตรงกับที่คนตัดสิน พร้อมใบรับที่ตรวจแล้ว",
                       "the apply job records exactly the decision, with a verified receipt", detail)
    return {job_id[-6:]: {k: v for k, v in done.items() if k != "handoffs"} for job_id, done in outcome.items()}


def phase_failures(checks, workdir, args, case, control):
    rows = []
    if control:
        control("ok", -1, 3.0)  # every answer slower than the client waits
    try:
        with Service(workdir, "timeout", model_id=args.model_id, llm_base_url=args.llm_base_url,
                     timeout_s=args.short_timeout_s) as service:
            rows += failure_case(checks, service, case, args, "timeout")
    finally:
        if control:
            control("ok", -1, 0.0)
    closed = f"http://127.0.0.1:{free_port()}/v1"  # nothing listens there
    with Service(workdir, "unreachable", model_id=args.model_id, llm_base_url=closed, timeout_s=5) as service:
        rows += failure_case(checks, service, case, args, "unreachable")
    return rows


def failure_case(checks, service, case, args, tag):
    status, body = service.submit(case, f"e2e-{tag}-{case['case_id']}")
    if not checks.add("failures", f"{tag}:admitted", status == 202, "ระบบรับเคสเข้าคิว", "admitted", status):
        return []
    job = service.wait(body["job_id"], args.job_timeout_s)
    row = check_case(checks, "failures", service, case, job, args.model_id,
                     expect_ai=("unavailable", "provider_unavailable", 2))
    review = (job.get("result") or {}).get("review") or {}
    checks.add("failures", f"{tag}:rules_kept", review.get("suggestion_source", "").startswith("rules:")
               and review.get("suggested_category") in CATEGORIES,
               "ข้อเสนอของกฎยังอยู่ให้คนตัดสิน" + (" (AI ตอบไม่ทันเวลา)" if tag == "timeout" else " (เครื่องรันโมเดลไม่ตอบ)"),
               "the rules' suggestion still reaches the person", review.get("suggested_category"))
    return [{**row, "scenario": tag}]


def phase_faults(checks, workdir, args, case, control):
    rows = []
    chosen = [fault for fault in FAULTS if not args.faults or fault[0] in args.faults.split(",")]
    with Service(workdir, "faults", model_id=args.model_id, llm_base_url=args.llm_base_url,
                 timeout_s=args.timeout_s) as service:
        for mode, count, status_wanted, reason, attempts in chosen:
            control(mode, count, 0.0)
            try:
                status, body = service.submit(case, f"e2e-fault-{mode}")
                if not checks.add("faults", f"{mode}:admitted", status == 202, "รับเคส", "admitted", status):
                    continue
                job = service.wait(body["job_id"], args.job_timeout_s)
                row = check_case(checks, "faults", service, dict(case, case_id=f"{case['case_id']}~{mode}"), job,
                                 args.model_id, expect_ai=(status_wanted, reason, attempts))
                rows.append({**row, "scenario": mode})
            finally:
                control("ok", -1, 0.0)
    return rows


def fake_control(llm_base_url):
    root = server_root(llm_base_url)

    def control(mode, count, delay_s):
        status, _body, _ = http("POST", root + "/_control", {"mode": mode, "count": count, "delay_s": delay_s})
        if status != 200:
            raise RuntimeError("the fake model server did not accept the fault")
    return control


# -- the report -------------------------------------------------------------------------------------------

def totals(rows):
    answered = [r for r in rows if r["ai_status"] == "ok"]
    seconds = [r["seconds"] for r in rows if r.get("seconds") is not None]
    latency = [r["latency_ms"] for r in answered if r["latency_ms"]]
    labelled = [r for r in answered if r["set"] == "hard"]  # only the hard set marks needs_person
    return {"cases": len(rows), "answered": len(answered),
            "category_right": sum(r["ai"] == r["expected"] for r in answered),
            "attention_labelled": len(labelled),
            "attention_right": sum((r["attention"] != "none") == r["needs_person"] for r in labelled),
            "raised": sum(r["priority"] == "elevated" for r in rows),
            "needs_person": sum(r["needs_person"] for r in rows),
            "needs_person_raised": sum(r["needs_person"] and r["priority"] == "elevated" for r in rows),
            "rules_right": sum(r["rules"] == r["expected"] for r in rows),
            "seconds_median": round(statistics.median(seconds), 2) if seconds else None,
            "seconds_max": max(seconds) if seconds else None,
            "latency_ms_median": round(statistics.median(latency), 1) if latency else None}


def markdown(document):
    checks = document["checks"]
    failed = [c for c in checks if not c["ok"]]
    t = document["totals"]
    lines = ["## ทดสอบปลายทางกับโมเดลในเครื่อง (end-to-end, case_triage.v2)", "",
             f"**{'ผ่านทุกข้อ' if not failed else f'ไม่ผ่าน {len(failed)} ข้อ'}** · ตรวจ {len(checks)} ข้อ · "
             f"รุ่น `{document['model_id']}` · ใช้เวลา {document['seconds']:.0f} วินาที", "",
             "บริการจริง (API + ตัวรันงาน + Core) บนเครื่องนี้ ใช้ผู้ให้บริการ `local` ชี้ไปที่เครื่องรันโมเดลบน 127.0.0.1 "
             "ทุกเคสเป็นข้อมูลสมมุติ ไม่มีข้อความออกไปบริษัท AI ใด", ""]
    if t["cases"]:
        lines += ["| สิ่งที่วัด | ผล |", "|---|---|",
                  f"| เคสที่ไปรอคนตัดสิน | {sum(r['status'] == 'REVIEW_REQUIRED' for r in document['cases'])}/{t['cases']} |",
                  f"| AI ตอบได้ (ผ่าน JSON schema) | {t['answered']}/{t['cases']} |",
                  f"| AI จัดหมวดตรงเฉลย (ข้อมูลประกอบ ไม่ใช่ความแม่นยำ) | {t['category_right']}/{t['answered']} |",
                  f"| AI ชี้ \"ต้องให้คนดูก่อน\" ตรงเฉลย (เฉพาะชุดเคสยากที่มีเฉลยนี้) | "
                  f"{t['attention_right']}/{t['attention_labelled']} |",
                  f"| เคสที่ต้องให้คนดูก่อน ที่ถูกยกขึ้นจริง | {t['needs_person_raised']}/{t['needs_person']} |",
                  f"| กฎจัดหมวดตรงเฉลย | {t['rules_right']}/{t['cases']} |",
                  f"| เวลาต่อเคส ตั้งแต่ส่งจนรอคนตัดสิน: กลาง / สูงสุด | {t['seconds_median']} / {t['seconds_max']} วินาที |",
                  f"| เวลาตอบของ AI (กลาง) | {t['latency_ms_median']} ms |", ""]
    server = document.get("server") or {}
    if server:
        lines += [f"เครื่องรันโมเดล: ไฟล์ `{server.get('model_path_name')}` · slots {server.get('total_slots')} · "
                  f"chat template SHA-256 `{(server.get('chat_template_sha256') or '')[:12]}` "
                  f"({server.get('chat_template_chars')} ตัวอักษร) · build `{server.get('build_info')}`", ""]
    by_phase = {}
    for check in checks:
        by_phase.setdefault(check["phase"], []).append(check)
    names = {"service": "บริการกับเคสปกติ", "decide": "คนตัดสินและงานบันทึกผล", "failures": "เมื่อ AI ไม่ตอบหรือช้าเกิน",
             "faults": "เมื่อเครื่องรันโมเดลตอบผิดรูป (จำลอง)"}
    lines += ["| ส่วน | ผ่าน |", "|---|---|"]
    for phase, items in by_phase.items():
        lines.append(f"| {names.get(phase, phase)} | {sum(c['ok'] for c in items)}/{len(items)} |")
    if failed:
        lines += ["", "### ข้อที่ไม่ผ่าน (failed checks)", ""]
        lines += [f"- `{c['id']}` {c['th']} (*{c['en']}*): {c['detail']}" for c in failed[:40]]
    if document["cases"]:
        lines += ["", "<details><summary>รายเคส (per case)</summary>", "",
                  "| เคส | เฉลย | กฎ | AI | attention | ความมั่นใจ | ลำดับ | วินาที |", "|---|---|---|---|---|---|---|---|"]
        for r in document["cases"]:
            lines.append(f"| `{r['case_id']}` | {r['expected']}{' · ต้องให้คนดู' if r['needs_person'] else ''} | "
                         f"{r['rules']} | {r['ai'] or r['ai_status'] + ':' + str(r['ai_reason'])} | {r['attention']} | "
                         f"{r['confidence']} | {r['priority']} | {r.get('seconds')} |")
        lines += ["", "</details>"]
    lines += ["", "_Synthetic cases; the categories above describe this model file on these few cases, not accuracy._", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--llm-base-url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--model-id", required=True, help="<name>:<first 12 hex digits of the file's SHA-256>")
    parser.add_argument("--model-file", help="the model file the server opened (checked by name, and re-hashed)")
    parser.add_argument("--model-sha256", help="the pinned SHA-256 of --model-file")
    parser.add_argument("--phases", default="service,failures")
    parser.add_argument("--cases", choices=("full", "quick"), default="full")
    parser.add_argument("--timeout-s", type=float, default=300.0, help="the client's wait for one answer")
    parser.add_argument("--short-timeout-s", type=float, default=0.2, help="the timeout phase's wait")
    parser.add_argument("--job-timeout-s", type=float, default=900.0)
    parser.add_argument("--fake-control", action="store_true", help="the model server is tests/fake_llama_server.py")
    parser.add_argument("--faults", default="", help="only these faults, comma-separated (default: all of FAULTS)")
    parser.add_argument("--workdir", help="keep the data folders and logs here (default: a temporary folder)")
    parser.add_argument("--summary")
    parser.add_argument("--json")
    args = parser.parse_args(argv)
    phases = [p.strip() for p in args.phases.split(",") if p.strip()]
    unknown = set(phases) - {"service", "failures", "faults"}
    if unknown or ("faults" in phases and not args.fake_control):
        parser.error("phases are service, failures and faults; faults needs --fake-control")
    if args.model_sha256 and not args.model_file:
        parser.error("--model-sha256 needs --model-file")
    if set(filter(None, args.faults.split(","))) - {fault[0] for fault in FAULTS}:
        parser.error("--faults names a fault that does not exist: " + ", ".join(fault[0] for fault in FAULTS))
    cases = load_cases(SERVICE_CASES if args.cases == "full" else QUICK_CASES)
    control = fake_control(args.llm_base_url) if args.fake_control else None
    checks, started = Checks(), time.monotonic()
    document = {"schema": "neuron-flow-local-e2e-v1", "model_id": args.model_id, "phases": phases, "cases": [],
                "scenarios": []}
    temporary = None if args.workdir else tempfile.TemporaryDirectory(prefix="neuron-local-e2e-")
    workdir = args.workdir or temporary.name
    try:
        if "service" in phases:
            report = phase_service(checks, workdir, args, cases)
            document.update(cases=report["cases"], decisions=report["decisions"], server=report.get("server"))
        if "failures" in phases:
            document["scenarios"] += phase_failures(checks, workdir, args, cases[0], control)
        if "faults" in phases:
            document["scenarios"] += phase_faults(checks, workdir, args, cases[0], control)
    except Exception as exc:  # report what broke; the class and our own message, never a key
        checks.add("run", "completed", False, "การทดสอบรันจนจบ", "the check ran to the end",
                   f"{type(exc).__name__}: {str(exc)[:200]}")
    finally:
        if temporary:
            temporary.cleanup()
    document.update(seconds=round(time.monotonic() - started, 1), checks=checks.items, totals=totals(document["cases"]),
                    failed=len(checks.failed))
    text = markdown(document)
    print(text)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as stream:
            stream.write(text + "\n")
    if args.json:
        Path(args.json).write_text(json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 1 if checks.failed else 0


if __name__ == "__main__":
    sys.exit(main())
