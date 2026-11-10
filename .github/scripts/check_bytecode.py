"""Report, and optionally require, bytecode cache files (``.pyc``) for the Python sources of the image (roadmap E1).

Why it matters: the image runs with ``PYTHONDONTWRITEBYTECODE=1`` and the service may not write into its code
folder. A module without a usable cache file is then compiled from source by every new Python process, each
time it starts: the API, the Runner and every Core worker. On a small instance that made the first case after a
start take about 10 seconds (docs/evidence/2026-11-10-effectiveness-baseline.md).

Run it inside the image, from the image's working directory, with this file on standard input:

    docker run --rm -i --entrypoint python IMAGE - --require app neuron_flow \
        --imports app.serve app.services.runner --require-imports < .github/scripts/check_bytecode.py

It reports, as Markdown on standard output:
1. for each folder given: how many sources have a cache file this interpreter will use, and which do not;
2. for the modules that a fresh process loads when it imports ``--imports``: how many come with a usable cache
   file, split into the standard library, installed packages and the folders given;
3. how long a fresh process needs for that import (the median of a few runs).

A cache file is usable when it carries this interpreter's magic number and still matches its source. For a
hash-based file the source hash stored in it must equal the source's hash; this is checked even for
"unchecked" files, which Python itself never compares. For a timestamp-based file the stored time and size must
equal the source's.

Exit status: 1 when ``--require`` is given and a source in a required folder has no usable cache file, or
when ``--require-imports`` is given and a module loaded by ``--imports`` has none (this covers the standard
library and installed packages); otherwise 0. It only reads files; it never writes a cache file itself.
"""

import argparse
import importlib.util
import json
import os
import statistics
import subprocess
import sys
import sysconfig
import time
from pathlib import Path

VALID, MISSING, STALE, FOREIGN = "valid", "missing", "stale", "other_interpreter"
STATES = (VALID, MISSING, STALE, FOREIGN)
SHOWN = 12  # at most this many file names per list in the report
TIMED_RUNS = 5


def cache_state(source):
    """Whether the interpreter running this script would use the cache file of ``source``."""
    source = Path(source)
    try:
        data = Path(importlib.util.cache_from_source(str(source))).read_bytes()
    except (OSError, NotImplementedError, ValueError):
        return MISSING
    if len(data) < 16 or data[:4] != importlib.util.MAGIC_NUMBER:
        return FOREIGN
    flags = int.from_bytes(data[4:8], "little")
    try:
        if flags & 0b1:  # hash-based: bytes 8-16 hold the source hash
            return VALID if data[8:16] == importlib.util.source_hash(source.read_bytes()) else STALE
        stat = source.stat()  # timestamp-based: bytes 8-12 the source time, 12-16 its size
    except OSError:
        return STALE
    matches = (int.from_bytes(data[8:12], "little") == int(stat.st_mtime) & 0xFFFFFFFF
               and int.from_bytes(data[12:16], "little") == stat.st_size & 0xFFFFFFFF)
    return VALID if matches else STALE


def scan(folder):
    """Every ``.py`` file under ``folder`` with its cache state: ``{state: [relative paths]}``."""
    folder = Path(folder)
    found = {state: [] for state in STATES}
    for source in sorted(folder.rglob("*.py")):
        if "__pycache__" not in source.parts:
            found[cache_state(source)].append(str(source))
    return found


def _group(origin, folders, stdlib, packages):
    path = Path(origin).resolve()
    for folder in folders:
        if path.is_relative_to(Path(folder).resolve()):
            return str(folder)
    if any(path.is_relative_to(root) for root in packages):
        return "installed packages"
    if path.is_relative_to(stdlib):
        return "standard library"
    return "elsewhere"


def imported_sources(modules, python=sys.executable, cwd=None):
    """The source files that a fresh process has loaded after ``import <modules>`` (cached or not).
    ``-B``: the process must not write cache files itself, whatever the environment says."""
    code = ("import importlib, json, sys\n"
            f"for name in {list(modules)!r}:\n"
            "    importlib.import_module(name)\n"
            "origins = sorted({getattr(getattr(module, '__spec__', None), 'origin', None) or ''"
            " for module in list(sys.modules.values())})\n"
            "print(json.dumps([origin for origin in origins if origin.endswith('.py')]))\n")
    done = subprocess.run([python, "-B", "-c", code], capture_output=True, text=True, timeout=120, cwd=cwd)
    if done.returncode != 0:
        raise RuntimeError(f"could not import {' '.join(modules)}: {done.stderr.strip()[-400:]}")
    return json.loads(done.stdout.strip().splitlines()[-1])


def import_time_ms(modules, python=sys.executable, runs=TIMED_RUNS, cwd=None):
    """Wall time of a fresh process importing ``modules``: (median, fastest, slowest) in milliseconds."""
    code = "import importlib\n" + "".join(f"importlib.import_module({name!r})\n" for name in modules)
    times = []
    for _ in range(runs):
        started = time.perf_counter()
        subprocess.run([python, "-B", "-c", code], capture_output=True, timeout=120, check=True, cwd=cwd)
        times.append((time.perf_counter() - started) * 1000)
    return statistics.median(times), min(times), max(times)


