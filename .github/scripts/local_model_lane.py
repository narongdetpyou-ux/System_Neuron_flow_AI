"""Run one pinned model through the local model lane on this machine (ADR-026, ADR-034); used by *Local open model
eval*. Standard library only; run from the repository root:

    python .github/scripts/local_model_lane.py --server-cmd ~/llama-bin/llama-server --model-path ~/models/<file> \
        --model-id <name>:<12 hex> --model-sha256 <64 hex> --triage-sets all --e2e full --out-dir lane \
        --summary "$GITHUB_STEP_SUMMARY"

In order, for the one model:
1. starts llama.cpp's server on 127.0.0.1 with the lane's fixed settings (``SERVER_FLAGS``: greedy decoding, a light
   repetition penalty, thinking off, two slots) and the model id as its alias, and times how long the file takes to
   load until ``/health`` answers;
2. times the first answer after loading (cold: nothing cached), with one fixed synthetic sentence through the real
   gateway, then runs the connection check (``llm_probe.py``) for the run page;
3. runs the triage scorecard on each chosen case set (and the study guide's, when asked), one JSON report each;
4. runs the end-to-end check (``tests/local_model_e2e.py``): the real service with this model, people's decisions,
   receipts, and the failure paths;
5. reads the server's own figures: peak and current memory of its process (``VmHWM``/``VmRSS``), prompt and
   generation speed from ``/metrics``, the file and chat template it has open from ``/props``; and this machine's
   processor, cores and memory;
6. stops the server and writes ``lane-<name>.json`` and a Thai summary.

A step that fails is recorded and the next one still runs; the exit status is 1 when any step failed. The child
processes get this environment without secrets (``NF_MODEL_*`` and anything named like a key or token): the model
link is used only by ``fetch_model.py``, in its own step. ``--server-cmd`` lets the tests use
``tests/fake_llama_server.py`` instead of llama.cpp.
"""

import argparse
import json
import os
from pathlib import Path
import platform
import re
import shlex
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

SETS = {  # the triage case sets, by the short names the reports and the comparison use
    "synthetic": "app/eval/golden/case_triage_synthetic_v1.json",
    "edge": "tests/robustness/triage_edge_golden_v1.json",
    "heldout": "app/eval/golden/case_triage_heldout_v1.json",
    "hard": "app/eval/golden/case_triage_autosend_hard_v1.json",
    "attention": "app/eval/golden/case_triage_attention_heldout_v1.json",
}
SERVER_FLAGS = ("--ctx-size", "16384", "--parallel", "2", "--reasoning", "off", "--temp", "0",
                "--repeat-penalty", "1.05", "--seed", "42", "--no-webui", "--no-slots", "--metrics")
SETTINGS_TEXT = "temperature 0, repeat penalty 1.05, seed 42, thinking off, context 16384 (2 slots)"
SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|DSN)", re.IGNORECASE)
SENTENCE = "I cannot upload a file to my ticket."  # fixed and synthetic, the same as the connection check's
METRICS = ("prompt_tokens_total", "prompt_seconds_total", "tokens_predicted_total", "tokens_predicted_seconds_total")


def child_environment(base, **values):
    env = {k: v for k, v in base.items()
           if not k.startswith(("NF_MODEL_", "NEURON_FLOW_")) and not SECRET_NAME.search(k)}
    env.update({k: str(v) for k, v in values.items()})
    return env


def get(url, timeout=10):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, exc.read()


def start_server(command, model_path, model_id, port, log_path, timeout_s):
    """``(process, seconds until /health answered)``; raises when it does not start."""
    full = [*command, "-m", str(model_path), "--alias", model_id, "--host", "127.0.0.1", "--port", str(port),
            *SERVER_FLAGS]
    log = open(log_path, "wb")
    started = time.monotonic()
    process = subprocess.Popen(full, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
    deadline = started + timeout_s
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"the model server stopped while starting (exit {process.returncode})")
        try:
            if get(f"http://127.0.0.1:{port}/health", timeout=2)[0] == 200:
                return process, round(time.monotonic() - started, 2)
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.5)
    process.kill()
    raise RuntimeError(f"the model server did not answer /health in {timeout_s:.0f}s")


def stop_server(process):
    if process.poll() is None:
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def first_answer(model_id, base_url, timeout_s):
    """The first answer after loading, through the real gateway: ``(milliseconds, answer or None, problem)``."""
    from app.llm import LLMConfig, load_prompt, mask, structured_answer
    config = LLMConfig(provider="local", model=model_id, base_url=base_url, request_timeout_s=timeout_s)
    started = time.monotonic()
    try:
        result = structured_answer(config, load_prompt("triage_classify_v2"), mask(SENTENCE))
        return round((time.monotonic() - started) * 1000, 1), result["answer"], None
    except Exception as exc:  # the class only; never a reply
        return round((time.monotonic() - started) * 1000, 1), None, type(exc).__name__


