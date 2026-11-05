"""The study library's link check (roadmap 3.1), against a local HTTP server: no internet needed."""

import contextlib
import http.server
import io
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.request

from app.domains.study_guide import link_check
from app.domains.study_guide.library import CATALOG_DIR, LibraryError
from app.domains.study_guide.link_check import LinkResult, build_opener, check_url


class _Handler(http.server.BaseHTTPRequestHandler):
    hits = {}
    agents = []

    def log_message(self, *args):
        pass

    def _send(self, status, body=b"", content_type="text/html; charset=utf-8", headers=()):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path
        type(self).hits[path] = type(self).hits.get(path, 0) + 1
        type(self).agents.append(self.headers.get("User-Agent"))
        if path == "/ok":
            self._send(200, b"<html><head><TITLE>\n  Guide &amp; map | `site` </TITLE></head></html>")
        elif path == "/thai":
            self._send(200, "<title>คู่มือภาษาไทย</title>".encode("utf-8"))
        elif path == "/notitle":
            self._send(200, b"<html><body>no title</body></html>")
        elif path == "/slash":
            self._send(301, headers=[("Location", "/slash/")])
        elif path == "/slash/":
            self._send(200, b"<title>Slash</title>")
        elif path == "/moved":
            self._send(301, headers=[("Location", "/ok")])
        elif path == "/gone":
            self._send(404, b"not here")
        elif path == "/blocked":
            self._send(403, b"no bots")
        elif path == "/limited":
            self._send(429, b"slow down")
        elif path == "/flaky":
            self._send(503 if type(self).hits[path] == 1 else 200, b"<title>Back</title>")
        elif path == "/down":
            self._send(500, b"broken")
        elif path == "/loop":
            self._send(302, headers=[("Location", "/loop")])
        elif path == "/pdf":
            self._send(200, b"%PDF-1.4\n1 0 obj << /Title (Cognitive load \\(CLT\\)) >> endobj", "application/pdf")
        elif path == "/slow":
            time.sleep(1.0)
            self._send(200, b"<title>Late</title>")
        else:
            self._send(404)


class LinkCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.server.daemon_threads = True
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.opener = build_opener(proxies={})

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        _Handler.hits.clear()
        _Handler.agents.clear()

    def check(self, path, timeout=5.0):
        return check_url("r", self.base + path, timeout=timeout, retry_delays=(0, 0), opener=self.opener)

    def test_a_working_page_is_ok_with_its_title_cleaned(self):
        result = self.check("/ok")
        self.assertEqual((result.outcome, result.status, result.attempts), ("ok", 200, 1))
        self.assertEqual(result.title, "Guide & map / 'site'")
        self.assertEqual(self.check("/thai").title, "คู่มือภาษาไทย")
        self.assertEqual(self.check("/notitle").title, "")

    def test_a_redirect_that_only_adds_a_slash_is_still_ok(self):
        result = self.check("/slash")
        self.assertEqual((result.outcome, result.title), ("ok", "Slash"))

    def test_a_redirect_elsewhere_is_moved_and_names_the_new_address(self):
        result = self.check("/moved")
        self.assertEqual(result.outcome, "moved")
        self.assertTrue(result.final_url.endswith("/ok"))
        self.assertIn("now answers at", result.detail)

    def test_missing_pages_are_broken_and_not_retried(self):
        result = self.check("/gone")
        self.assertEqual((result.outcome, result.status, result.attempts), ("broken", 404, 1))
        self.assertEqual(_Handler.hits["/gone"], 1)

    def test_refused_automated_visits_are_blocked_not_broken(self):
        for path, status in (("/blocked", 403), ("/limited", 429)):
            result = self.check(path)
            self.assertEqual((result.outcome, result.status), ("blocked", status), path)
            self.assertIn("check it by hand", result.detail)

    def test_server_errors_are_retried_twice_after_the_delays(self):
        waits = []
        result = check_url("r", self.base + "/flaky", timeout=5, retry_delays=(0.01, 0.02), opener=self.opener,
                           sleep=waits.append)
        self.assertEqual((result.outcome, result.attempts, result.title), ("ok", 2, "Back"))
        self.assertEqual(waits, [0.01], "no further wait after the page came back")
        waits.clear()
        result = check_url("r", self.base + "/down", timeout=5, retry_delays=(0.01, 0.02), opener=self.opener,
                           sleep=waits.append)
        self.assertEqual((result.outcome, result.status, result.attempts), ("broken", 500, 3))
        self.assertEqual((_Handler.hits["/down"], waits), (3, [0.01, 0.02]))
        self.assertEqual(link_check.RETRY_DELAYS, (5.0, 20.0))

    def test_a_redirect_loop_is_broken(self):
        result = self.check("/loop")
        self.assertEqual(result.outcome, "broken")
        self.assertIn("redirect loop", result.detail)

    def test_a_pdf_is_ok_and_its_metadata_title_is_read(self):
        result = self.check("/pdf")
        self.assertEqual((result.outcome, result.title), ("ok", "Cognitive load (CLT)"))

    def test_a_timeout_is_broken_after_the_retries(self):
        result = self.check("/slow", timeout=0.2)
        self.assertEqual((result.outcome, result.attempts), ("broken", 3))
        self.assertIn("no answer within 0.2 s", result.detail)

    def test_a_closed_port_is_broken(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        result = check_url("r", f"http://127.0.0.1:{port}/", timeout=2, retry_delays=(0, 0), opener=self.opener)
        self.assertEqual((result.outcome, result.status, result.attempts), ("broken", None, 3))
        self.assertEqual(result.detail, "connection refused")

    def test_https_to_http_redirects_are_refused(self):
        handler = link_check._RedirectHandler()
        request = urllib.request.Request("https://example.org/a")
        with self.assertRaises(link_check.InsecureRedirect):
            handler.redirect_request(request, None, 301, "Moved", {}, "http://example.org/b")
        self.assertIsNotNone(handler.redirect_request(request, None, 301, "Moved", {}, "https://example.org/b"))

    def test_the_client_name_is_generic(self):
        self.check("/ok")
        self.assertEqual(_Handler.agents, [link_check.USER_AGENT])
        self.assertNotIn("@", link_check.USER_AGENT)


def _fake_results(outcomes):
    """A check_url stand-in that answers ``outcomes[resource_id]`` (default ok)."""
    def fake(resource_id, url, **kwargs):
        outcome = outcomes.get(resource_id, "ok")
        detail = {"ok": "", "moved": "now answers at https://example.org/new",
                  "blocked": "HTTP 403: the site refused an automated check; check it by hand",
                  "broken": "HTTP 404"}[outcome]
        status = {"ok": 200, "moved": 200, "blocked": 403, "broken": 404}[outcome]
        return LinkResult(resource_id, url, outcome, status, url, "Title | with `ticks`\nand lines", detail, 1)
    return fake


class MainTests(unittest.TestCase):
    def run_main(self, outcomes):
        with tempfile.TemporaryDirectory() as folder:
            summary = os.path.join(folder, "summary.md")
            out = io.StringIO()
            with mock.patch.object(link_check, "check_url", _fake_results(outcomes)), \
                    contextlib.redirect_stdout(out):
                code = link_check.main(["--summary", summary])
            return code, Path(summary).read_text(encoding="utf-8"), out.getvalue()

    def test_all_links_working_passes(self):
        before = {p.name: p.read_bytes() for p in CATALOG_DIR.iterdir()}
        code, summary, out = self.run_main({})
        self.assertEqual(code, 0)
        self.assertIn("(study library link check): ผ่าน", summary)
        self.assertNotIn("::error", out)
        self.assertEqual({p.name: p.read_bytes() for p in CATALOG_DIR.iterdir()}, before,
                         "the link check must never edit the library")

    def test_a_broken_link_fails_and_moved_or_blocked_links_only_warn(self):
        code, summary, out = self.run_main({"thai_mooc": "broken", "roadmap_sh_ai_agents": "moved",
                                            "iso_24495_1": "blocked"})
        self.assertEqual(code, 1)
        self.assertIn("(study library link check): ไม่ผ่าน", summary)
        self.assertIn("เสีย 1", summary)
        self.assertIn("::error title=Broken study link::thai_mooc: https://thaimooc.ac.th/ — HTTP 404", out)
        self.assertIn("::warning title=Study link moved::roadmap_sh_ai_agents", out)
        self.assertIn("::warning title=Study link blocked::iso_24495_1", out)
        code, _, _ = self.run_main({"roadmap_sh_ai_agents": "moved", "iso_24495_1": "blocked"})
        self.assertEqual(code, 0)

    def test_page_titles_cannot_break_the_summary_table(self):
        _, summary, _ = self.run_main({})
        rows = [line for line in summary.splitlines() if line.startswith("| ✅")]
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row.count("|"), 6, row)  # five cells
            self.assertIn("`Title / with 'ticks' and lines`", row)

    def test_an_invalid_library_fails_without_checking_any_link(self):
        called = mock.Mock()
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(link_check, "load_library", side_effect=LibraryError(["topic x: bad"])), \
                mock.patch.object(link_check, "check_url", called), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            summary = os.path.join(folder, "summary.md")
            code = link_check.main(["--summary", summary])
            text = Path(summary).read_text(encoding="utf-8")
        self.assertEqual(code, 2)
        called.assert_not_called()
        self.assertIn("::error title=Study library is invalid::topic x: bad", out.getvalue())
        self.assertIn("ไม่ผ่าน", text)

    def test_annotations_escape_line_breaks(self):
        self.assertEqual(link_check._annotation("a%b\nc\rd"), "a%25b%0Ac%0Dd")


if __name__ == "__main__":
    unittest.main()
