"""The bytecode cache of the service image (effectiveness plan E1).

A new process that finds no cache file for a module compiles it from source, and the service can never
write a cache itself, so the image carries one. These tests cover the three places that keep it there:
* ``.github/scripts/check_image_bytecode.py``, which the *Service container* workflow runs inside the image:
  how it reads one cache file (exact, re-checked, by file time, stale, missing) and what it refuses;
* the ``Dockerfile`` and the workflow, read as text: the compile steps, their order, and the gate;
* the smoke test's report of the first case after a start, which must never fail on a time.
"""

import contextlib
import importlib.util
import io
import os
import py_compile
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from examples import service_smoke_test as smoke

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("check_image_bytecode",
                                               ROOT / ".github" / "scripts" / "check_image_bytecode.py")
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)

MODES = {"unchecked": py_compile.PycInvalidationMode.UNCHECKED_HASH,
         "checked": py_compile.PycInvalidationMode.CHECKED_HASH,
         "timestamp": py_compile.PycInvalidationMode.TIMESTAMP}


def write_module(folder, name="module.py", text="VALUE = 1\n"):
    path = Path(folder) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def compile_as(path, mode):
    py_compile.compile(str(path), doraise=True, invalidation_mode=MODES[mode])


class CacheStateTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.folder = Path(self._temp.name)

    def test_no_cache_file_is_missing(self):
        self.assertEqual(check.cache_state(write_module(self.folder)), check.MISSING)

    def test_each_invalidation_mode_is_told_apart(self):
        for mode, expected in (("unchecked", check.OK), ("checked", check.CHECKED), ("timestamp", check.TIMESTAMP)):
            with self.subTest(mode=mode):
                path = write_module(self.folder, f"{mode}.py")
                compile_as(path, mode)
                self.assertEqual(check.cache_state(path), expected)

    def test_a_hash_cache_of_other_source_is_stale_even_with_the_same_time_and_size(self):
        # Unchecked, Python would run the old code: the reason the image check compares hashes.
        path = write_module(self.folder, text="VALUE = 1\n")
        compile_as(path, "unchecked")
        stat = path.stat()
        path.write_text("VALUE = 2\n", encoding="utf-8")
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertEqual(path.stat().st_size, stat.st_size)
        self.assertEqual(check.cache_state(path), check.STALE)
        done = subprocess.run([sys.executable, "-B", "-c", "import module; print(module.VALUE)"], cwd=self.folder,
                              capture_output=True, text=True, check=True)
        self.assertEqual(done.stdout.strip(), "1", "Python is expected to trust an unchecked cache")

    def test_a_timestamp_cache_is_stale_once_the_source_changes(self):
        path = write_module(self.folder)
        compile_as(path, "timestamp")
        path.write_text("VALUE = 22\n", encoding="utf-8")  # another size
        self.assertEqual(check.cache_state(path), check.STALE)

    def test_a_cache_of_another_python_or_a_cut_file_is_stale(self):
        path = write_module(self.folder)
        compile_as(path, "unchecked")
        cache = Path(importlib.util.cache_from_source(str(path)))
        whole = cache.read_bytes()
        for label, data in (("another magic number", b"\x00\x00\r\n" + whole[4:]), ("cut", whole[:9]), ("empty", b"")):
            with self.subTest(label):
                cache.write_bytes(data)
                self.assertEqual(check.cache_state(path), check.STALE)

    def test_scan_tree_groups_every_python_file_by_state(self):
        done = write_module(self.folder, "pkg/done.py")
        write_module(self.folder, "pkg/sub/todo.py")
        write_module(self.folder, "pkg/notes.txt")
        compile_as(done, "unchecked")
        states = check.scan_tree(self.folder / "pkg")
        self.assertEqual({state: [Path(p).name for p in paths] for state, paths in states.items()},
                         {check.OK: ["done.py"], check.MISSING: ["todo.py"]})