def imported_states(modules, folders, python=sys.executable, cwd=None):
    """``{group: {state: count}}`` and the sources without a usable cache, for what ``modules`` import."""
    stdlib = Path(sysconfig.get_path("stdlib")).resolve()
    packages = {Path(sysconfig.get_path(name)).resolve() for name in ("purelib", "platlib")}
    groups, unusable = {}, []
    for origin in imported_sources(modules, python, cwd):
        state = cache_state(origin)
        group = _group(origin, folders, stdlib, packages)
        groups.setdefault(group, {name: 0 for name in STATES})[state] += 1
        if state != VALID:
            unusable.append(origin)
    return groups, unusable


def _names(paths):
    shown = ", ".join(f"`{path}`" for path in paths[:SHOWN])
    return shown + (f" และอีก {len(paths) - SHOWN} ไฟล์ (and {len(paths) - SHOWN} more)" if len(paths) > SHOWN else "")


def report(folders, required, modules, python=sys.executable, timed=True, require_imports=False, cwd=None):
    """The Markdown report and the list of problems that ``--require`` and ``--require-imports`` turn into a
    failure."""
    lines = ["### ไฟล์ที่แปลโค้ดไว้ล่วงหน้าในตัวเครื่อง (bytecode cache in the image)", "",
             f"Python {sys.version.split()[0]}, `PYTHONDONTWRITEBYTECODE={os.environ.get('PYTHONDONTWRITEBYTECODE', '')}`. "
             "ถ้าไฟล์ไหนไม่มีไฟล์ที่แปลไว้ โปรแกรมต้องแปลไฟล์นั้นใหม่ทุกครั้งที่เริ่ม "
             "(A source without a usable cache file is compiled again by every new process.)", "",
             "| โฟลเดอร์ (folder) | ไฟล์โค้ด (sources) | ใช้ได้ (usable) | ไม่มี (missing) | ไม่ตรงกับโค้ด (stale) | "
             "ของ Python รุ่นอื่น (other interpreter) |", "|---|---|---|---|---|---|"]
    problems = []
    for folder in folders:
        found = scan(folder)
        total = sum(len(paths) for paths in found.values())
        lines.append(f"| `{folder}` | {total} | {len(found[VALID])} | {len(found[MISSING])} | {len(found[STALE])} | "
                     f"{len(found[FOREIGN])} |")
        if str(folder) in required:
            if total == 0:
                problems.append(f"`{folder}`: no Python source found; is this the image's working directory?")
            for state in (MISSING, STALE, FOREIGN):
                if found[state]:
                    problems.append(f"`{folder}`: {len(found[state])} {state}: {_names(found[state])}")
    if modules:
        groups, unusable = imported_states(modules, folders, python, cwd)
        lines += ["", f"โมดูลที่โปรเซสใหม่โหลดเมื่อ import `{' '.join(modules)}` "
                      "(what a fresh process loads for that import):", "",
                  "| มาจาก (from) | ไฟล์โค้ด (sources) | ใช้ได้ (usable) | ไม่มี (missing) | ไม่ตรงกับโค้ด (stale) | "
                  "ของ Python รุ่นอื่น (other interpreter) |", "|---|---|---|---|---|---|"]
        for group in sorted(groups):
            counts = groups[group]
            lines.append(f"| {group} | {sum(counts.values())} | {counts[VALID]} | {counts[MISSING]} | "
                         f"{counts[STALE]} | {counts[FOREIGN]} |")
        if unusable:
            lines += ["", f"ไม่มีไฟล์ที่แปลไว้ใช้ได้ {len(unusable)} ไฟล์ (without a usable cache file): {_names(unusable)}"]
            if require_imports:
                problems.append(f"{len(unusable)} of the modules loaded by `{' '.join(modules)}` have no usable "
                                f"cache file: {_names(unusable)}")
        if timed:
            median, fastest, slowest = import_time_ms(modules, python, cwd=cwd)
            lines += ["", f"เวลาที่โปรเซสใหม่ใช้ import ชุดนี้ (a fresh process importing them, {TIMED_RUNS} runs): "
                          f"กลาง (median) **{median:.0f} ms**, เร็วสุด {fastest:.0f} ms, ช้าสุด {slowest:.0f} ms"]
    if required or require_imports:
        checked = [f"`{name}`" for name in sorted(required)]
        if require_imports:
            checked.append(f"โมดูลที่ `{' '.join(modules)}` โหลด (the modules those imports load)")
        lines += ["", ("**ไม่ผ่าน (failed):** " + "; ".join(problems)) if problems else
                  f"**ผ่าน (passed):** ทุกไฟล์ใน {', '.join(checked)} "
                  "มีไฟล์ที่แปลไว้และตรงกับโค้ด (every source there has a usable cache file)."]
    return "\n".join(lines) + "\n", problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folders", nargs="*", default=[], help="folders to report on")
    parser.add_argument("--require", nargs="*", default=[], metavar="FOLDER",
                        help="folders whose every source must have a usable cache file")
    parser.add_argument("--imports", nargs="*", default=[], metavar="MODULE",
                        help="modules a process imports at start; reports what they load and how long it takes")
    parser.add_argument("--require-imports", action="store_true",
                        help="every module loaded by --imports must have a usable cache file")
    parser.add_argument("--no-timing", action="store_true", help="skip the import timing")
    args = parser.parse_args(argv)
    folders = list(dict.fromkeys([*args.folders, *args.require]))
    if not folders and not args.imports:
        parser.error("give at least one folder or --imports")
    if args.require_imports and not args.imports:
        parser.error("--require-imports needs --imports")
    text, problems = report(folders, set(args.require), args.imports, timed=not args.no_timing,
                            require_imports=args.require_imports)
    sys.stdout.write(text)
    if problems:
        for problem in problems:
            print(f"::error::bytecode cache: {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