def process_memory(pid):
    """Peak and current resident memory of one process, in kB, from /proc (Linux)."""
    values = {}
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            name, _, rest = line.partition(":")
            if name in ("VmHWM", "VmRSS"):
                values[name] = int(rest.split()[0])
    except (OSError, ValueError, IndexError):
        pass
    return {"peak_rss_kb": values.get("VmHWM"), "rss_kb": values.get("VmRSS")}


def parse_metrics(text):
    """llama.cpp's Prometheus counters (``llamacpp:<name> <value>``) that the lane reports."""
    found = {}
    for line in text.splitlines():
        match = re.match(r"^llamacpp:([a-z_]+)(?:\{[^}]*\})?\s+([0-9.eE+-]+)\s*$", line.strip())
        if match and match.group(1) in METRICS:
            found[match.group(1)] = float(match.group(2))
    speeds = {}
    if found.get("prompt_seconds_total"):
        speeds["prompt_tokens_per_s"] = round(found["prompt_tokens_total"] / found["prompt_seconds_total"], 1)
    if found.get("tokens_predicted_seconds_total"):
        speeds["generated_tokens_per_s"] = round(found["tokens_predicted_total"] / found["tokens_predicted_seconds_total"], 1)
    return {**found, **speeds}


def machine():
    info = {"cores": os.cpu_count(), "python": platform.python_version(), "cpu": None, "memory_kb": None}
    try:
        info["cpu"] = next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                            if line.startswith("model name")), None)
        info["memory_kb"] = next((int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines()
                                  if line.startswith("MemTotal:")), None)
    except (OSError, ValueError, IndexError):
        pass
    return info


def server_figures(process, port):
    figures = {"memory": process_memory(process.pid), "metrics": {}, "props": {}}
    try:
        status, raw = get(f"http://127.0.0.1:{port}/metrics")
        if status == 200:
            figures["metrics"] = parse_metrics(raw.decode("utf-8", "replace"))
        status, raw = get(f"http://127.0.0.1:{port}/props")
        if status == 200:
            props = json.loads(raw)
            figures["props"] = {"model_file": Path(props.get("model_path") or "").name or None,
                                "total_slots": props.get("total_slots"), "build_info": props.get("build_info")}
    except (urllib.error.URLError, OSError, ValueError):
        pass
    return figures


def run_step(record, name, command, env, timeout_s, quiet=False):
    started = time.monotonic()
    try:
        code = subprocess.run(command, cwd=ROOT, env=env, timeout=timeout_s,
                              stdout=subprocess.DEVNULL if quiet else None).returncode
    except subprocess.TimeoutExpired:
        code = "timeout"
    record["steps"].append({"step": name, "exit": code, "seconds": round(time.monotonic() - started, 1)})
    return code == 0


def chosen_sets(value):
    if value in ("", "none"):
        return []
    names = list(SETS) if value == "all" else [name.strip() for name in value.split(",") if name.strip()]
    unknown = set(names) - set(SETS)
    if unknown:
        raise SystemExit(f"unknown case sets: {sorted(unknown)}; use {', '.join(SETS)} or all")
    return names


def mb(kb):
    return "–" if not kb else f"{kb / 1024:,.0f} MB"


