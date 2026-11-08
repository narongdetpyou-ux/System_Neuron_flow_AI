"""The model-file fetcher of the local open-model lane (`.github/scripts/fetch_model.py`, ADR-026), against a fake
Hugging Face Hub on this machine: a moving revision becomes one commit, exactly one file is picked, the SHA-256
is checked (pinned or the publisher's), a cached file is reused only when it matches, and a bad download is
never kept."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("fetch_model", ROOT / ".github" / "scripts" / "fetch_model.py")
fetch_model = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch_model)

REPO = "typhoon-ai/typhoon2.5-qwen3-4b-gguf"
COMMIT = "c0ffee" + "0" * 34
CONTENT = b"GGUF" + bytes(range(256)) * 64  # a stand-in for the model's bytes
SHA = hashlib.sha256(CONTENT).hexdigest()
OTHER = hashlib.sha256(b"something else").hexdigest()


class FakeHub:
    """Serves the revision and tree APIs, and each file through a redirect, as the Hub does."""

    def __init__(self, *, served=CONTENT, published=SHA, extra_files=()):
        self.requests = []
        hub = self
        files = [{"type": "file", "path": "README.md", "size": 10, "oid": "a" * 40},
                 {"type": "file", "path": "typhoon2.5-qwen3-4b-q4_k_m.gguf", "size": len(CONTENT),
                  "oid": "b" * 40, "lfs": {"oid": published, "size": len(CONTENT), "pointerSize": 134}},
                 {"type": "file", "path": "typhoon2.5-qwen3-4b-q8_0.gguf", "size": 7,
                  "oid": "c" * 40, "lfs": {"oid": OTHER, "size": 7, "pointerSize": 134}}, *extra_files]

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                hub.requests.append(self.path)
                if self.path == f"/api/models/{REPO}/revision/main" or self.path == f"/api/models/{REPO}/revision/{COMMIT}":
                    return self.send(200, json.dumps({"id": REPO, "sha": COMMIT}).encode())
                if self.path == f"/api/models/{REPO}/tree/{COMMIT}":
                    return self.send(200, json.dumps(files).encode())
                if self.path.startswith(f"/{REPO}/resolve/{COMMIT}/"):
                    self.send_response(302)
                    self.send_header("location", "/cdn/" + self.path.rsplit("/", 1)[1])
                    self.send_header("content-length", "0")
                    return self.end_headers()
                if self.path.startswith("/cdn/"):
                    return self.send(200, served)
                return self.send(404, b"{}")

            def send(self, status, body):
                self.send_response(status)
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self._thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()

    def downloads(self):
        return [path for path in self.requests if path.startswith("/cdn/")]


def run(hub, dest, *, revision="main", file="*Q4_K_M.gguf", sha256=""):
    return fetch_model.fetch(hub.base_url, REPO, revision, file, sha256, Path(dest))


class FetchTests(unittest.TestCase):
    def test_a_glob_picks_one_file_and_a_moving_revision_becomes_a_commit(self):
        with FakeHub() as hub, tempfile.TemporaryDirectory() as dest:
            result = run(hub, dest)
            self.assertEqual(Path(result["path"]).read_bytes(), CONTENT)
        self.assertEqual((result["file"], result["revision"], result["sha256"], result["pinned"], result["reused"]),
                         ("typhoon2.5-qwen3-4b-q4_k_m.gguf", COMMIT, SHA, False, False))
        self.assertIn(f"/{REPO}/resolve/{COMMIT}/typhoon2.5-qwen3-4b-q4_k_m.gguf", hub.requests)  # not "main"
        self.assertEqual(len(hub.downloads()), 1)

    def test_a_pinned_file_is_checked_against_the_pin_and_the_publisher(self):
        with FakeHub() as hub, tempfile.TemporaryDirectory() as dest:
            result = run(hub, dest, revision=COMMIT, file="typhoon2.5-qwen3-4b-q4_k_m.gguf", sha256=SHA.upper())
            self.assertTrue(result["pinned"])
            with self.assertRaisesRegex(fetch_model.FetchError, "differs from the publisher"):
                run(hub, Path(dest) / "other", sha256=OTHER)
            self.assertFalse((Path(dest) / "other").exists())  # stopped before any download
        self.assertEqual(len(hub.downloads()), 1)

    def test_a_download_that_does_not_match_is_never_kept(self):
        with FakeHub(served=CONTENT[:-1] + b"X") as hub, tempfile.TemporaryDirectory() as dest:
            with self.assertRaisesRegex(fetch_model.FetchError, "does not match"):
                run(hub, dest)
            self.assertEqual(list(Path(dest).iterdir()), [])  # neither the file nor the .part is left

    def test_a_cached_file_is_reused_only_when_its_hash_matches(self):
        with FakeHub() as hub, tempfile.TemporaryDirectory() as dest:
            target = Path(dest) / "typhoon2.5-qwen3-4b-q4_k_m.gguf"
            target.write_bytes(CONTENT)
            self.assertTrue(run(hub, dest)["reused"])
            self.assertEqual(hub.downloads(), [])
            target.write_bytes(b"stale or broken")
            result = run(hub, dest)
            self.assertFalse(result["reused"])
            self.assertEqual(target.read_bytes(), CONTENT)
        self.assertEqual(len(hub.downloads()), 1)

    def test_it_refuses_ambiguous_missing_or_unsafe_requests(self):
        with FakeHub() as hub, tempfile.TemporaryDirectory() as dest:
            with self.assertRaisesRegex(fetch_model.FetchError, "2 files match"):
                run(hub, dest, file="*.gguf")
            with self.assertRaisesRegex(fetch_model.FetchError, "0 files match"):
                run(hub, dest, file="*q5_k_m.gguf")
            for kwargs in ({"file": "../x.gguf"}, {"file": "models/x.gguf"}, {"revision": "main;rm"},
                           {"sha256": "abc"}):
                with self.assertRaises(fetch_model.FetchError, msg=kwargs):
                    run(hub, dest, **kwargs)
            with self.assertRaisesRegex(fetch_model.FetchError, "owner/name"):
                fetch_model.fetch(hub.base_url, "../etc", "main", "*.gguf", "", Path(dest))
        with self.assertRaisesRegex(fetch_model.FetchError, "https"):
            fetch_model.check_base("http://huggingface.co")
        self.assertEqual(fetch_model.check_base("https://huggingface.co/"), "https://huggingface.co")

    def test_a_file_without_a_published_hash_needs_a_pin(self):
        plain = {"type": "file", "path": "plain.gguf", "size": len(CONTENT), "oid": "d" * 40}
        with FakeHub(extra_files=[plain]) as hub, tempfile.TemporaryDirectory() as dest:
            with self.assertRaisesRegex(fetch_model.FetchError, "no SHA-256"):
                run(hub, dest, file="plain.gguf")
            self.assertEqual(run(hub, dest, file="plain.gguf", sha256=SHA)["sha256"], SHA)

    def test_main_writes_the_outputs_and_a_summary_that_says_when_it_is_not_pinned(self):
        with FakeHub() as hub, tempfile.TemporaryDirectory() as work:
            summary, outputs = Path(work) / "summary.md", Path(work) / "outputs.txt"
            code = fetch_model.main(["--repo", REPO, "--file", "*q4_k_m.gguf", "--dest", str(Path(work) / "models"),
                                     "--summary", str(summary), "--github-output", str(outputs),
                                     "--base-url", hub.base_url])
            self.assertEqual(code, 0)
            values = dict(line.split("=", 1) for line in outputs.read_text().splitlines())
            self.assertEqual((values["sha256"], values["revision"], values["pinned"]), (SHA, COMMIT, "false"))
            self.assertTrue(values["path"].endswith("typhoon2.5-qwen3-4b-q4_k_m.gguf"))
            self.assertIn("ยังไม่ตรึง", summary.read_text(encoding="utf-8"))
            failed = fetch_model.main(["--repo", REPO, "--file", "*.gguf", "--dest", str(Path(work) / "models"),
                                       "--summary", str(summary), "--base-url", hub.base_url])
            self.assertEqual(failed, 1)
            self.assertIn("ดาวน์โหลดหรือตรวจไฟล์ไม่ผ่าน", summary.read_text(encoding="utf-8"))

    def test_the_hub_being_down_is_reported_not_raised(self):
        hub = FakeHub()
        base = hub.base_url
        hub.server.server_close()  # nothing listens there any more
        original = fetch_model.time.sleep
        fetch_model.time.sleep = lambda _seconds: None
        try:
            with tempfile.TemporaryDirectory() as dest:
                with self.assertRaisesRegex(fetch_model.FetchError, "after 3 attempts"):
                    fetch_model.fetch(base, REPO, "main", "*q4_k_m.gguf", "", Path(dest))
        finally:
            fetch_model.time.sleep = original


if __name__ == "__main__":
    unittest.main()
