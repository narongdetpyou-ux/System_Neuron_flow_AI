"""The model-file fetcher of the local open-model lane (`.github/scripts/fetch_model.py`, ADR-026, ADR-034), against
fakes on this machine.

The Hugging Face Hub: a moving revision becomes one commit, exactly one file is picked, the SHA-256 is checked
(pinned or the publisher's), a cached file is reused only when it matches, and a bad download is never kept.

The pin file and a private link (the owner's fine-tune, ADR-034): the committed entries are what the owner reported;
a Google Drive share link becomes Drive's direct download, also through the page Drive shows for files it cannot
scan; only the pinned size and SHA-256 are kept; a token reaches the link's own host only, never a redirect target;
a redirect off https is refused; and the link itself never appears in what the script prints or writes."""
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
        self.requests, self.seen = [], []
        hub = self
        files = [{"type": "file", "path": "README.md", "size": 10, "oid": "a" * 40},
                 {"type": "file", "path": "typhoon2.5-qwen3-4b-q4_k_m.gguf", "size": len(CONTENT),
                  "oid": "b" * 40, "lfs": {"oid": published, "size": len(CONTENT), "pointerSize": 134}},
                 {"type": "file", "path": "typhoon2.5-qwen3-4b-q8_0.gguf", "size": 7,
                  "oid": "c" * 40, "lfs": {"oid": OTHER, "size": 7, "pointerSize": 134}}, *extra_files]

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                hub.requests.append(self.path)
                hub.seen.append((self.path, {k.lower(): v for k, v in self.headers.items()}))
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



# -- the pin file and a private link (ADR-034) -------------------------------------------------------------

PINS = ROOT / ".github" / "local_models.json"
FINETUNE = "nf-typhoon4b-v01-q4_k_m"
BASE = "typhoon2.5-qwen3-4b-q4_k_m"
DRIVE_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz012345"  # made up; shaped like a Drive file id
SECRET_PATH = "/private-path-4f7a"  # stands for the part of a link that must never be printed
TOKEN = "fetch-test-TOKEN-9c1d"


class FakeLink:
    """A recording HTTP server: ``routes`` maps a path to (status, headers, body) or to ("redirect", location)."""

    def __init__(self, routes):
        self.routes, self.requests = routes, []
        link = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = self.path.split("?", 1)[0]
                link.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}})
                route = link.routes.get(path, (404, {}, b"not found"))
                if route[0] == "redirect":
                    self.send_response(302)
                    self.send_header("location", route[1])
                    self.send_header("content-length", "0")
                    return self.end_headers()
                status, headers, body = route
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                if "content-length" not in {name.lower() for name in headers}:
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


def octets(body=CONTENT):
    return (200, {"content-type": "application/octet-stream"}, body)


def link_fetch(url, dest, *, token=None, size=len(CONTENT), sha=SHA, drive_url=None, mask=None):
    kwargs = {"drive_url": drive_url} if drive_url else {}
    return fetch_model.fetch_link(url, token, "model.gguf", size, sha, Path(dest), mask=mask, **kwargs)


