"""The service over a real socket, plus the launcher pieces (boot, privileges, Runner supervision, settings)."""

import json
import logging
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from app import boot
from app.api import ApiApp, make_server
from app.api.limits import RateLimiter
from app.boot import drop_privileges
from app.persistence import QueueStore
from app.serve import RunnerSupervisor
from app.services.runner import Runner
from app.settings import Settings, SettingsError
from tests.service_fixtures import KEY, case_body, settings, wait_for


class LiveServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temp = tempfile.TemporaryDirectory()
        cls.settings = settings(cls._temp.name, host="127.0.0.1", port=0, max_connections=8)
        cls.store = QueueStore(cls.settings.queue_db)
        cls.store.migrate()
        cls.server = make_server(cls.settings, ApiApp(cls.settings, cls.store))
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls._temp.cleanup()

    def request(self, method, path, body=None, headers=None):
        data = None if body is None else json.dumps(body).encode()
        all_headers = {"Authorization": f"Bearer {KEY}", **({"Content-Type": "application/json"} if data else {}),
                       **(headers or {})}
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=all_headers)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, dict(exc.headers), exc.read()

    def test_submit_run_and_read_back_over_http(self):
        status, headers, body = self.request("POST", "/v1/jobs", case_body("key-http-0001"))
        self.assertEqual(status, 202)
        job_id = json.loads(body)["job_id"]
        self.assertEqual(headers["Location"], f"/v1/jobs/{job_id}")
        self.assertEqual(self.request("POST", "/v1/jobs", case_body("key-http-0001"))[0], 200)
        Runner(self.settings, store=self.store).drain()
        status, _headers, body = self.request("GET", f"/v1/jobs/{job_id}")
        self.assertEqual((status, json.loads(body)["status"]), (200, "REVIEW_REQUIRED"))

    def test_page_health_and_head(self):
        status, headers, body = self.request("GET", "/", headers={"Authorization": ""})
        self.assertEqual(status, 200)
        self.assertIn("Content-Security-Policy", headers)
        self.assertEqual(headers["Server"], "neuron-flow")
        status, _headers, body = self.request("HEAD", "/healthz")
        self.assertEqual((status, body), (200, b""))

    def test_oversized_body_is_refused_before_it_is_read(self):
        jobs_before = self.store.counts()
        with socket.create_connection(self.server.server_address[:2], timeout=5) as connection:
            connection.sendall(b"POST /v1/jobs HTTP/1.1\r\nHost: test\r\nContent-Type: application/json\r\n"
                               b"Authorization: Bearer " + KEY.encode() + b"\r\nContent-Length: 99999999\r\n\r\n")
            reply = connection.recv(4096)  # answered at once, although no body byte was sent
        self.assertTrue(reply.startswith(b"HTTP/1.0 413"), reply[:40])
        self.assertEqual(self.store.counts(), jobs_before)

    def test_post_without_a_length_is_refused(self):
        with socket.create_connection(self.server.server_address[:2], timeout=5) as connection:
            connection.sendall(b"POST /v1/jobs HTTP/1.0\r\nContent-Type: application/json\r\n\r\n")
            reply = connection.recv(4096)
        self.assertTrue(reply.startswith(b"HTTP/1.0 411"), reply[:40])

    def test_access_log_lines_hide_query_strings_and_job_ids(self):
        with self.assertLogs("neuron_flow.http", level="INFO") as logs:
            self.request("GET", "/v1/jobs?limit=5&before=99")
            self.request("GET", "/v1/jobs/job_0123456789abcdef01234567/events?after=3")
        joined = "\n".join(logs.output)
        self.assertIn("GET /v1/jobs 200", joined)
        self.assertIn("/v1/jobs/{job_id}/events", joined)
        self.assertNotIn("limit=5", joined)
        self.assertNotIn("0123456789abcdef", joined)
        self.assertNotIn(KEY, joined)


class LimiterTests(unittest.TestCase):
    def test_tokens_come_back_over_time(self):
        now = [0.0]
        limiter = RateLimiter(2, 60, clock=lambda: now[0])
        self.assertEqual([limiter.allow("a")[0] for _ in range(3)], [True, True, False])
        self.assertEqual(limiter.allow("a")[1], 30)
        now[0] += 30
        self.assertTrue(limiter.allow("a")[0])

    def test_the_shared_bucket_caps_many_clients(self):
        limiter = RateLimiter(5, 60, total_capacity=3, clock=lambda: 0.0)
        self.assertEqual([limiter.allow(f"client-{n}")[0] for n in range(4)], [True, True, True, False])

    def test_the_client_map_stays_bounded(self):
        limiter = RateLimiter(1, 60, max_clients=10, clock=lambda: 0.0)
        for n in range(100):
            limiter.allow(f"client-{n}")
        self.assertEqual(len(limiter._clients), 10)


