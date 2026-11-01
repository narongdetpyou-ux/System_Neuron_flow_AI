"""The HTTP server for the API and the web page (standard library only).

Python's ``http.server`` is enough for a single-owner pilot behind Railway's HTTPS edge, with these
guards:
* a socket timeout on every read, so a stalled client cannot hold a thread for long;
* a cap on concurrent connections (extra connections get an immediate 503);
* a body cap checked from ``Content-Length`` before anything is read;
* access log lines without query strings, bodies, headers or job ids.
For real traffic, put a production web server in front of the same ``ApiApp`` (see
docs/intake_queue.md).
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import logging
import socket
import threading
import time
from urllib.parse import parse_qs, urlsplit

from .routes import MAX_BODY_BYTES, Request, error, finalize, route_label

SOCKET_TIMEOUT_S = 15
_BUSY = (b"HTTP/1.0 503 Service Unavailable\r\nContent-Type: application/json\r\nContent-Length: 20\r\n"
         b"Retry-After: 1\r\nConnection: close\r\n\r\n{\"error\":\"too_busy\"}")
log = logging.getLogger("neuron_flow.http")


class _Handler(BaseHTTPRequestHandler):
    timeout = SOCKET_TIMEOUT_S

    def version_string(self):
        return "neuron-flow"

    def log_message(self, *_args):  # the default prints full paths; _serve logs a safe line instead
        pass

    def do_GET(self):
        self._serve()

    do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_GET

    def _client(self):
        forwarded = self.headers.get("X-Forwarded-For", "")
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        # The last hop was added by the platform's proxy; earlier ones are whatever the client sent.
        return hops[-1][:64] if hops else self.client_address[0]

    def _read_body(self):
        length = self.headers.get("Content-Length")
        if length is None:
            if self.command in ("POST", "PUT", "PATCH"):
                return None, error(411, "length_required", "Send a Content-Length header")
            return b"", None
        if not (length.isascii() and length.isdigit()):
            return None, error(400, "bad_request", "Invalid Content-Length")
        size = int(length)
        if size > MAX_BODY_BYTES:
            return None, error(413, "body_too_large", f"The body is larger than {MAX_BODY_BYTES} bytes")
        body = self.rfile.read(size)
        if len(body) != size:
            return None, error(400, "bad_request", "The body ended early")
        return body, None

    def _respond(self, split):
        body, response = self._read_body()
        if response is not None:
            return finalize(response)
        try:
            query = parse_qs(split.query, keep_blank_values=True, max_num_fields=20)
        except ValueError:
            return finalize(error(400, "bad_request", "Too many query parameters"))
        request = Request(self.command, split.path or "/", query,
                          {name.lower(): value for name, value in self.headers.items()}, body, self._client())
        return self.server.app.handle(request)

    def _serve(self):
        started = time.monotonic()
        split = urlsplit(self.path)
        try:
            response = self._respond(split)
        except (socket.timeout, ConnectionError):  # the client stalled or left while sending
            self.close_connection = True
            response = None
        # Log before replying, so the line never arrives after the client has its answer.
        log.info("%s %s %s %.0fms", self.command, route_label(split.path),
                 response.status if response is not None else "-", (time.monotonic() - started) * 1000)
        if response is None:
            return
        try:
            self.send_response(response.status)
            for name, value in response.headers:
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(response.body)))
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(response.body)
        except (socket.timeout, ConnectionError):
            self.close_connection = True


class ApiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64

    def __init__(self, address, app, *, max_connections=32):
        if ":" in address[0]:
            self.address_family = socket.AF_INET6
        self.app = app
        self._slots = threading.BoundedSemaphore(max_connections)
        super().__init__(address, _Handler)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            try:
                request.settimeout(1)
                request.sendall(_BUSY)
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def make_server(settings, app):
    return ApiServer((settings.host, settings.port), app, max_connections=settings.max_connections)