class RequireTests(unittest.TestCase):
    def test_exact_caches_everywhere_pass(self):
        trees = {"app": {check.OK: ["app/a.py"]}, "neuron_flow": {check.OK: ["neuron_flow/b.py"]}}
        modules = {"app/a.py": check.OK, "/usr/lib/python3/json/__init__.py": check.TIMESTAMP,
                   "/usr/lib/python3/os.py": check.CHECKED}
        self.assertEqual(check.problems(trees, modules), [])

    def test_project_code_must_be_exact_not_only_usable(self):
        # A cache valid by file time breaks when a build tool touches the files; one that re-checks the
        # source reads every file again at every start. Only an exact, unchecked cache is accepted.
        for state in (check.MISSING, check.STALE, check.TIMESTAMP, check.CHECKED):
            with self.subTest(state=state):
                found = check.problems({"app": {check.OK: ["app/a.py"], state: ["app/x.py", "app/y.py"]}}, {})
                self.assertEqual(len(found), 1)
                self.assertIn(f"2 file(s) under app/ with a {state} cache, e.g. app/x.py", found[0])

    def test_an_empty_tree_is_refused(self):
        # Run from the wrong folder, the check would otherwise pass with nothing checked.
        self.assertIn("no .py file found under app/", check.problems({"app": {}}, {})[0])

    def test_every_module_the_runner_imports_needs_a_usable_cache(self):
        modules = {"/lib/a.py": check.OK, "/lib/c.py": check.MISSING, "/lib/b.py": check.STALE}
        found = check.problems({"app": {check.OK: ["app/a.py"]}}, modules)
        self.assertEqual(found, ["2 module(s) the Runner imports have no usable cache, e.g. /lib/b.py"])

    def test_loaded_sources_lists_what_a_fresh_process_imported(self):
        sources = check.loaded_sources("json")
        self.assertTrue(any(source.endswith(os.path.join("json", "decoder.py")) for source in sources))
        self.assertTrue(all(source.endswith(".py") for source in sources))

    def test_modules_are_grouped_by_where_they_live(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(check.group_of(Path(temp) / "app" / "services" / "runner.py", cwd=temp), "app")
            self.assertEqual(check.group_of(Path(temp) / "neuron_flow" / "engine.py", cwd=temp), "neuron_flow")
            self.assertEqual(check.group_of("/usr/lib/python3.12/site-packages/sentry_sdk/hub.py", cwd=temp),
                             "installed packages")
            self.assertEqual(check.group_of("/usr/lib/python3.12/json/decoder.py", cwd=temp), "standard library")


class MainTests(unittest.TestCase):
    """The script as the workflow runs it, in a folder shaped like the image's code folder."""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.folder = Path(self._temp.name)
        self.sources = [write_module(self.folder, "app/__init__.py", ""),
                        write_module(self.folder, "app/services/runner.py"),
                        write_module(self.folder, "neuron_flow/__init__.py", "")]
        previous = os.getcwd()
        os.chdir(self.folder)
        self.addCleanup(os.chdir, previous)
        # Only the folder's own files: whether this machine's standard library has a cache is not the test.
        original = check.loaded_sources
        check.loaded_sources = lambda name: [str(path) for path in self.sources]
        self.addCleanup(setattr, check, "loaded_sources", original)

    def run_main(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = check.main(["--runs", "0", *args])
        return code, output.getvalue()

    def test_without_a_cache_it_reports_and_only_require_fails(self):
        code, output = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("**0 จาก 3 ไฟล์**", output)
        self.assertIn("::notice::2 file(s) under app/ with a missing cache", output)
        code, output = self.run_main("--require")
        self.assertEqual(code, 1)
        self.assertIn("::error::2 file(s) under app/ with a missing cache", output)
        self.assertIn("::error::3 module(s) the Runner imports have no usable cache", output)

    def test_the_dockerfile_compile_command_satisfies_require(self):
        command = re.search(r"^RUN (python -m compileall .* neuron_flow app)$",
                            (ROOT / "Dockerfile").read_text(encoding="utf-8"), re.MULTILINE)
        self.assertIsNotNone(command, "the Dockerfile must compile neuron_flow/ and app/")
        arguments = command.group(1).split()[1:]
        subprocess.run([sys.executable, *arguments], cwd=self.folder, check=True,
                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})  # as the image sets it
        code, output = self.run_main("--require")
        self.assertEqual(code, 0, output)
        self.assertIn("**3 จาก 3 ไฟล์**", output)
        self.assertNotIn("::error::", output)
        # A file changed after the compile step is caught, whatever its time says.
        self.sources[1].write_text("VALUE = 3\n", encoding="utf-8")
        code, output = self.run_main("--require")
        self.assertEqual(code, 1)
        self.assertIn("with a stale cache, e.g. app/services/runner.py", output)

    def test_timing_only_reports_times_and_never_fails(self):
        check.time_imports, original = (lambda name, runs: [120.4, 100.0, 180.6][:runs]), check.time_imports
        self.addCleanup(setattr, check, "time_imports", original)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = check.main(["--timing-only", "--runs", "3", "--label", "0.1 CPU", "--require"])
        self.assertEqual(code, 0)
        self.assertIn("| `import app.services.runner` | 100 ms | 120 ms | 181 ms |", output.getvalue())
        self.assertIn("0.1 CPU", output.getvalue())


class ImageContractTests(unittest.TestCase):
    """The Dockerfile and the workflow, read as text: what keeps the cache in the image and exact."""

    @classmethod
    def setUpClass(cls):
        cls.dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        # Instructions with their continuation lines joined, comments dropped.
        joined = re.sub(r"\\\n\s*", " ", "\n".join(line for line in cls.dockerfile.splitlines()
                                                    if not line.lstrip().startswith("#")))
        cls.instructions = [line.strip() for line in joined.splitlines() if line.strip()]
        cls.workflow = (ROOT / ".github" / "workflows" / "service-container.yml").read_text(encoding="utf-8")

    def index(self, pattern):
        found = [number for number, line in enumerate(self.instructions) if re.search(pattern, line)]
        self.assertTrue(found, f"no Dockerfile instruction matches {pattern!r}")
        return found

    def test_the_service_still_never_writes_bytecode_itself(self):
        # The cache is built once, at build time; a running service must not write into its code folder.
        self.assertRegex(self.dockerfile, r"ENV PYTHONDONTWRITEBYTECODE=1\b")

    def test_the_projects_code_is_compiled_after_the_last_step_that_changes_it(self):
        compile_step = self.index(r"^RUN python -m compileall .*--invalidation-mode unchecked-hash neuron_flow app$")
        self.assertEqual(len(compile_step), 1)
        changes = self.index(r"^(COPY|ADD) ") + [number for number, line in enumerate(self.instructions)
                                                 if line.startswith("RUN ") and "compileall" not in line]
        self.assertGreater(compile_step[0], max(changes),
                           "a step after the compile step could change a file and leave a stale cache")

    def test_the_standard_library_and_installed_packages_are_compiled_after_pip(self):
        stdlib = self.index(r"^RUN python -m compileall .*--invalidation-mode unchecked-hash .*sysconfig\.get_path\(\"stdlib\"\)")
        self.assertEqual(len(stdlib), 1)
        self.assertGreater(stdlib[0], max(self.index(r"^RUN pip install ")),
                           "packages installed after the compile step would have no exact cache")

    def test_both_compile_steps_replace_any_cache_already_there(self):
        # Without -f, compileall keeps a cache that is valid by file time, such as the ones pip writes.
        for line in self.instructions:
            if "compileall" in line:
                self.assertRegex(line, r" -f ")

    def test_caches_from_the_build_machine_never_enter_the_image(self):
        ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
        self.assertIn("**/__pycache__", ignored)
        self.assertIn("*.py[cod]", ignored)

    def test_the_container_check_requires_the_cache_as_the_service_user(self):
        commands = re.sub(r"\\\n\s*", " ", self.workflow)
        required = [line for line in commands.splitlines()
                    if "check_image_bytecode.py" in line and "--require" in line]
        self.assertEqual(len(required), 1, "exactly one step must gate on the cache")
        self.assertIn("--user neuron", required[0])
        self.assertIn("neuron-flow:ci", required[0])
        self.assertNotIn("--timing-only", required[0])
        self.assertNotIn("|| true", required[0])


class FakeService:
    """Answers the smoke test's calls like a service whose first case ends as ``outcome``."""

    def __init__(self, outcome="REVIEW_REQUIRED", admitted=202, alive=True):
        self.outcome, self.admitted, self.alive = outcome, admitted, alive

    def call(self, method, path, body=None, *, key=True):
        if path == "/v1/status":
            figures = {"case_triage.v2": {"jobs": 1, "wait_s": {"median": 0.4, "max": 0.4},
                                          "run_s": {"median": 9.87, "max": 9.87}}}
            return 200, {"runner": {"alive": self.alive}, "metrics": {"workflows": figures}}
        if method == "POST":
            return self.admitted, {"job_id": "job-1", "status": "QUEUED"}
        return 200, {"status": self.outcome}


class FirstCaseReportTests(unittest.TestCase):
    def report(self, service, timeout_s=5):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(output):
            summary = Path(temp) / "summary.md"
            smoke.first_case_only(service, timeout_s, "0.1 CPU", str(summary))
            written = summary.read_text(encoding="utf-8")
        return output.getvalue(), written

    def test_it_reports_the_first_cases_run_time_from_the_status_figures(self):
        output, written = self.report(FakeService())
        self.assertEqual(written, "- เคสแรกหลังบริการเริ่มทำงาน — 0.1 CPU: ใช้เวลา **9.9 วินาที** "
                                  "(รอในคิวก่อนเริ่ม 0.4 วินาที) ผลลัพธ์ `REVIEW_REQUIRED`\n")
        self.assertIn('"run_s": 9.87', output)
        self.assertNotIn("::warning::", output)

    def test_a_failed_first_case_is_a_warning_not_an_error(self):
        # A worker that misses Core's 10 s start limit fails its step; the report must say so and go on.
        output, written = self.report(FakeService(outcome="FAILED"))
        self.assertIn("::warning::first case (0.1 CPU) ended as FAILED", output)
        self.assertIn("`FAILED`", written)

    def test_a_service_that_never_gets_ready_is_reported_without_a_time(self):
        output, written = self.report(FakeService(alive=False), timeout_s=0.01)
        self.assertIn("::warning::", output)
        self.assertIn("**ไม่มีตัวเลข**", written)

    def test_a_refused_case_is_reported_with_its_status(self):
        _output, written = self.report(FakeService(admitted=503))
        self.assertIn("`HTTP 503`", written)

    def test_the_mode_exits_zero_when_nothing_answers(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            summary = Path(temp) / "summary.md"
            code = smoke.main(["--url", "http://127.0.0.1:9", "--key", "unused", "--first-case-only",
                               "--timeout", "0.01", "--summary", str(summary)])
            self.assertEqual(code, 0)
            self.assertIn("บริการไม่พร้อมภายในเวลาที่รอ", summary.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