class PinFileTests(unittest.TestCase):
    def test_the_committed_pins_are_the_owners_reported_values(self):
        entry = fetch_model.load_profile(PINS, FINETUNE)
        self.assertEqual((entry["file"], entry["size"], entry["sha256"], entry["model_id"]),
                         ("nf_typhoon4b_v01_q4_k_m.gguf", 2_497_278_816,
                          "323ea4bb91fea1b6aa2e03fe845ca247f8c48de1e9e4d8da1841d48f18cc5c88",
                          "nf-typhoon4b-v01-q4_k_m:323ea4bb91fe"))
        self.assertEqual(entry["adapter_sha256"], "6d172e4ac9b177c78059f8318f38671b7ae1694d78da697e0b907a627bacd8ff")
        self.assertEqual(entry["base_model"], {"repo": "typhoon-ai/typhoon2.5-qwen3-4b",
                                               "revision": "ce0a7416fe82d4404b2b4a253ce3ac095ab1252c"})
        # Not published: a link from a secret, never cached in this public repository's Actions cache.
        self.assertEqual((entry["cache"], entry["source"]["kind"], entry["source"]["url_env"]),
                         (False, "link", "NF_MODEL_URL"))
        base = fetch_model.load_profile(PINS, BASE)
        self.assertEqual((base["model_id"], base["cache"], base["source"]["kind"], base["size"]),
                         ("typhoon2.5-qwen3-4b-q4_k_m:b36530292268", True, "huggingface", 2_497_276_128))
        self.assertRegex(base["source"]["revision"], r"^[0-9a-f]{40}$")
        from app.llm import LLMConfig
        for name in (FINETUNE, BASE):  # each model id is one the local provider accepts
            LLMConfig(provider="local", model=fetch_model.load_profile(PINS, name)["model_id"])

    def test_bad_entries_are_refused(self):
        document = json.loads(PINS.read_text(encoding="utf-8"))
        good = document["models"][FINETUNE]
        cases = {
            "cache": dict(good, cache=True),                                 # a private file in a public cache
            "sha256": dict(good, sha256="323EA4BB"),
            "size": dict(good, size="2497278816"),
            "file": dict(good, file="models/x.gguf"),
            "source.kind": dict(good, source={"kind": "ftp", "url_env": "NF_MODEL_URL"}),
            "url_env": dict(good, source={"kind": "link", "url_env": "lower-case"}),
            "entry needs": {key: value for key, value in good.items() if key != "license"},
        }
        with tempfile.TemporaryDirectory() as work:
            for problem, entry in cases.items():
                path = Path(work) / "pins.json"
                path.write_text(json.dumps({"schema": document["schema"], "models": {FINETUNE: entry}}),
                                encoding="utf-8")
                with self.assertRaisesRegex(fetch_model.FetchError, problem, msg=problem):
                    fetch_model.load_profile(path, FINETUNE)
            moving = dict(document["models"][BASE], source={"kind": "huggingface", "repo": "a/b", "revision": "main"})
            path.write_text(json.dumps({"schema": document["schema"], "models": {BASE: moving}}), encoding="utf-8")
            with self.assertRaisesRegex(fetch_model.FetchError, "40-digit commit"):
                fetch_model.load_profile(path, BASE)
        with self.assertRaisesRegex(fetch_model.FetchError, "no model 'other'"):
            fetch_model.load_profile(PINS, "other")

    def test_describe_needs_no_network_and_names_the_secret_not_its_value(self):
        with tempfile.TemporaryDirectory() as work:
            outputs = Path(work) / "out.txt"
            code = fetch_model.main(["--profile", str(PINS), "--model", FINETUNE, "--describe",
                                     "--github-output", str(outputs)], environ={})
            self.assertEqual(code, 0)
            values = dict(line.split("=", 1) for line in outputs.read_text().splitlines())
        self.assertEqual((values["model_id"], values["cache"], values["source"], values["url_env"]),
                         ("nf-typhoon4b-v01-q4_k_m:323ea4bb91fe", "false", "link", "NF_MODEL_URL"))


