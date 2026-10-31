"""A local stand-in for the Claude Messages API, so the real HTTP code path is tested offline."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time


def message(answer, *, stop_reason="end_turn", model="claude-haiku-5-5-20261001", thinking=True):
    """A Messages API reply whose text block holds the JSON answer (structured output)."""
    content = [{"type": "thinking", "thinking": "", "signature": "sig"}] if thinking else []
    content.append({"type": "text", "text": answer if isinstance(answer, str) else json.dumps(answer)})
    return {"id": "msg_test", "type": "message", "role": "assistant", "model": model, "content": content,
            "stop_reason": stop_reason, "usage": {"input_tokens": 120, "output_tokens": 30,
                                                  "cache_read_input_tokens": 5}}


def error(status, error_type):
    return status, {"type": "error", "error": {"type": error_type, "message": "echo: SECRET-CASE-TEXT"}}


class FakeAnthropic:
    """Replies are consumed in order; the last one repeats. Each reply: (status, body[, delay_s[, headers]])."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        self._lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("content-length", 0)))
                with fake._lock:
                    fake.requests.append({"path": self.path, "headers": dict(self.headers),
                                          "body": json.loads(body)})
                    reply = fake.replies.pop(0) if len(fake.replies) > 1 else fake.replies[0]
                status, payload = reply[0], reply[1]
                if len(reply) > 2 and reply[2]:
                    time.sleep(reply[2])
                data = payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
                try:
                    self.send_response(status)
                    for name, value in (reply[3] if len(reply) > 3 else {}).items():
                        self.send_header(name, value)
                    self.send_header("content-type", "application/json")
                    self.send_header("content-length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the client gave up (timeout test)

            def do_GET(self):  # a followed 301/302 turns the POST into a GET; record it too
                with fake._lock:
                    fake.requests.append({"path": self.path, "headers": dict(self.headers), "body": None})
                self.send_response(405)
                self.send_header("content-length", "0")
                self.end_headers()

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self._thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05},
                                        daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