def markdown(record):
    figures, cold = record.get("server") or {}, record.get("first_answer") or {}
    memory, metrics, host = figures.get("memory") or {}, figures.get("metrics") or {}, record["machine"]
    lines = [f"### เวลาและหน่วยความจำของรุ่น `{record['model_id']}` (performance)", "",
             "| | |", "|---|---|",
             f"| เครื่อง | {host.get('cpu') or 'unknown CPU'}, {host.get('cores')} cores, หน่วยความจำ {mb(host.get('memory_kb'))} |",
             f"| การตั้งค่าเครื่องรันโมเดล | {SETTINGS_TEXT} |",
             f"| โหลดไฟล์โมเดลจนพร้อมตอบ | {record.get('load_s', '–')} วินาที |",
             f"| คำตอบแรกหลังโหลด (ยังไม่มีแคช) | {cold.get('ms', '–')} ms"
             f"{' · ตอบได้' if cold.get('answer') else ' · ' + str(cold.get('problem'))} |",
             f"| หน่วยความจำสูงสุดของเครื่องรันโมเดล (peak RSS) | {mb(memory.get('peak_rss_kb'))} |",
             f"| ความเร็วอ่าน prompt / เขียนคำตอบ | {metrics.get('prompt_tokens_per_s', '–')} / "
             f"{metrics.get('generated_tokens_per_s', '–')} token ต่อวินาที |",
             f"| token ที่อ่าน / เขียน ทั้งรอบ | {int(metrics.get('prompt_tokens_total', 0)):,} / "
             f"{int(metrics.get('tokens_predicted_total', 0)):,} |", "",
             "| ขั้น | ผล | วินาที |", "|---|---|---|"]
    for step in record["steps"]:
        lines.append(f"| {step['step']} | {'ผ่าน' if step['exit'] == 0 else 'ไม่ผ่าน (' + str(step['exit']) + ')'} | "
                     f"{step['seconds']} |")
    lines += ["", "_Peak RSS is the server process's high-water mark (VmHWM), including the parts of the model file it "
              "read. Speeds come from llama.cpp's own counters for this run. One machine, one run._", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--server-cmd", required=True, help="the llama-server program (a command line)")
    parser.add_argument("--model-path", required=True, type=Path)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--model-sha256", default="")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--triage-sets", default="synthetic", help=f"comma-separated of {', '.join(SETS)}; all; none")
    parser.add_argument("--limit", default="")
    parser.add_argument("--study-guide", action="store_true")
    parser.add_argument("--e2e", choices=("full", "quick", "none"), default="full")
    parser.add_argument("--timeout-s", type=float, default=300.0)
    parser.add_argument("--start-timeout-s", type=float, default=300.0)
    parser.add_argument("--out-dir", type=Path, default=Path("lane"))
    parser.add_argument("--log-dir", type=Path, default=None, help="the server's log (default: --out-dir)")
    parser.add_argument("--summary", default=os.devnull)
    parser.add_argument("--quiet", action="store_true", help="the steps' own output is not shown (tests)")
    args = parser.parse_args(argv)
    sets = chosen_sets(args.triage_sets)
    name = args.model_id.split(":", 1)[0]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    log_dir = args.log_dir or args.out_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    base_url = f"http://127.0.0.1:{args.port}/v1"
    env = child_environment(os.environ, PYTHONPATH=ROOT, NEURON_FLOW_LLM_PROVIDER="local",
                            NEURON_FLOW_LLM_MODEL=args.model_id, NEURON_FLOW_LOCAL_BASE_URL=base_url,
                            NEURON_FLOW_LLM_TIMEOUT_S=args.timeout_s)
    record = {"schema": "neuron-flow-local-lane-v1", "model_id": args.model_id, "model_file": args.model_path.name,
              "model_sha256": args.model_sha256 or None, "settings": SETTINGS_TEXT, "server_flags": list(SERVER_FLAGS),
              "machine": machine(), "sets": sets, "steps": []}
    ok = True
    try:
        process, record["load_s"] = start_server(shlex.split(args.server_cmd), args.model_path, args.model_id,
                                                 args.port, log_dir / f"llama-server-{name}.log", args.start_timeout_s)
    except RuntimeError as exc:
        record["steps"].append({"step": "start the model server", "exit": str(exc), "seconds": 0})
        process, ok = None, False
    if process is not None:
        try:
            ms, answer, problem = first_answer(args.model_id, base_url, args.timeout_s)
            record["first_answer"] = {"ms": ms, "answer": answer, "problem": problem}
            ok &= run_step(record, "connection check", [sys.executable, ".github/scripts/llm_probe.py", args.summary],
                           env, 600, args.quiet)
            for short in sets:
                command = [sys.executable, "-m", "app.eval.triage_shadow_eval", "--golden", SETS[short],
                           "--out", str(args.out_dir / f"shadow-{name}-{short}.json"), "--summary", args.summary]
                if args.limit:
                    command += ["--limit", args.limit]
                ok &= run_step(record, f"triage scorecard: {short}", command, env, 3 * 3600, args.quiet)
            if args.study_guide:
                command = [sys.executable, "-m", "app.eval.study_guide_eval", "--summary", args.summary,
                           "--out", str(args.out_dir / f"study-guide-{name}.json")]
                if args.limit:
                    command += ["--limit", args.limit]
                ok &= run_step(record, "study guide scorecard", command, env, 3 * 3600, args.quiet)
            if args.e2e != "none":
                command = [sys.executable, "-m", "tests.local_model_e2e", "--llm-base-url", base_url,
                           "--model-id", args.model_id, "--model-file", str(args.model_path), "--cases", args.e2e,
                           "--timeout-s", str(args.timeout_s), "--json", str(args.out_dir / f"e2e-{name}.json"),
                           "--summary", args.summary]
                if args.model_sha256:
                    command += ["--model-sha256", args.model_sha256]
                ok &= run_step(record, "end-to-end check", command, env, 3600, args.quiet)
            record["server"] = server_figures(process, args.port)
        finally:
            stop_server(process)
    text = markdown(record)
    print(text)
    with open(args.summary, "a", encoding="utf-8") as stream:
        stream.write(text + "\n")
    (args.out_dir / f"lane-{name}.json").write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n",
                                                    encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
