"""Check the bytecode cache inside the service image (effectiveness plan E1; standard library only).

A new Python process that finds no cache file (``__pycache__/*.pyc``) for a module compiles that module
from its source before running it. The service starts several processes (the launcher, the Runner and one
worker per parallel step), and it can never write a cache itself: ``PYTHONDONTWRITEBYTECODE=1`` is set and
the service user cannot write into the code folders. So the image must carry the cache, built once.

The *Service container* workflow pipes this file into the image it just built, as the service user:

    docker run --rm -i --entrypoint python --user neuron neuron-flow:ci - --require \
        < .github/scripts/check_image_bytecode.py

It prints a Markdown report (Thai headings for the owner, the figures in a table) and, with ``--require``,
exits 1 when
* a ``.py`` file under ``app/`` or ``neuron_flow/``, or in the installed packages (``sentry-sdk``, which
  the service imports only when ``SENTRY_DSN`` is set, as it is on Render), has no cache file, or one that
  does not hold exactly that source (compared by the hash stored in the cache file, never by file times), or
* a module the Runner imports, standard library and installed packages included, has no usable cache.

It also times fresh processes that import the Runner's modules. That time is reported and never gated:
a shared CI machine is too noisy for a limit.
"""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import sysconfig
import time

TREES = ("app", "neuron_flow")       # relative to the working directory (/srv/neuron-flow in the image)
IMPORT = "app.services.runner"       # what the Runner, and each worker process it starts, imports
OK, CHECKED, TIMESTAMP, STALE, MISSING = "ok", "checked", "timestamp", "stale", "missing"
# Every state in which Python runs the cached code without compiling. CHECKED costs a read and a hash of
# the source on each import; TIMESTAMP is valid only while the source's time and size stay as recorded.
USABLE = (OK, CHECKED, TIMESTAMP)
_LIST_MODULES = (
    "import importlib, json, sys\n"
    "importlib.import_module(sys.argv[1])\n"
    "print(json.dumps(sorted({m.__spec__.origin for m in list(sys.modules.values())\n"
    "    if getattr(m, '__spec__', None) is not None and m.__spec__.has_location\n"
    "    and str(m.__spec__.origin).endswith('.py')})))\n"
)


def cache_state(source):
    """How Python will treat the cache file of one source file.

    ``ok``: a hash-based cache holding exactly this source, used without looking at the source again;
    ``checked``: the same, but Python re-reads and re-hashes the source on every import;
    ``timestamp``: valid by the source's modification time and size, as recorded in the cache file;
    ``stale``: a cache file that is not for this source or this Python (unchecked, Python would run it
    as it is; otherwise it compiles again on every start);
    ``missing``: no cache file, so every new process compiles the module.
    """
    source = Path(source)
    try:
        header = Path(importlib.util.cache_from_source(str(source))).read_bytes()[:16]
    except OSError:
        return MISSING
    if len(header) < 16 or header[:4] != importlib.util.MAGIC_NUMBER:
        return STALE
    flags = int.from_bytes(header[4:8], "little")
    if flags & 0b1:  # hash-based (PEP 552): bytes 8..16 are the source's hash
        if header[8:16] != importlib.util.source_hash(source.read_bytes()):
            return STALE
        return CHECKED if flags & 0b10 else OK
    stat = source.stat()
    recorded = (int.from_bytes(header[8:12], "little"), int.from_bytes(header[12:16], "little"))
    return TIMESTAMP if recorded == (int(stat.st_mtime) & 0xFFFFFFFF, stat.st_size & 0xFFFFFFFF) else STALE


def scan_tree(root):
    """``{state: [paths]}`` for every ``.py`` file under ``root``."""
    states = {}
    for source in sorted(Path(root).rglob("*.py")):
        states.setdefault(cache_state(source), []).append(str(source))
    return states


def installed_packages():
    """The folder pip installs into (``site-packages``), or ``None`` when there is none."""
    folder = sysconfig.get_path("purelib")
    return folder if folder and Path(folder).is_dir() else None


def loaded_sources(import_name, python=sys.executable):
    """The source files of every module a fresh process holds after ``import <import_name>``."""
    # -B: looking must not write a cache (outside the image nothing else stops Python from doing so).
    done = subprocess.run([python, "-B", "-c", _LIST_MODULES, import_name], check=True, capture_output=True,
                          text=True)
    return json.loads(done.stdout)


def group_of(source, trees=TREES, cwd=None):
    """``app``, ``neuron_flow``, ``installed packages`` or ``standard library`` for a module's file."""
    path = Path(source).resolve()
    for tree in trees:
        if (Path(cwd or os.getcwd()) / tree).resolve() in path.parents:
            return tree
    return "installed packages" if "site-packages" in path.parts else "standard library"


def time_imports(import_name, runs, python=sys.executable):
    """Wall-clock milliseconds of ``runs`` fresh processes that import ``import_name`` (``None``: none)."""
    code = "pass" if import_name is None else f"import {import_name}"
    times = []
    for _ in range(runs):
        started = time.perf_counter()
        subprocess.run([python, "-B", "-c", code], check=True)
        times.append((time.perf_counter() - started) * 1000)
    return times


def spread(times):
    return {"min": round(min(times)), "median": round(statistics.median(times)), "max": round(max(times))}