class LinkTests(unittest.TestCase):
    def test_a_link_is_kept_only_with_the_pinned_size_and_hash(self):
        with FakeLink({SECRET_PATH: octets()}) as link, tempfile.TemporaryDirectory() as dest:
            result = link_fetch(link.base_url + SECRET_PATH, dest)
            self.assertEqual(Path(result["path"]).read_bytes(), CONTENT)
            self.assertEqual((result["kind"], result["host"], result["reused"]), ("link", "this machine", False))
            again = link_fetch(link.base_url + SECRET_PATH, dest)  # restored file: checked, not downloaded again
        self.assertTrue(again["reused"])
        self.assertEqual(len(link.requests), 1)

    def test_wrong_bytes_or_sizes_are_never_kept(self):
        changed = CONTENT[:-1] + b"X"
        routes = {"/same-size": octets(changed), "/shorter": octets(CONTENT[:-5]),
                  "/announced": (200, {"content-length": str(len(CONTENT) + 1)}, CONTENT + b"!"),
                  # announces the pinned size, then the connection ends early: retried, then refused
                  "/cut": (200, {"content-length": str(len(CONTENT))}, CONTENT[:100])}
        original = fetch_model.time.sleep
        fetch_model.time.sleep = lambda _seconds: None
        try:
            with FakeLink(routes) as link, tempfile.TemporaryDirectory() as dest:
                for path, problem in (("/same-size", "does not match"), ("/shorter", "offers 16,383 bytes"),
                                      ("/announced", "offers"), ("/cut", "IncompleteRead after 3 attempts")):
                    with self.assertRaisesRegex(fetch_model.FetchError, problem, msg=path):
                        link_fetch(link.base_url + path, dest)
                    self.assertEqual(list(Path(dest).iterdir()), [], path)  # neither the file nor the .part is left
                with self.assertRaisesRegex(fetch_model.FetchError, "more than the pinned"):
                    fetch_model._stream(_Reply(CONTENT + b"tail"), Path(dest) / "x.part", len(CONTENT))
        finally:
            fetch_model.time.sleep = original
        self.assertEqual(sum(r["path"] == "/cut" for r in link.requests), 3)

    def test_a_token_reaches_the_first_host_only(self):
        with FakeLink({"/cdn/file": octets()}) as cdn, \
                FakeLink({SECRET_PATH: ("redirect", "/hop"), "/hop": ("redirect", cdn.base_url + "/cdn/file")}) as first, \
                tempfile.TemporaryDirectory() as dest:
            link_fetch(first.base_url + SECRET_PATH, dest, token=TOKEN)
        self.assertEqual(first.requests[0]["headers"].get("authorization"), f"Bearer {TOKEN}")
        self.assertNotIn("authorization", first.requests[1]["headers"])  # a redirect on the same host: not sent
        self.assertNotIn("authorization", cdn.requests[0]["headers"])    # nor to another server

    def test_a_redirect_off_https_is_refused(self):
        with FakeLink({SECRET_PATH: ("redirect", "http://models.example/file.gguf")}) as link, \
                tempfile.TemporaryDirectory() as dest:
            with self.assertRaisesRegex(fetch_model.FetchError, "left https"):
                link_fetch(link.base_url + SECRET_PATH, dest)
        for bad in ("http://models.example/x.gguf", "ftp://127.0.0.1/x", "https://user:pw@models.example/x", ""):
            with self.assertRaises(fetch_model.FetchError, msg=bad):
                fetch_model.download_address(bad)

    def test_google_drive_share_links_become_the_direct_download(self):
        for link in (f"https://drive.google.com/file/d/{DRIVE_ID}/view?usp=sharing",
                     f"https://drive.google.com/open?id={DRIVE_ID}",
                     f"https://drive.google.com/uc?id={DRIVE_ID}&export=download",
                     f"https://drive.usercontent.google.com/download?id={DRIVE_ID}&export=download"):
            address, kind, file_id = fetch_model.download_address(link)
            self.assertEqual((kind, file_id), ("google_drive", DRIVE_ID), link)
            self.assertEqual(address, "https://drive.usercontent.google.com/download?"
                                      f"id={DRIVE_ID}&export=download&confirm=t")
        with self.assertRaisesRegex(fetch_model.FetchError, "no file id"):
            fetch_model.download_address("https://drive.google.com/drive/folders/")
        self.assertEqual(fetch_model.download_address("https://models.example/m.gguf")[1:], ("link", None))

    def test_drives_cannot_scan_page_is_followed_once_without_the_token(self):
        page = (f'<html><body><form id="download-form" action="/download2" method="get">'
                f'<input type="hidden" name="id" value="{DRIVE_ID}"><input type="hidden" name="export" value="download">'
                f'<input type="hidden" name="confirm" value="t"><input type="hidden" name="uuid" value="u-123">'
                f'</form></body></html>').encode()
        routes = {"/download": (200, {"content-type": "text/html; charset=utf-8"}, page), "/download2": octets()}
        with FakeLink(routes) as drive, tempfile.TemporaryDirectory() as dest:
            masked = []
            result = link_fetch(f"https://drive.google.com/file/d/{DRIVE_ID}/view?usp=sharing", dest, token=TOKEN,
                                drive_url=drive.base_url + "/download", mask=masked.append)
            self.assertEqual(Path(result["path"]).read_bytes(), CONTENT)
        self.assertEqual((result["kind"], result["host"]), ("google_drive", "Google Drive"))
        first, second = drive.requests
        self.assertIn(f"id={DRIVE_ID}", first["path"])
        self.assertIn("confirm=t", first["path"])
        self.assertIn("uuid=u-123", second["path"])
        self.assertNotIn("authorization", second["headers"])
        self.assertIn(DRIVE_ID, masked)  # values derived from the secret are masked in the Actions log

    def test_drive_pages_that_are_not_the_file_say_what_to_do(self):
        pages = {"quota": b"<html><title>Google Drive - Quota exceeded</title>Too many users have viewed</html>",
                 "sign-in": b"<html><a href='https://accounts.google.com/ServiceLogin'>Sign in</a></html>",
                 "web page instead": b"<html><title>Something else</title></html>"}
        for problem, body in pages.items():
            with FakeLink({"/download": (200, {"content-type": "text/html"}, body)}) as drive, \
                    tempfile.TemporaryDirectory() as dest:
                with self.assertRaisesRegex(fetch_model.FetchError, problem, msg=problem):
                    link_fetch(f"https://drive.google.com/file/d/{DRIVE_ID}/view", dest,
                               drive_url=drive.base_url + "/download")
                self.assertEqual(list(Path(dest).iterdir()), [])

    def test_the_link_never_appears_in_what_is_printed_or_written(self):
        import contextlib
        import io
        document = json.loads(PINS.read_text(encoding="utf-8"))
        entry = dict(document["models"][FINETUNE], file="model.gguf", size=len(CONTENT), sha256=SHA)
        with FakeLink({SECRET_PATH: octets(), "/wrong": octets(b"wrong")}) as link, \
                tempfile.TemporaryDirectory() as work:
            pins = Path(work) / "pins.json"
            pins.write_text(json.dumps({"schema": document["schema"], "models": {FINETUNE: entry}}), encoding="utf-8")
            summary, outputs = Path(work) / "summary.md", Path(work) / "out.txt"
            for path, expected_code in ((SECRET_PATH, 0), ("/wrong", 1)):
                printed = io.StringIO()
                with contextlib.redirect_stdout(printed):
                    code = fetch_model.main(["--profile", str(pins), "--model", FINETUNE, "--dest",
                                             str(Path(work) / f"models-{expected_code}"), "--summary", str(summary),
                                             "--github-output", str(outputs)],
                                            environ={"NF_MODEL_URL": link.base_url + path, "NF_MODEL_TOKEN": TOKEN})
                self.assertEqual(code, expected_code, path)
                for text in (printed.getvalue(), summary.read_text(encoding="utf-8"),
                             outputs.read_text(encoding="utf-8") if outputs.exists() else ""):
                    for secret in (SECRET_PATH, link.base_url, TOKEN, "/wrong"):
                        self.assertNotIn(secret, text, path)
            values = dict(line.split("=", 1) for line in outputs.read_text().splitlines())
            self.assertEqual((values["sha256"], values["cache"], values["model_id"]),
                             (SHA, "false", f"{FINETUNE}:{SHA[:12]}"))
            self.assertIn("ลิงก์ส่วนตัวจาก secret `NF_MODEL_URL`", summary.read_text(encoding="utf-8"))

    def test_in_actions_the_only_lines_with_the_link_are_mask_commands(self):
        import contextlib
        import io
        document = json.loads(PINS.read_text(encoding="utf-8"))
        entry = dict(document["models"][FINETUNE], file="model.gguf", size=len(CONTENT), sha256=SHA)
        with FakeLink({SECRET_PATH: octets()}) as link, tempfile.TemporaryDirectory() as work:
            pins = Path(work) / "pins.json"
            pins.write_text(json.dumps({"schema": document["schema"], "models": {FINETUNE: entry}}), encoding="utf-8")
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                code = fetch_model.main(["--profile", str(pins), "--model", FINETUNE, "--dest", str(Path(work) / "m")],
                                        environ={"GITHUB_ACTIONS": "true", "NF_MODEL_URL": link.base_url + SECRET_PATH,
                                                 "NF_MODEL_TOKEN": TOKEN})
        self.assertEqual(code, 0)
        lines = printed.getvalue().splitlines()
        with_secret = [line for line in lines if SECRET_PATH in line or TOKEN in line]
        self.assertTrue(with_secret)  # the link and the token are masked before anything else is printed
        self.assertTrue(all(line.startswith("::add-mask::") for line in with_secret), with_secret)
        first_other = next(i for i, line in enumerate(lines) if not line.startswith("::add-mask::"))
        self.assertTrue(all(not line.startswith("::add-mask::") for line in lines[first_other:]))

    def test_a_missing_secret_names_the_secret_to_add(self):
        with tempfile.TemporaryDirectory() as work:
            summary = Path(work) / "summary.md"
            code = fetch_model.main(["--profile", str(PINS), "--model", FINETUNE, "--dest", str(Path(work) / "m"),
                                     "--summary", str(summary)], environ={})
            self.assertEqual(code, 1)
            self.assertIn("NF_MODEL_URL", summary.read_text(encoding="utf-8"))

    def test_a_private_hub_repository_gets_the_token_but_its_file_store_does_not(self):
        with FakeHub() as hub, tempfile.TemporaryDirectory() as work:
            document = json.loads(PINS.read_text(encoding="utf-8"))
            entry = {**document["models"][BASE], "size": len(CONTENT), "sha256": SHA,
                     "source": {"kind": "huggingface", "repo": REPO, "revision": COMMIT, "token_env": "HF_TOKEN"}}
            pins = Path(work) / "pins.json"
            pins.write_text(json.dumps({"schema": document["schema"], "models": {BASE: entry}}), encoding="utf-8")
            result = fetch_model.fetch_profile(fetch_model.load_profile(pins, BASE), Path(work) / "m",
                                               {"HF_TOKEN": TOKEN}, base_url=hub.base_url)
            self.assertEqual(Path(result["path"]).read_bytes(), CONTENT)
            wrong_size = dict(entry, size=len(CONTENT) + 1)
            pins.write_text(json.dumps({"schema": document["schema"], "models": {BASE: wrong_size}}), encoding="utf-8")
            with self.assertRaisesRegex(fetch_model.FetchError, "pinned size"):
                fetch_model.fetch_profile(fetch_model.load_profile(pins, BASE), Path(work) / "n",
                                          {"HF_TOKEN": TOKEN}, base_url=hub.base_url)
        self.assertEqual(len(hub.downloads()), 1)
        self.assertTrue(all(h.get("authorization") == f"Bearer {TOKEN}" for p, h in hub.seen if p.startswith("/api/")))
        self.assertTrue(all("authorization" not in h for p, h in hub.seen if p.startswith("/cdn/")))


class _Reply:
    """A stand-in for a response that sends more bytes than it announced."""

    def __init__(self, body):
        self.headers, self._body = {}, [body, b""]

    def read(self, _size):
        return self._body.pop(0)


if __name__ == "__main__":
    unittest.main()
