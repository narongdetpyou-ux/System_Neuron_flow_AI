"""Robustness benchmark, stage 1 (docs/benchmarking.md): hard edge cases against the deterministic logic and Core.

Run:
    python -m tests.robustness.bench --summary summary.md --out robustness.json \\
        --compare-with tests/baselines/robustness_v1.json
    python -m tests.robustness.bench --write-baseline tests/baselines/robustness_v1.json
    python -m tests.robustness.bench --layers intake,rules            # a subset, for a quick look
    python -m tests.robustness.bench --export-golden tests/robustness/triage_edge_golden_v1.json

Flow:
1. load the hand-written set (``synthetic_v1.json``) and the open-dataset extract (``open_extract_v1.json``);
2. run every item through its layer and check what it expects, plus the promises every item of that layer
   must keep (for example: bad input never gets a server error; masking twice changes nothing; a parsed AI
   answer can always be stored by Core);
3. sweep the open corpora (Big List of Naughty Strings, JSONTestSuite) through the layers with those promises;
4. write a JSON report and a Thai/English markdown summary (shown on the GitHub Actions run page);
5. with ``--compare-with``: exit 3 when any item's outcome differs from the baseline (the gate). A fix or a
   new failure both change the outcome, so the same pull request regenerates the baseline and says why.

Layers: ``intake`` (the HTTP API in memory, no sockets), ``rules`` (v1 keyword rules), ``masking`` (personal
data before AI calls), ``ai_reply`` (what the gateway does with odd model replies), ``core`` (Core's spec and
JSON contracts) and ``e2e`` (whole jobs through Core's child processes, with the offline mock AI or a local
fake of the Typhoon HTTP API). Nothing here calls a real AI service or the internet.
"""

import argparse
import base64
import hashlib
import json
import logging
import os
import platform
import sys
import tempfile
import time
import unicodedata
import zlib
from datetime import datetime, timezone
from pathlib import Path

from neuron_flow import Runtime
from neuron_flow.model import SpecError, decode, encode, fingerprint, normalize_spec

from app.api.routes import ApiApp, Request
from app.domains.case_triage.agents import classify
from app.domains.case_triage.contracts import CATEGORIES, QUEUE_FOR
from app.domains.case_triage.workflow import build_workflow
from app.domains.study_guide.library import load_library
from app.eval.common import git_sha
from app.llm import InvalidModelOutput, LLMConfig, load_prompt
from app.llm.gateway import TEXT_LIMIT, parse_answer
from app.llm.providers.openai_compat import answer_text
from app.llm.redaction import KINDS, mask
from app.persistence import QueueStore
from app.services.workflows import CATALOG
from tests.fake_openai import FakeServer, completion
from tests.service_fixtures import KEY, settings

HERE = Path(__file__).resolve().parent
SYNTHETIC = HERE / "synthetic_v1.json"
OPEN_EXTRACT = HERE / "open_extract_v1.json"
GOLDEN = HERE / "triage_edge_golden_v1.json"
LAYERS = ("intake", "rules", "masking", "ai_reply", "core", "e2e")
SEVERITIES = ("bug", "gap", "info")
LAYER_TH = {"intake": "ด่านรับเคส (API)", "rules": "กฎคำสำคัญ v1", "masking": "การปิดข้อมูลส่วนตัว",
            "ai_reply": "การตรวจคำตอบ AI", "core": "สัญญาของ Core", "e2e": "ทั้งระบบผ่าน Core"}
SEVERITY_TH = {"bug": "ปัญหาร้ายแรง (bug)", "gap": "จุดอ่อน (gap)", "info": "ข้อสังเกต (info)"}
CONTROL = set(range(0x00, 0x20)) | {0x7F, 0x2028, 0x2029}
CANARY = Path("/tmp/blns.fail")  # the file BLNS's shell-injection strings try to create
FAKE_KEY = "typhoon-test-robustness-benchmark"  # a deliberately fake key (allowed by the secret scan)
TYPHOON_MODEL = "typhoon-v2.5-30b-a3b-instruct"
MAX_LISTED = 40


# --- small helpers --------------------------------------------------------------------------------------------