def problems(trees, modules):
    """What ``--require`` refuses, as sentences. ``trees``: ``{tree: {state: [paths]}}``; ``modules``:
    ``{source: state}`` for the modules the Runner imports."""
    found = []
    for tree, states in trees.items():
        if not any(states.values()):
            found.append(f"no .py file found under {tree}/: is the working directory the code folder?")
            continue
        for state, paths in states.items():
            if state != OK:
                found.append(f"{len(paths)} file(s) under {tree}/ with a {state} cache, e.g. {paths[0]} "
                             f"(compile with --invalidation-mode unchecked-hash after the last change to the files)")
    unusable = sorted(source for source, state in modules.items() if state not in USABLE)
    if unusable:
        found.append(f"{len(unusable)} module(s) the Runner imports have no usable cache, e.g. {unusable[0]}")
    return found


def report(trees, modules, timings, label):
    """The Markdown report: Thai for the owner, with the figures in tables."""
    lines = [f"### ไฟล์ที่แปลไว้ล่วงหน้าในภาพของบริการ (bytecode cache) — {label}", ""]
    project = [trees[tree] for tree in TREES if tree in trees]
    total = sum(len(paths) for states in project for paths in states.values())
    ready = sum(len(states.get(OK, [])) for states in project)
    usable = sum(1 for state in modules.values() if state in USABLE)
    lines += [f"- โค้ดของโปรเจกต์ (`app/` และ `neuron_flow/`): มีไฟล์ที่แปลไว้แล้วและตรงกับต้นฉบับ **{ready} จาก {total} ไฟล์**",
              f"- โมดูลที่ตัวรันงาน (Runner) ต้องโหลดตอนเริ่ม: มีไฟล์ที่แปลไว้แล้ว **{usable} จาก {len(modules)} โมดูล** "
              "(ที่เหลือต้องแปลใหม่ทุกครั้งที่เริ่มโปรแกรม)", ""]
    lines += ["| Modules the Runner imports | with a usable cache | of |", "|---|---|---|"]
    groups = {}
    for source, state in modules.items():
        entry = groups.setdefault(group_of(source), [0, 0])
        entry[0] += state in USABLE
        entry[1] += 1
    for name in sorted(groups):
        lines.append(f"| {name} | {groups[name][0]} | {groups[name][1]} |")
    lines += ["", "| Files in the image | " + " | ".join((OK, CHECKED, TIMESTAMP, STALE, MISSING)) + " |",
              "|---|---|---|---|---|---|"]
    for tree, states in trees.items():
        lines.append(f"| `{tree}/` | " + " | ".join(str(len(states.get(state, [])))
                                                 for state in (OK, CHECKED, TIMESTAMP, STALE, MISSING)) + " |")
    text = "\n".join(lines) + "\n"
    return text + ("\n" + timing_table(timings, label) if timings else "")


def timing_table(timings, label):
    """Fresh-process start times as a Markdown table. Reported, never gated."""
    lines = [f"เวลาเริ่มโปรแกรมใหม่ 1 ตัวที่โหลดโมดูลของ Runner — {label} "
             f"({timings['runs']} รอบ; รายงานเท่านั้น ไม่ใช้ตัดสินผ่านหรือไม่ผ่าน)", "",
             "| A fresh process | min | median | max |", "|---|---|---|---|"]
    for name, key in ((f"`import {IMPORT}`", "import_ms"), ("the interpreter alone", "bare_ms")):
        lines.append(f"| {name} | {timings[key]['min']} ms | {timings[key]['median']} ms | {timings[key]['max']} ms |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--require", action="store_true", help="exit 1 when a cache file is missing or not exact")
    parser.add_argument("--runs", type=int, default=10, help="fresh processes to time (0: no timing)")
    parser.add_argument("--timing-only", action="store_true", help="only time fresh processes (for a CPU-limited run)")
    parser.add_argument("--label", default="this image", help="named in the report's heading")
    args = parser.parse_args(argv)
    timings = None
    if args.runs > 0:
        timings = {"runs": args.runs, "import_ms": spread(time_imports(IMPORT, args.runs)),
                   "bare_ms": spread(time_imports(None, args.runs))}
    if args.timing_only:
        print(timing_table(timings, args.label))
        print("bytecode-report " + json.dumps({"label": args.label, "timings": timings}, sort_keys=True))
        return 0
    trees = {tree: scan_tree(tree) for tree in TREES}
    packages = installed_packages()
    if packages:
        trees[packages] = scan_tree(packages)
    modules = {source: cache_state(source) for source in loaded_sources(IMPORT)}
    print(report(trees, modules, timings, args.label))
    print("bytecode-report " + json.dumps({
        "label": args.label, "python": sys.version.split()[0],
        "trees": {tree: {state: len(paths) for state, paths in states.items()} for tree, states in trees.items()},
        "modules": {"total": len(modules), "usable": sum(1 for state in modules.values() if state in USABLE)},
        "timings": timings}, sort_keys=True))
    found = problems(trees, modules)
    for problem in found:
        print(f"::error::{problem}" if args.require else f"::notice::{problem}")
    return 1 if found and args.require else 0


if __name__ == "__main__":
    sys.exit(main())