class LauncherTests(unittest.TestCase):
    def test_settings_find_the_railway_volume_and_validate_numbers(self):
        found = Settings.from_env({"RAILWAY_VOLUME_MOUNT_PATH": "/var/data", "NEURON_FLOW_ACCESS_KEY": KEY, "PORT": "9000"})
        self.assertEqual((found.data_dir, found.storage, found.persistent, found.port),
                         (Path("/var/data"), "railway_volume", True, 9000))
        self.assertEqual(Settings.from_env({"NEURON_FLOW_DATA_DIR": "/srv/data", "RAILWAY_VOLUME_MOUNT_PATH": "/x"}).storage,
                         "configured")
        local = Settings.from_env({})
        self.assertEqual((local.storage, local.persistent, local.access_key, local.access_key_problem),
                         ("local_default", False, None, "missing"))
        self.assertEqual(Settings.from_env({"NEURON_FLOW_ACCESS_KEY": "short"}).access_key_problem, "too_short")
        with self.assertRaises(SettingsError):
            Settings.from_env({"PORT": "eighty"})
        with self.assertRaises(SettingsError):
            Settings.from_env({"NEURON_FLOW_MAX_QUEUED": "0"})

    def test_privileges_are_only_dropped_inside_the_image(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertFalse(drop_privileges(temp, user="no-such-user-for-neuron-flow-tests"))

    def test_the_supervisor_stops_its_runner(self):
        supervisor = RunnerSupervisor([sys.executable, "-c", "import time; time.sleep(60)"])
        supervisor.start()
        wait_for(lambda: supervisor.process is not None and supervisor.process.poll() is None, timeout=10)
        started = time.monotonic()
        supervisor.stop(grace_s=5)
        self.assertIsNotNone(supervisor.process.poll())
        self.assertLess(time.monotonic() - started, 6)

    def test_the_supervisor_restarts_a_runner_that_exits(self):
        supervisor = RunnerSupervisor([sys.executable, "-c", "pass"])
        supervisor.start()
        first = wait_for(lambda: supervisor.process, timeout=10)
        wait_for(lambda: supervisor.process is not first, timeout=10)
        supervisor.stop(grace_s=2)


class BootTests(unittest.TestCase):
    """``python -m app.boot``: process 1 of the image. It must hand over to tini, because a root tini
    cannot pass stop signals on where root lacks CAP_KILL (Render); the container check covers the rest."""

    NO_USER = "no-such-user-for-neuron-flow-tests"

    def _boot(self, argv, execv):
        with tempfile.TemporaryDirectory() as temp:
            code = boot.main(argv, environ={"NEURON_FLOW_DATA_DIR": temp}, user=self.NO_USER, execv=execv)
            folders = sorted(path.name for path in Path(temp).iterdir())
        return code, folders

    def test_boot_prepares_the_data_folder_and_hands_the_service_to_tini(self):
        calls = []
        code, folders = self._boot([], lambda path, args: calls.append((path, args)))
        self.assertEqual(code, 0)
        self.assertEqual(folders, ["app", "core"])
        self.assertEqual(calls, [("/usr/bin/tini", ["/usr/bin/tini", "--", "python", "-m", "app.serve"])])

    def test_boot_runs_the_command_it_is_given_under_tini(self):
        calls = []
        self._boot(["python", "-m", "app.services.runner"], lambda path, args: calls.append(args))
        self.assertEqual(calls, [["/usr/bin/tini", "--", "python", "-m", "app.services.runner"]])

    def test_boot_explains_a_missing_tini_instead_of_crashing(self):
        def missing(path, args):
            raise FileNotFoundError(path)

        with self.assertLogs("neuron_flow.boot", "ERROR") as logs:
            code, _ = self._boot([], missing)
        self.assertEqual(code, 1)
        self.assertIn("python -m app.serve", logs.output[0])


class ServeEndToEndTests(unittest.TestCase):
    """``python -m app.serve`` as the container runs it: API + supervised Runner, then SIGTERM."""

    def test_the_service_starts_works_and_stops_cleanly(self):
        with tempfile.TemporaryDirectory() as temp:
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            env = {"PATH": "/usr/bin:/bin", "NEURON_FLOW_DATA_DIR": temp, "NEURON_FLOW_ACCESS_KEY": KEY,
                   "NEURON_FLOW_HOST": "127.0.0.1", "PORT": str(port), "PYTHONDONTWRITEBYTECODE": "1"}
            root = Path(__file__).resolve().parent.parent
            service = subprocess.Popen([sys.executable, "-m", "app.serve"], cwd=root, env=env,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            try:
                base = f"http://127.0.0.1:{port}"
                wait_for(lambda: _get(base + "/healthz") == 200, timeout=30)
                request = urllib.request.Request(base + "/v1/jobs", method="POST",
                                                 data=json.dumps(case_body("key-serve-0001")).encode(),
                                                 headers={"Authorization": f"Bearer {KEY}",
                                                          "Content-Type": "application/json"})
                with urllib.request.urlopen(request, timeout=10) as response:
                    job_id = json.loads(response.read())["job_id"]

                def finished():
                    detail = _json(base + f"/v1/jobs/{job_id}")
                    return detail if detail["status"] == "REVIEW_REQUIRED" else None

                wait_for(finished, timeout=30)
                status = _json(base + "/v1/status")
                self.assertTrue(status["runner"]["alive"])
            finally:
                service.terminate()
                output, _ = service.communicate(timeout=40)
            self.assertEqual(service.returncode, 0, output)
            self.assertIn("serve: stopping", output)
            self.assertIn("runner: stopping after the current job", output)
            self.assertNotIn(KEY, output)


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status
    except (urllib.error.URLError, OSError):
        return None


def _json(url):
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {KEY}"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read())


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    unittest.main()