def expand(value):
    """``{"$repeat": s, "count": n}``, ``{"$repeat": s, "count_chars": n, "suffix": x}`` and ``{"$concat": [...]}``
    let the data file describe big inputs in a few bytes."""
    if isinstance(value, dict):
        if "$repeat" in value:
            unit = value["$repeat"]
            if "count_chars" in value:
                suffix = value.get("suffix", "")
                body = (unit * (value["count_chars"] // len(unit) + 1))[:value["count_chars"] - len(suffix)]
                return body + suffix
            return unit * value["count"]
        if "$concat" in value:
            return "".join(expand(part) for part in value["$concat"])
        return {key: expand(item) for key, item in value.items()}
    if isinstance(value, list):
        return [expand(item) for item in value]
    return value


def safe(value):
    """A report-safe copy: lone surrogates and invisible characters become visible ``\\uXXXX`` text, so the
    report is valid UTF-8 and two runs compare equal."""
    if isinstance(value, str):
        out = []
        for ch in value:
            category = unicodedata.category(ch)
            if category in ("Cs", "Cc", "Cf", "Zl", "Zp") and ch not in "\n":
                out.append(f"\\u{ord(ch):04x}")
            else:
                out.append(ch)
        return "".join(out)
    if isinstance(value, dict):
        return {safe(key): safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe(item) for item in value]
    return value


def short(value, limit=160):
    text = safe(value) if isinstance(value, str) else json.dumps(safe(value), ensure_ascii=False)
    return text if len(text) <= limit else text[:limit - 1] + "…"


def has_format_chars(text):
    return any(unicodedata.category(ch) == "Cf" for ch in text)


def has_control_chars(text):
    return any(ord(ch) in CONTROL for ch in text)


def storable(value):
    try:
        encode(value)
        return True
    except SpecError:
        return False


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def thai(text):
    return any("฀" <= ch <= "๿" for ch in text)


# --- loading --------------------------------------------------------------------------------------------------

def load_sets(synthetic=SYNTHETIC, open_extract=OPEN_EXTRACT):
    synthetic_doc = json.loads(Path(synthetic).read_text(encoding="utf-8"))
    open_doc = json.loads(Path(open_extract).read_text(encoding="utf-8"))
    if synthetic_doc.get("schema") != "neuron-flow-robustness-synthetic-v1":
        raise ValueError("synthetic set: unexpected schema")
    if open_doc.get("schema") != "neuron-flow-robustness-open-v1":
        raise ValueError("open extract: unexpected schema")
    items, seen = [], set()
    for entry in synthetic_doc["items"]:
        if entry["id"] in seen or entry["layer"] not in LAYERS or entry["severity"] not in SEVERITIES:
            raise ValueError(f"synthetic set: invalid or repeated item {entry.get('id')}")
        seen.add(entry["id"])
        items.append({**entry, "source": "synthetic"})
    for entry in open_doc["labelled"]:
        if entry["id"] in seen or entry["label"] not in CATEGORIES:
            raise ValueError(f"open extract: invalid or repeated item {entry.get('id')}")
        seen.add(entry["id"])
        items.append({"id": entry["id"], "layer": "rules", "source": entry["source"],
                      "title_th": f"คำขอจาก {entry['source'].upper()} ({entry['source_intent']})",
                      "title_en": f"{entry['source']} request ({entry['source_intent']})",
                      "checklist": "MFT", "capability": f"open_{entry['source']}", "lang": "en", "severity": "gap",
                      "input": {"summary": entry["text"]},
                      "expect": {"category": entry["label"]}, "selected_by": entry["selected_by"]})
    corpora = {"blns": open_doc["corpora"]["blns"],
               "jsontestsuite": [{**f, "data": zlib.decompress(base64.b64decode(f["data_z"]))}
                                 for f in open_doc["corpora"]["jsontestsuite"]]}
    for f in corpora["jsontestsuite"]:
        if hashlib.sha256(f["data"]).hexdigest() != f["sha256"]:
            raise ValueError(f"open extract: {f['name']} does not match its SHA-256")
    return {"items": items, "corpora": corpora,
            "sets": {"synthetic": {"name": SYNTHETIC.name, "sha256": file_sha256(synthetic), "items":
                                   len(synthetic_doc["items"])},
                     "open": {"name": OPEN_EXTRACT.name, "sha256": file_sha256(open_extract),
                              "labelled": len(open_doc["labelled"]), "blns": len(corpora["blns"]),
                              "jsontestsuite": len(corpora["jsontestsuite"]),
                              "sources": [{k: s[k] for k in ("id", "name", "repo", "commit", "license")}
                                          for s in open_doc["sources"]]}}}


# --- layer: intake (the HTTP API, in memory) ------------------------------------------------------------------

class Intake:
    def __init__(self, workdir):
        cfg = settings(Path(workdir), submit_per_minute=100_000, max_queued=100_000)
        self.store = QueueStore(cfg.queue_db)
        self.store.migrate()
        self.app = ApiApp(cfg, self.store)
        self.headers = {"content-type": "application/json", "authorization": f"Bearer {KEY}"}

    def post(self, body, content_type="application/json"):
        headers = dict(self.headers)
        if content_type is None:
            headers.pop("content-type")
        else:
            headers["content-type"] = content_type
        response = self.app.handle(Request("POST", "/v1/jobs", {}, headers, body, "robustness"))
        payload = json.loads(response.body) if response.body else {}
        return response.status, payload

    def stored_input_ok(self, payload):
        job = self.store.get(payload.get("job_id", ""))
        return job is not None and storable(job["input"])


def default_body(item_id, inp):
    workflow_type = inp.get("workflow_type", "case_triage.v2")
    if workflow_type == "study_guide.v1":
        case = {"message": expand(inp.get("message", "learn prompt writing"))}
    else:
        case = {"case_id": inp.get("case_id", "RB-CASE-1"), "summary": expand(inp.get("summary", "I cannot upload a file"))}
    case.update(inp.get("extra_input", {}))
    body = {"workflow_type": workflow_type, "idempotency_key": inp.get("idempotency_key", "rb-" + item_id.lower()),
            "input": case}
    body.update(inp.get("extra_top", {}))
    return body


def intake_bytes(item_id, inp):
    if "body_b64" in inp:
        return base64.b64decode(inp["body_b64"])
    if "body_text" in inp:
        return expand(inp["body_text"]).encode("utf-8")
    if "body" in inp:
        return json.dumps(inp["body"]).encode("utf-8")
    body = default_body(item_id, inp)
    if inp.get("encoding") == "utf-16":
        return json.dumps(body).encode("utf-16")
    data = json.dumps(body).encode("utf-8")
    if inp.get("encoding") == "utf-8-sig":
        return b"\xef\xbb\xbf" + data
    if "pad_to" in inp:
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        data += b" " * (inp["pad_to"] - len(data))
    return data


def run_intake(item, intake):
    inp, expect = item["input"], item["expect"]
    problems = []
    content_type = inp.get("content_type", "application/json")
    if "sequence" in inp:
        status = payload = None
        for step in inp["sequence"]:
            status, payload = intake.post(intake_bytes(item["id"], {**inp, **step, "idempotency_key": "rb-seq-" + item["id"].lower()}),
                                          content_type)
    else:
        status, payload = intake.post(intake_bytes(item["id"], inp), content_type)
    error = payload.get("error")
    if status >= 500:
        problems.append(f"server error {status} ({error}) for a request that is the client's mistake")
    if "status" in expect and status != expect["status"]:
        problems.append(f"expected status {expect['status']}, got {status} ({error})")
    if "status_in" in expect and status not in expect["status_in"]:
        problems.append(f"expected one of {expect['status_in']}, got {status} ({error})")
    if "error" in expect and status < 500 and error != expect["error"]:
        problems.append(f"expected error {expect['error']}, got {error}")
    if status == 202 and not intake.stored_input_ok(payload):
        problems.append("accepted, but the stored input cannot be serialized by Core")
    if item.get("observe") == "status":  # the error code depends on the Python version (JSON nesting limit)
        return {"status": status}, problems
    return {"status": status, "error": error}, problems


# --- layer: rules ---------------------------------------------------------------------------------------------

def rules_category(summary):
    spec = build_workflow("robustness", {"case_id": "RB-CASE-1", "summary": summary})
    first = classify({"input": spec["input"]})
    second = classify({"input": spec["input"]})
    return first, second


def run_rules(item, observed_by_id):
    summary = expand(item["input"]["summary"])
    problems = []
    try:
        first, second = rules_category(summary)
    except SpecError as exc:
        return {"category": None, "refused": str(exc)[:80]}, ["the case does not pass the input contract"]
    if first != second:
        problems.append("two runs gave different answers")
    if first["category"] not in CATEGORIES or first["queue"] != QUEUE_FOR[first["category"]]:
        problems.append(f"invalid rules output {first}")
    expected = item["expect"]["category"]
    if first["category"] != expected:
        problems.append(f"expected {expected}, the rules said {first['category']}")
    base = item["expect"].get("same_as")
    if base and observed_by_id.get(base, {}).get("category") not in (None, first["category"]):
        problems.append(f"answer differs from {base} (same meaning): {observed_by_id[base]['category']} vs "
                        f"{first['category']}")
    return {"category": first["category"]}, problems


# --- layer: masking -------------------------------------------------------------------------------------------

def run_masking(item):
    text, expect = item["input"]["text"], item["expect"]
    problems = []
    masked = mask(text)
    again = mask(masked.text)
    if again.text != masked.text:
        problems.append("masking twice changed the text again")
    if not set(masked.counts) <= set(KINDS):
        problems.append(f"unknown kinds {sorted(set(masked.counts) - set(KINDS))}")
    if masked.counts != expect["counts"]:
        problems.append(f"expected masked {expect['counts'] or 'nothing'}, got {masked.counts or 'nothing'}")
    for piece in expect.get("must_not_contain", []):
        if piece in masked.text:
            problems.append(f"'{piece}' still reaches the AI")
    for piece in expect.get("must_keep", []):
        if piece not in masked.text:
            problems.append(f"'{piece}' was masked but is not personal data")
    return {"counts": masked.counts, "text": safe(masked.text)}, problems


# --- layer: ai_reply ------------------------------------------------------------------------------------------

def parse_reply(prompt_id, reply, via):
    schema = load_prompt(prompt_id).output_schema
    text = answer_text(reply) if via == "answer_text" else reply
    try:
        return "ok", parse_answer(text, schema), None
    except InvalidModelOutput as exc:
        return "invalid", None, str(exc)[:80]
    except Exception as exc:  # anything else breaks the gateway's promise
        return "crash", None, type(exc).__name__


def answer_promises(answer, schema):
    problems = []
    for name, value in answer.items():
        spec = schema["properties"][name]
        if not isinstance(value, str):
            problems.append(f"{name} is not text")
        elif "enum" in spec and value not in spec["enum"]:
            problems.append(f"{name} is outside its fixed choices")
        elif "enum" not in spec and (len(value) > TEXT_LIMIT or has_control_chars(value)):
            problems.append(f"{name} is longer than {TEXT_LIMIT} or has control characters")
    if not storable(answer):
        problems.append("the accepted answer cannot be stored by Core (the whole case would fail)")
    return problems


def run_ai_reply(item):
    inp, expect = item["input"], item["expect"]
    outcome, answer, detail = parse_reply(inp["prompt"], expand(inp["reply"]), inp.get("via", "answer_text"))
    problems = []
    if outcome == "crash":
        problems.append(f"raised {detail} instead of InvalidModelOutput")
    if outcome == "ok":
        problems += answer_promises(answer, load_prompt(inp["prompt"]).output_schema)
    if outcome != expect["outcome"]:
        problems.append(f"expected {expect['outcome']}, got {outcome}")
    if outcome == "ok":
        for name, value in expect.get("fields", {}).items():
            if answer.get(name) != value:
                problems.append(f"{name}: expected {short(value)}, got {short(answer.get(name))}")
        if "max_text" in expect and any(len(v) > expect["max_text"] for v in answer.values()):
            problems.append("a text field is longer than allowed")
        if expect.get("no_format_chars") and any(has_format_chars(v) for v in answer.values()):
            problems.append("invisible or direction-changing characters reach the reviewer")
        if expect.get("no_control_chars") and any(has_control_chars(v) for v in answer.values()):
            problems.append("control characters reach the reviewer")
    return {"outcome": outcome, "detail": safe(detail) if outcome == "crash" else None,
            "answer": safe(answer)}, problems


# --- layer: core ----------------------------------------------------------------------------------------------

KNOWN_AGENTS = {"agent.a"}


def core_spec(inp):
    if inp.get("generate") == "chain":
        steps = [{"id": f"s{i}", "agent": "agent.a", **({"depends_on": [f"s{i - 1}"]} if i else {})}
                 for i in range(inp["steps"])]
        return {"job_id": "job-chain", "input": {}, "steps": steps}
    spec = expand(inp["spec"])
    step = spec["steps"][0] if spec.get("steps") and isinstance(spec["steps"][0], dict) else None
    if "set_nan" in inp:
        step[inp["set_nan"]] = float("nan")
    if "params_bytes" in inp:
        step["params"] = {"blob": "x" * inp["params_bytes"]}
    if "params_bigint_digits" in inp:
        step["params"] = {"n": 10 ** (inp["params_bigint_digits"] - 1)}
    return spec


def run_core(item):
    inp, expect = item["input"], item["expect"]
    problems = []
    error = None
    try:
        if inp["op"] == "normalize_spec":
            normalize_spec(core_spec(inp), KNOWN_AGENTS)
            outcome = "ok"
        elif inp["op"] == "decode":
            if "text" in inp:
                data = inp["text"]
            elif "data_text" in inp:
                data = expand(inp["data_text"]).encode("utf-8")
            elif "generate_bytes" in inp:
                data = b'"' + b"x" * (inp["generate_bytes"] - 2) + b'"'
            else:
                data = base64.b64decode(inp["data_b64"])
            decode(data)
            outcome = "ok"
        elif inp["op"] == "fingerprint_pair":
            outcome = "same" if fingerprint(inp["a"]) == fingerprint(inp["b"]) else "different"
        else:
            raise ValueError(f"unknown op {inp['op']}")
    except SpecError as exc:
        outcome, error = "SpecError", type(exc).__name__
    except Exception as exc:
        outcome, error = "crash", type(exc).__name__
        problems.append(f"raised {error} instead of SpecError")
    if outcome != expect["outcome"] and outcome != "crash":
        problems.append(f"expected {expect['outcome']}, got {outcome}")
    return {"outcome": outcome, "error": error}, problems


# --- layer: e2e (whole jobs through Core) ---------------------------------------------------------------------

def fake_reply(spec):
    if "body" in spec:
        return (spec["status"], spec["body"])
    if "raw" in spec:
        return (spec["status"], spec["raw"])
    return (spec["status"], completion(spec["content"], finish_reason=spec.get("finish_reason", "stop"),
                                       refusal=spec.get("refusal")))


def run_job(runtime, workflow, job_id, normalized, config):
    runtime.submit(workflow.build_spec(job_id, normalized, config))
    snapshot = runtime.run(job_id)
    stored = runtime.store.job(job_id)["spec"]["input"]
    return snapshot, stored == normalized


def e2e_observed(workflow, snapshot, preserved):
    steps = snapshot["steps"]
    failed = [step_id for step_id, step in steps.items() if step["status"] == "FAILED"]
    final = steps[workflow.final_step].get("output") if steps[workflow.final_step]["status"] == "SUCCEEDED" else None
    observed = {"job": snapshot["status"], "input_preserved": preserved, "failed_step": failed[0] if failed else None,
                "error_type": ((steps[failed[0]].get("error") or {}).get("type") if failed else None)}
    if workflow.name.startswith("case_triage") and final:
        observed["decision"] = final.get("decision")
        second = final.get("second_opinion")
        if second:
            observed["second_opinion"] = second.get("status")
            observed["reason"] = second.get("reason")
            observed["rationale"] = safe(second.get("rationale")) if second.get("rationale") else None
    if workflow.name == "study_guide.v1" and final:
        urls = {r.url for r in load_library("v1").resources}
        observed["status"] = final.get("status")
        observed["steps"] = len(final.get("steps", []))
        observed["links_from_library"] = all(step.get("url") in urls for step in final.get("steps", []))
    return observed, final


def check_e2e(expect, observed, final):
    problems = []
    if observed["job"] != expect["job"]:
        why = f" (step {observed['failed_step']} failed: {observed['error_type']})" if observed["failed_step"] else ""
        problems.append(f"expected the job to end {expect['job']}, it ended {observed['job']}{why}")
    if observed["job"] == "SUCCEEDED" and not observed["input_preserved"]:
        problems.append("the stored case text differs from what was admitted")
    if "decision" in expect and observed.get("decision") != expect["decision"]:
        problems.append(f"expected decision {expect['decision']}, got {observed.get('decision')}")
    if "second_opinion" in expect and observed.get("second_opinion") != expect["second_opinion"]:
        problems.append(f"expected the AI view {expect['second_opinion']}, got {observed.get('second_opinion')}")
    if "second_opinion_in" in expect and observed.get("second_opinion") not in expect["second_opinion_in"]:
        problems.append(f"expected the AI view to be one of {expect['second_opinion_in']}, got "
                        f"{observed.get('second_opinion')}")
    if "reason" in expect and observed.get("reason") != expect["reason"]:
        problems.append(f"expected reason {expect['reason']}, got {observed.get('reason')}")
    if expect.get("rationale_no_format_chars") and final and has_format_chars(
            (final.get("second_opinion") or {}).get("rationale") or ""):
        problems.append("invisible or direction-changing characters reach the reviewer")
    if "failed_step" in expect and observed.get("failed_step") != expect["failed_step"]:
        problems.append(f"expected step {expect['failed_step']} to fail, got {observed.get('failed_step')}")
    if "max_steps" in expect and observed.get("steps", 0) > expect["max_steps"]:
        problems.append(f"more than {expect['max_steps']} study resources")
    if expect.get("links_from_library") and observed.get("links_from_library") is False:
        problems.append("a link outside the verified library")
    if expect.get("canary_absent") and CANARY.exists():
        problems.append(f"{CANARY} exists: some text was run as a shell command")
    return problems


def run_e2e_items(items, workdir):
    """Mock-AI jobs share one Runtime; each fake-Typhoon job gets its own fake server and Runtime."""
    results = {}
    mock = LLMConfig.from_env({})
    os.environ["TYPHOON_API_KEY"] = FAKE_KEY  # children inherit it; it only ever reaches the local fake server
    mock_items = [i for i in items if i["input"].get("provider", "mock") == "mock"]
    fake_items = [i for i in items if i["input"].get("provider") == "fake_typhoon"]
    if mock_items:
        names = sorted({i["input"]["workflow"] for i in mock_items})
        agents = {}
        for name in names:
            for definition in CATALOG[name].agents(mock):
                agents[definition.name] = definition
        with Runtime(Path(workdir) / "e2e-mock", agents=list(agents.values()), max_workers=3) as runtime:
            for item in mock_items:
                results[item["id"]] = _one_job(runtime, item, mock)
    for item in fake_items:
        with FakeServer([fake_reply(r) for r in item["input"]["replies"]]) as fake:
            config = LLMConfig(provider="typhoon", model=TYPHOON_MODEL, base_url=fake.base_url)
            workflow = CATALOG[item["input"]["workflow"]]
            with Runtime(Path(workdir) / f"e2e-{item['id'].lower()}", agents=workflow.agents(config),
                         max_workers=3) as runtime:
                results[item["id"]] = _one_job(runtime, item, config)
    return results


def _one_job(runtime, item, config):
    inp = item["input"]
    workflow = CATALOG[inp["workflow"]]
    raw = {"message": expand(inp["message"])} if workflow.name == "study_guide.v1" else \
        {"case_id": "RB-" + item["id"].split("-")[-1], "summary": expand(inp["summary"])}
    try:
        normalized = workflow.check_input(raw)
    except SpecError as exc:
        return {"job": "REFUSED", "refused": str(exc)[:80]}, ["refused at admission, so it never reached Core"]
    snapshot, preserved = run_job(runtime, workflow, "rb_" + item["id"].lower().replace("-", "_"), normalized, config)
    observed, final = e2e_observed(workflow, snapshot, preserved)
    return observed, check_e2e(item["expect"], observed, final)


# --- sweeps over the open corpora -----------------------------------------------------------------------------

def sweep(sweep_id, layer, corpus, title_th, title_en, check):
    violations, notes = [], {}
    for index, entry in enumerate(corpus):
        problem, note = check(index, entry)
        if problem:
            violations.append({"index": index, "name": entry["name"] if isinstance(entry, dict) else None,
                               "problem": problem})
        if note:
            notes[note] = notes.get(note, 0) + 1
    return {"id": sweep_id, "layer": layer, "title_th": title_th, "title_en": title_en, "checked": len(corpus),
            "violations": violations, "notes": dict(sorted(notes.items()))}


def run_sweeps(corpora, layers, workdir):
    blns, suite = corpora["blns"], corpora["jsontestsuite"]
    results = []
    if "intake" in layers:
        intake = Intake(Path(workdir) / "sweep-intake")

        def as_field(field, workflow_type):
            def check(index, text):
                inp = {"workflow_type": workflow_type, field: text, "idempotency_key": f"rb-blns-{field}-{index:04d}"}
                status, payload = intake.post(json.dumps(default_body("x", inp)).encode("utf-8"))
                if status >= 500:
                    return f"server error {status}", None
                if status not in (202, 400):
                    return f"unexpected status {status}", None
                if status == 202 and not intake.stored_input_ok(payload):
                    return "accepted but not storable", None
                return None, "accepted" if status == 202 else "refused"
            return check

        results.append(sweep("SWP-BLNS-INTAKE-CASE", "intake", blns, "ข้อความแปลก 515 แบบ เป็นข้อความเคส",
                             "BLNS strings as a case summary", as_field("summary", "case_triage.v2")))
        results.append(sweep("SWP-BLNS-INTAKE-STUDY", "intake", blns, "ข้อความแปลก 515 แบบ เป็นคำถามผู้ช่วยเรียน",
                             "BLNS strings as a study message", as_field("message", "study_guide.v1")))

        def raw_body(placement):
            def check(index, entry):
                data = entry["data"]
                if placement == "input":
                    data = (b'{"workflow_type":"case_triage.v2","idempotency_key":"rb-json-in-' + str(index).encode()
                            + b'","input":' + data + b"}")
                elif placement == "summary":
                    data = (b'{"workflow_type":"case_triage.v2","idempotency_key":"rb-json-sm-' + str(index).encode()
                            + b'","input":{"case_id":"C1","summary":' + data + b"}}")
                status, payload = intake.post(data)
                if status >= 500:
                    return f"server error {status} ({payload.get('error')})", None
                if status not in (400, 413):
                    return f"unexpected status {status}", None
                return None, f"{status} {payload.get('error')}"
            return check

        for placement, th in (("body", "ทั้งตัวคำขอ"), ("input", "ในช่อง input"), ("summary", "ในช่องข้อความเคส")):
            results.append(sweep(f"SWP-JSON-INTAKE-{placement.upper()}", "intake", suite,
                                 f"ไฟล์ทดสอบ JSON 318 ไฟล์ วาง{th}", f"JSONTestSuite files as the {placement}",
                                 raw_body(placement)))
    if "rules" in layers:
        def rules_check(index, text):
            try:
                first, second = classify({"input": {"summary": text.strip()}}), classify({"input": {"summary": text.strip()}})
            except Exception as exc:
                return f"raised {type(exc).__name__}", None
            if first != second or first["category"] not in CATEGORIES:
                return "invalid or unstable answer", None
            return None, first["category"]
        results.append(sweep("SWP-BLNS-RULES", "rules", blns, "ข้อความแปลก 515 แบบ ผ่านกฎคำสำคัญ",
                             "BLNS strings through the keyword rules", rules_check))
    if "masking" in layers:
        def mask_check(index, text):
            try:
                once = mask(text)
                twice = mask(once.text)
            except Exception as exc:
                return f"raised {type(exc).__name__}", None
            if twice.text != once.text:
                return "masking twice changed the text", None
            if not set(once.counts) <= set(KINDS):
                return "unknown kind", None
            return None, "masked" if once.counts else "unchanged"
        results.append(sweep("SWP-BLNS-MASK", "masking", blns, "ข้อความแปลก 515 แบบ ผ่านการปิดข้อมูลส่วนตัว",
                             "BLNS strings through masking", mask_check))
    if "ai_reply" in layers:
        schema = load_prompt("triage_classify_v1").output_schema

        def rationale_check(index, text):
            reply = json.dumps({"category": "other", "confidence": "low", "rationale": text})
            outcome, answer, detail = parse_reply("triage_classify_v1", reply, "answer_text")
            if outcome == "crash":
                return f"raised {detail}", None
            if outcome == "ok":
                broken = answer_promises(answer, schema)
                if broken:
                    return broken[0], None
                if not answer["rationale"].strip():
                    return None, "accepted with an empty rationale"
                if has_format_chars(answer["rationale"]):
                    return None, "accepted with invisible or direction characters"
                return None, "accepted"
            return None, "refused"
        results.append(sweep("SWP-BLNS-AI-RATIONALE", "ai_reply", blns, "ข้อความแปลก 515 แบบ เป็นเหตุผลในคำตอบ AI",
                             "BLNS strings as the AI's rationale", rationale_check))

        def reply_check(index, entry):
            try:
                text = entry["data"].decode("utf-8")
            except UnicodeDecodeError:
                return None, "skipped (not UTF-8 text)"
            outcome, answer, detail = parse_reply("triage_classify_v1", text, "answer_text")
            if outcome == "crash":
                return f"raised {detail}", None
            if outcome == "ok":
                return "a parser test file was accepted as an answer", None
            return None, "refused"
        results.append(sweep("SWP-JSON-AIREPLY", "ai_reply", suite, "ไฟล์ทดสอบ JSON 318 ไฟล์ เป็นคำตอบ AI",
                             "JSONTestSuite files as a model reply", reply_check))
    if "core" in layers:
        def decode_check(index, entry):
            try:
                value = decode(entry["data"])
            except SpecError:
                return None, f"{entry['expect']}: rejected"
            except Exception as exc:
                return f"raised {type(exc).__name__} instead of SpecError", None
            note = f"{entry['expect']}: accepted"
            if not storable(value):
                note += " (but Core cannot store the value)"
            return None, note
        results.append(sweep("SWP-JSON-CORE-DECODE", "core", suite, "ไฟล์ทดสอบ JSON 318 ไฟล์ ผ่านตัวอ่าน JSON ของ Core",
                             "JSONTestSuite files through Core's decode()", decode_check))

        def fingerprint_check(index, text):
            try:
                same = fingerprint({"summary": text}) == fingerprint({"summary": text})
            except Exception as exc:
                return f"raised {type(exc).__name__}", None
            return (None, "stable") if same else ("fingerprint changed between two calls", None)
        results.append(sweep("SWP-BLNS-CORE-FINGERPRINT", "core", blns, "ข้อความแปลก 515 แบบ ผ่านลายนิ้วมือของ Core",
                             "BLNS strings through Core's fingerprint()", fingerprint_check))
    return results


# --- the run --------------------------------------------------------------------------------------------------

def run(layers=LAYERS, sets=None):
    sets = sets or load_sets()
    started = time.monotonic()
    canary_before = CANARY.exists()
    if canary_before:
        CANARY.unlink()
    outcomes = {}
    items = [i for i in sets["items"] if i["layer"] in layers]
    with tempfile.TemporaryDirectory(prefix="neuron-robustness-") as workdir:
        logging.disable(logging.CRITICAL)  # the API logs every 500 with a traceback; the report lists them
        try:
            intake = Intake(Path(workdir) / "intake") if "intake" in layers else None
            observed_rules = {}
            for item in items:
                if item["layer"] == "intake":
                    outcomes[item["id"]] = run_intake(item, intake)
                elif item["layer"] == "rules":
                    outcomes[item["id"]] = run_rules(item, observed_rules)
                    observed_rules[item["id"]] = outcomes[item["id"]][0]
                elif item["layer"] == "masking":
                    outcomes[item["id"]] = run_masking(item)
                elif item["layer"] == "ai_reply":
                    outcomes[item["id"]] = run_ai_reply(item)
                elif item["layer"] == "core":
                    outcomes[item["id"]] = run_core(item)
            if "e2e" in layers:
                outcomes.update(run_e2e_items([i for i in items if i["layer"] == "e2e"], workdir))
            sweeps = run_sweeps(sets["corpora"], layers, workdir)
        finally:
            logging.disable(logging.NOTSET)
    rows = []
    for item in items:
        observed, problems = outcomes[item["id"]]
        rows.append({"id": item["id"], "layer": item["layer"], "source": item["source"],
                     "severity": item["severity"], "known": item.get("known"), "checklist": item["checklist"],
                     "capability": item["capability"], "title_th": item["title_th"], "title_en": item["title_en"],
                     "passed": not problems, "problems": [safe(p) for p in problems], "observed": safe(observed)})
    canary = CANARY.exists()
    return {"schema": "neuron-flow-robustness-report-v1",
            "provenance": {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           "git_sha": os.environ.get("GITHUB_SHA") or git_sha(), "python": platform.python_version(),
                           "layers": list(layers), "duration_s": round(time.monotonic() - started, 1),
                           "sets": sets["sets"]},
            "canary": {"path": str(CANARY), "existed_before": canary_before, "exists_after": canary},
            "metrics": metrics(rows, sweeps), "items": rows, "sweeps": sweeps}


def metrics(rows, sweeps):
    by_layer = {}
    for layer in LAYERS:
        subset = [r for r in rows if r["layer"] == layer]
        if not subset:
            continue
        failed = [r for r in subset if not r["passed"] and r["source"] == "synthetic"]
        open_failed = sum(1 for r in subset if not r["passed"] and r["source"] != "synthetic")
        by_layer[layer] = {"items": len(subset), "passed": len(subset) - len(failed) - open_failed,
                           "open_items": sum(1 for r in subset if r["source"] != "synthetic"), "open_failed": open_failed,
                           **{s: sum(1 for r in failed if r["severity"] == s) for s in SEVERITIES},
                           "sweeps": sum(1 for s in sweeps if s["layer"] == layer),
                           "sweep_checks": sum(s["checked"] for s in sweeps if s["layer"] == layer),
                           "sweep_violations": sum(len(s["violations"]) for s in sweeps if s["layer"] == layer)}
    open_rows = [r for r in rows if r["source"] in ("clinc150", "banking77")]
    synthetic = [r for r in rows if r["source"] == "synthetic"]
    return {"by_layer": by_layer,
            "items": len(rows), "passed": sum(1 for r in rows if r["passed"]),
            "synthetic_items": len(synthetic), "synthetic_passed": sum(1 for r in synthetic if r["passed"]),
            **{s: sum(1 for r in synthetic if not r["passed"] and r["severity"] == s) for s in SEVERITIES},
            "sweep_checks": sum(s["checked"] for s in sweeps),
            "sweep_violations": sum(len(s["violations"]) for s in sweeps),
            "open_rules_correct": {"numerator": sum(1 for r in open_rows if r["passed"]), "denominator": len(open_rows)}}


# --- baseline and gate ----------------------------------------------------------------------------------------

def baseline_of(report):
    return {"schema": "neuron-flow-robustness-baseline-v1", "sets": report["provenance"]["sets"],
            "items": {r["id"]: {"passed": r["passed"], "observed": r["observed"]} for r in report["items"]},
            "sweeps": {s["id"]: {"checked": s["checked"], "violations": s["violations"]} for s in report["sweeps"]}}


def write_baseline(report, path):
    data = baseline_of(report)
    lines = ["{", f' "schema": {json.dumps(data["schema"])},', f' "sets": {json.dumps(data["sets"], ensure_ascii=False)},',
             ' "items": {']
    entries = list(data["items"].items())
    for index, (item_id, value) in enumerate(entries):
        comma = "," if index < len(entries) - 1 else ""
        lines.append(f"  {json.dumps(item_id)}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}{comma}")
    lines.append(" },")
    lines.append(' "sweeps": {')
    sweeps = list(data["sweeps"].items())
    for index, (sweep_id, value) in enumerate(sweeps):
        comma = "," if index < len(sweeps) - 1 else ""
        lines.append(f"  {json.dumps(sweep_id)}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}{comma}")
    lines.append(" }")
    lines.append("}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def compare(report, baseline):
    """The list of differences between this run and a baseline (empty: the gate passes). A run of only some layers
    is compared on the items and sweeps it ran."""
    current = baseline_of(report)
    full = set(report["provenance"]["layers"]) == set(LAYERS)
    changes = []
    for part in ("synthetic", "open"):
        if current["sets"][part]["sha256"] != baseline["sets"][part]["sha256"]:
            changes.append(f"the {part} set changed (regenerate the baseline in the same pull request)")
    ids = sorted(set(baseline["items"]) | set(current["items"])) if full else sorted(current["items"])
    for item_id in ids:
        before, after = baseline["items"].get(item_id), current["items"].get(item_id)
        if before is None or after is None:
            changes.append(f"{item_id}: {'new item' if before is None else 'item missing from this run'}")
        elif before != after:
            what = "now passes" if after["passed"] and not before["passed"] else \
                "now fails" if before["passed"] and not after["passed"] else "answer changed"
            changes.append(f"{item_id}: {what} ({short(before['observed'], 70)} → {short(after['observed'], 70)})")
    for sweep_id in sorted(set(baseline["sweeps"]) | set(current["sweeps"])) if full else sorted(current["sweeps"]):
        before, after = baseline["sweeps"].get(sweep_id), current["sweeps"].get(sweep_id)
        if before != after:
            count = lambda value: len(value["violations"]) if value else "–"  # noqa: E731
            changes.append(f"{sweep_id}: violations changed ({count(before)} → {count(after)})")
    return changes


# --- summary --------------------------------------------------------------------------------------------------

def summary(report, changes=None):
    m = report["metrics"]
    sets = report["provenance"]["sets"]
    lines = ["## ด่านความทนทาน (Robustness benchmark ขั้นที่ 1)", "",
             f"ทดสอบ **{m['items']} รายการ** (เขียนเอง {m['synthetic_items']} + คำขอจากชุดข้อมูลเปิด "
             f"{m['items'] - m['synthetic_items']}) และกวาดข้อมูลเปิดอีก **{m['sweep_checks']:,} ครั้ง** "
             f"(ข้อความแปลก {sets['open']['blns']} แบบ และไฟล์ทดสอบ JSON {sets['open']['jsontestsuite']} ไฟล์)  ",
             f"เคสที่เขียนเอง ผ่าน **{m['synthetic_passed']}/{m['synthetic_items']}** · {SEVERITY_TH['bug']} **{m['bug']}** · "
             f"{SEVERITY_TH['gap']} **{m['gap']}** · {SEVERITY_TH['info']} **{m['info']}** · "
             f"ผิดสัญญาระหว่างกวาด **{m['sweep_violations']}**", "",
             "| ชั้น | รายการ | ผ่าน | bug | gap | info | กวาดข้อมูลเปิด | ผิดสัญญา |", "|---|---|---|---|---|---|---|---|"]
    for layer, row in m["by_layer"].items():
        items, passed = str(row["items"]), str(row["passed"])
        if row["open_items"]:  # synthetic + open requests, so the columns add up
            own = row["items"] - row["open_items"]
            open_passed = row["open_items"] - row["open_failed"]
            items = f"{own} + เปิด {row['open_items']}"
            passed = f"{row['passed'] - open_passed} + เปิด {open_passed}"
        lines.append(f"| {LAYER_TH[layer]} (`{layer}`) | {items} | {passed} | {row['bug']} | {row['gap']} | "
                     f"{row['info']} | {row['sweep_checks']:,} | {row['sweep_violations']} |")
    lines.append("")
    failed = [r for r in report["items"] if not r["passed"] and r["source"] == "synthetic"]
    for severity in SEVERITIES:
        subset = [r for r in failed if r["severity"] == severity]
        if not subset:
            continue
        lines += [f"### {SEVERITY_TH[severity]}: {len(subset)} รายการ", ""]
        for r in subset[:MAX_LISTED]:
            known = " *(เขียนไว้แล้วในเอกสารว่าจับไม่ได้)*" if r["known"] == "documented_limitation" else ""
            lines.append(f"- `{r['id']}` {r['title_th']}{known} — {short('; '.join(r['problems']), 200)}")
        if len(subset) > MAX_LISTED:
            lines.append(f"- … และอีก {len(subset) - MAX_LISTED} รายการ (ดูไฟล์รายงาน)")
        lines.append("")
    broken = [s for s in report["sweeps"] if s["violations"]]
    lines += ["### การกวาดข้อมูลเปิด (open-corpus sweeps)", "", "| กวาด | ตรวจ | ผิดสัญญา | ตัวอย่าง |", "|---|---|---|---|"]
    for s in report["sweeps"]:
        example = short(s["violations"][0]["problem"] + (f" ({s['violations'][0]['name']})" if s["violations"][0]["name"]
                                                          else f" (index {s['violations'][0]['index']})"), 90) \
            if s["violations"] else "–"
        lines.append(f"| {s['title_th']} | {s['checked']} | {len(s['violations'])} | {example} |")
    lines.append("")
    open_correct = m["open_rules_correct"]
    if open_correct["denominator"]:
        lines += ["### คำขอจากชุดข้อมูลเปิด (CLINC150, BANKING77) ผ่านกฎคำสำคัญ v1", "",
                  f"กฎตอบตรงกับป้ายที่ผู้พัฒนาจับคู่ไว้ **{open_correct['numerator']}/{open_correct['denominator']}** "
                  "(ป้ายเป็นการจับคู่ของผู้พัฒนา ไม่ใช่ความแม่นยำจริง) ตัวอย่างที่กฎส่งผิดคิว:", ""]
        missed = [r for r in report["items"] if r["source"] != "synthetic" and not r["passed"]]
        for r in missed[:10]:
            lines.append(f"- `{r['id']}` {short(r['problems'][0], 120)}")
        lines.append("")
    canary = report["canary"]
    lines.append(f"ไฟล์ตรวจจับคำสั่ง shell (`{canary['path']}`): "
                 + ("**พบ — มีข้อความถูกรันเป็นคำสั่ง!**" if canary["exists_after"] else "ไม่พบ (ไม่มีข้อความใดถูกรันเป็นคำสั่ง)"))
    lines.append("")
    if changes is not None:
        if changes:
            lines += [f"### ด่านตรวจผลรายรายการ (gate): **ไม่ผ่าน** — {len(changes)} รายการเปลี่ยนจาก baseline", ""]
            lines += [f"- {c}" for c in changes[:MAX_LISTED]]
            if len(changes) > MAX_LISTED:
                lines.append(f"- … และอีก {len(changes) - MAX_LISTED} รายการ")
            lines += ["", "ถ้าตั้งใจเปลี่ยน (แก้ bug หรือเพิ่มเคส) ให้สร้าง baseline ใหม่ใน PR เดียวกัน แล้วบอกเหตุผล", ""]
        else:
            lines += ["### ด่านตรวจผลรายรายการ (gate): **ผ่าน** — ทุกรายการตอบเหมือน baseline", ""]
    sources = ", ".join(f"{s['name']} ({s['license']})" for s in sets["open"]["sources"])
    lines += [f"> แหล่งข้อมูลเปิด: {sources} — รายละเอียดสัญญาอนุญาตใน `tests/robustness/NOTICE.md`  ",
              "> *Robustness benchmark, stage 1: synthetic Thai/English edge cases plus open corpora, against the "
              "deterministic logic and Core, offline (mock AI and a local fake of the Typhoon API). "
              f"{m['synthetic_items']} own items: {m['synthetic_passed']} passed, {m['bug']} bug, {m['gap']} gap, "
              f"{m['info']} info; open requests through the rules: {m['open_rules_correct']['numerator']}/"
              f"{m['open_rules_correct']['denominator']} match the mapped label; "
              f"{m['sweep_checks']:,} sweep checks, {m['sweep_violations']} violations. "
              f"Python {report['provenance']['python']}, {report['provenance']['duration_s']} s.*", ""]
    return "\n".join(lines)


# --- golden export for the live-AI scorecard ------------------------------------------------------------------

def golden_export(sets=None):
    """The rules items as a ``neuron-flow-golden-v1`` case file, so *Shadow eval with Typhoon* (and Claude) can run
    the same edge cases against a real model (pick the case set on the Actions page)."""
    sets = sets or load_sets()
    cases = []
    for item in sets["items"]:
        if item["layer"] != "rules":
            continue
        summary_text = expand(item["input"]["summary"])
        cases.append({"case_id": item["id"], "language": "th" if thai(summary_text) else "en",
                      "expected_category": item["expect"]["category"],
                      "tags": [item["capability"], item["checklist"].lower(), item["source"]],
                      "summary": summary_text})
    return {"schema": "neuron-flow-golden-v1", "name": "triage_edge_robustness_v1",
            "label_scope": ("Edge cases written and labelled by the developer, plus requests from CLINC150 (CC BY 3.0) "
                            "and BANKING77 (CC BY 4.0) re-labelled into this project's categories by the developer "
                            "(tests/robustness/NOTICE.md). Synthetic or crowdsourced text, no real customer data, and "
                            "not independent ground truth."),
            "cases": cases}


def escape_invisible(text):
    """JSON text with invisible characters written as ``\\uXXXX`` escapes, so the file stays readable."""
    out = []
    for ch in text:
        if ch != "\n" and unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Zl", "Zp"):
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return "".join(out)


def dump_golden(document):
    lines = ["{", f' "schema": {json.dumps(document["schema"])},', f' "name": {json.dumps(document["name"])},',
             f' "label_scope": {json.dumps(document["label_scope"], ensure_ascii=False)},', ' "cases": [']
    for index, case in enumerate(document["cases"]):
        comma = "," if index < len(document["cases"]) - 1 else ""
        lines.append("  " + escape_invisible(json.dumps(case, ensure_ascii=False)) + comma)
    lines += [" ]", "}"]
    return "\n".join(lines) + "\n"


# --- command line ---------------------------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description="Robustness benchmark, stage 1 (docs/benchmarking.md)")
    parser.add_argument("--layers", default=",".join(LAYERS), help=f"comma-separated subset of {', '.join(LAYERS)}")
    parser.add_argument("--out", help="write the full JSON report here")
    parser.add_argument("--summary", help="append the markdown summary here (e.g. $GITHUB_STEP_SUMMARY)")
    parser.add_argument("--compare-with", help="baseline file: exit 3 when any item's outcome differs")
    parser.add_argument("--write-baseline", help="write this run's outcomes as the baseline")
    parser.add_argument("--export-golden", help="write the rules items as a case file for the live-AI scorecard")
    args = parser.parse_args(argv)
    if args.export_golden:
        Path(args.export_golden).write_text(dump_golden(golden_export()), encoding="utf-8")
        print(f"wrote {args.export_golden}")
        return 0
    layers = tuple(layer for layer in args.layers.split(",") if layer)
    unknown = set(layers) - set(LAYERS)
    if unknown:
        parser.error(f"unknown layers: {', '.join(sorted(unknown))}")
    report = run(layers)
    changes = None
    if args.compare_with:
        changes = compare(report, json.loads(Path(args.compare_with).read_text(encoding="utf-8")))
    text = summary(report, changes)
    print(text)
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    if args.write_baseline:
        if set(layers) != set(LAYERS):
            parser.error("--write-baseline needs every layer")
        write_baseline(report, args.write_baseline)
    if report["canary"]["exists_after"]:
        return 4
    return 3 if changes else 0


if __name__ == "__main__":
    sys.exit(main())
