"""A stand-in for llama.cpp's ``llama-server`` (ADR-026), so the local model lane can be tested without a model file.

It answers the endpoints the lane uses, in llama.cpp's shapes:

* ``GET /health``: ``{"status": "ok"}``, or 503 while it pretends to load (``loading_s``);
* ``GET /v1/models``: the alias as the model id;
* ``GET /props``: the model file's path, the chat template, the number of slots and a build string;
* ``GET /metrics``: Prometheus counters of prompt and generated tokens and the seconds spent on them;
* ``POST /v1/chat/completions``: an OpenAI-format chat completion. The answer comes from a few keyword rules over
  the case text (English and Thai), written in the key order of the request's ``response_format`` schema, so it
  always passes the gateway's checks unless a fault is asked for.

Faults, for the error paths: ``POST /_control`` with ``{"mode": ..., "count": N, "delay_s": seconds}`` makes the
next N chat requests (all when N is -1) behave in one of these ways: ``invalid_json`` (prose instead of JSON),
``bad_enum`` (a category outside the schema), ``wrong_keys``, ``http_500``, ``http_503`` (llama.cpp's "loading
model"), ``cut_off`` (``finish_reason: length``), ``content_filter``, ``refusal``, or ``ok`` (with ``delay_s``, a
slow but good answer). The real server has no ``/_control``; the end-to-end check uses it only when asked to.

Every request is recorded (path, headers, body) so tests can check what reached the model: masked text, no key.

Run it like the real server, for the lane's own tests (unknown llama.cpp flags are accepted and ignored); with
``--fake-delay-s`` every answer is that slow, like a real model on a processor, and ``--fake-loading-s`` answers 503
for that long first, like a model that is still loading:

    python tests/fake_llama_server.py -m model.gguf --alias name:0123456789ab --host 127.0.0.1 --port 8080
"""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sys
import threading
import time

TEMPLATE = "{% for m in messages %}<|im_start|>{{ m.role }}\n{{ m.content }}<|im_end|>\n{% endfor %}"  # Qwen-like
MODES = {"ok", "invalid_json", "bad_enum", "wrong_keys", "http_500", "http_503", "cut_off", "content_filter",
         "refusal"}

_CATEGORY_WORDS = (
    ("billing", ("charge", "charged", "refund", "invoice", "payment", "billing", "billed", "subscription", "card",
                 "receipt", "money", "เงิน", "ใบแจ้งหนี้", "ใบเสร็จ", "ชำระ", "สมัครสมาชิก", "บัตร", "หักเงิน")),
    ("upload", ("upload", "uplod", "attach", "file", "pdf", "screenshot", "อัปโหลด", "อัพโหลด", "แนบ", "ไฟล์")),
    ("access", ("password", "log in", "login", "sign in", "locked", "otp", "2fa", "verification", "account",
                "รหัสผ่าน", "เข้าสู่ระบบ", "ล็อกอิน", "บัญชี", "รหัส otp")),
)
_ATTENTION_WORDS = (
    ("distress", ("don't see the point", "ไม่อยากอยู่", "threat", "danger", "ข่มขู่")),
    ("security", ("stolen", "someone changed", "phishing", "scam", "former employee", "อดีตพนักงาน", "หาย",
                  "มีคนเปลี่ยน")),
    ("legal_privacy", ("lawyer", "court", "data protection", "pdpa", "gdpr", "ทนาย", "กฎหมาย")),
    ("instruction", ("ignore all previous", "ignore previous", "system:", "classify this as", "developer mode",
                     "ไม่ต้องสนใจคำสั่ง", "ไม่ต้องสนคำสั่ง", "ให้จัดเป็น", "จัดเป็น")),
)


def classify(text):
    """A deterministic answer for one case text: (category, attention)."""
    lowered = text.lower()
    category = next((name for name, words in _CATEGORY_WORDS if any(w in lowered for w in words)), "other")
    attention = next((name for name, words in _ATTENTION_WORDS if any(w in lowered for w in words)), "none")
    return category, attention


def case_text(messages):
    """The case text from the user message (the prompt puts it last, as a JSON object on its own line)."""
    user = next((m.get("content") for m in reversed(messages) if m.get("role") == "user"), "") or ""
    last = user.rsplit("\n", 1)[-1]
    try:
        value = json.loads(last)
        return next((v for v in value.values() if isinstance(v, str)), user) if isinstance(value, dict) else user
    except ValueError:
        return user


def answer_for(body):
    schema = ((body.get("response_format") or {}).get("json_schema") or {}).get("schema") or {}
    properties = schema.get("properties") or {"category": {}, "confidence": {}, "rationale": {}}
    category, attention = classify(case_text(body.get("messages") or []))
    values = {"category": category, "attention": attention, "confidence": "high" if category != "other" else "medium",
              "rationale": "The fake server matched a keyword."}
    answer = {}
    for name, spec in properties.items():
        value = values.get(name, "fake")
        if "enum" in spec and value not in spec["enum"]:
            value = spec["enum"][0]
        answer[name] = value
    return answer


class FakeLlamaServer:
    def __init__(self, *, alias="fake-model:0123456789ab", model_path="/models/fake.gguf", host="127.0.0.1", port=0,
                 loading_s=0.0, slots=2, base_delay_s=0.0):
        self.alias, self.model_path, self.slots = alias, model_path, slots
        self.base_delay_s = base_delay_s  # every answer takes at least this long, like a real model on a CPU
        self.requests, self._lock = [], threading.Lock()
        self.mode, self.count, self.delay_s = "ok", 0, 0.0
        self.ready_at = time.monotonic() + loading_s
        self.counters = {"prompt_tokens_total": 0, "prompt_seconds_total": 0.0, "tokens_predicted_total": 0,
                         "tokens_predicted_seconds_total": 0.0, "requests_processing": 0}
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                fake._record(self.path, self.headers, None)
                if self.path == "/health":
                    if time.monotonic() < fake.ready_at:
                        return self._json(503, {"error": {"code": 503, "message": "Loading model",
                                                          "type": "unavailable_error"}})
                    return self._json(200, {"status": "ok"})
                if self.path == "/v1/models":
                    return self._json(200, {"object": "list", "data": [{"id": fake.alias, "object": "model",
                                                                        "owned_by": "llamacpp", "created": 0,
                                                                        "meta": {"n_params": 4_000_000_000}}]})
                if self.path == "/props":
                    return self._json(200, {"model_path": fake.model_path, "chat_template": TEMPLATE,
                                            "total_slots": fake.slots, "build_info": "fake-llama-server"})
                if self.path == "/metrics":
                    with fake._lock:
                        lines = [f"llamacpp:{name} {value}" for name, value in fake.counters.items()]
                    return self._text(200, "\n".join(lines) + "\n")
                return self._json(404, {"error": {"code": 404, "message": "File Not Found", "type": "not_found_error"}})

            def do_POST(self):
                length = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(length)
                try:
                    body = json.loads(raw or b"{}")
                except ValueError:
                    return self._json(400, {"error": {"code": 400, "message": "bad json", "type": "invalid_request_error"}})
                fake._record(self.path, self.headers, body)
                if self.path == "/_control":
                    mode = body.get("mode", "ok")
                    if mode not in MODES:
                        return self._json(400, {"error": f"unknown mode {mode}"})
                    with fake._lock:
                        fake.mode, fake.count = mode, int(body.get("count", -1))
                        fake.delay_s = float(body.get("delay_s", 0.0))
                    return self._json(200, {"mode": mode})
                if self.path != "/v1/chat/completions":
                    return self._json(404, {"error": {"code": 404, "message": "File Not Found", "type": "not_found_error"}})
                if time.monotonic() < fake.ready_at:
                    return self._json(503, {"error": {"code": 503, "message": "Loading model", "type": "unavailable_error"}})
                mode, delay = fake._take()
                if delay or fake.base_delay_s:
                    time.sleep(delay + fake.base_delay_s)
                if mode == "http_500":
                    return self._json(500, {"error": {"code": 500, "message": "internal", "type": "server_error"}})
                if mode == "http_503":
                    return self._json(503, {"error": {"code": 503, "message": "Loading model", "type": "unavailable_error"}})
                answer = answer_for(body)
                finish, refusal = "stop", None
                if mode == "invalid_json":
                    content = "category: " + answer.get("category", "other")
                elif mode == "bad_enum":
                    content = json.dumps({**answer, "category": "refund"})
                elif mode == "wrong_keys":
                    content = json.dumps({**answer, "extra": "x"})
                elif mode == "cut_off":
                    content, finish = json.dumps(answer)[:20], "length"
                elif mode == "content_filter":
                    content, finish = "", "content_filter"
                elif mode == "refusal":
                    content, refusal = "", "I cannot help with that."
                else:
                    content = json.dumps(answer, ensure_ascii=False)
                prompt_tokens = max(1, sum(len(m.get("content") or "") for m in body.get("messages") or []) // 4)
                completion_tokens = max(1, len(content) // 4)
                with fake._lock:
                    fake.counters["prompt_tokens_total"] += prompt_tokens
                    fake.counters["prompt_seconds_total"] += 0.01
                    fake.counters["tokens_predicted_total"] += completion_tokens
                    fake.counters["tokens_predicted_seconds_total"] += 0.02
                return self._json(200, {
                    "id": "chatcmpl-fake", "object": "chat.completion", "created": 0,
                    "model": body.get("model") or fake.alias,  # llama.cpp echoes the model the request named
                    "choices": [{"index": 0, "finish_reason": finish,
                                 "message": {"role": "assistant", "content": content, "refusal": refusal}}],
                    "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                              "total_tokens": prompt_tokens + completion_tokens}})

            def _json(self, status, payload):
                self._text(status, json.dumps(payload, ensure_ascii=False), "application/json; charset=utf-8")

            def _text(self, status, text, content_type="text/plain; version=0.0.4"):
                data = text.encode("utf-8")
                try:
                    self.send_response(status)
                    self.send_header("content-type", content_type)
                    self.send_header("content-length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the client gave up first (a timeout test)

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer((host, port), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)

    def _record(self, path, headers, body):
        with self._lock:
            self.requests.append({"path": path, "headers": {k.lower(): v for k, v in headers.items()}, "body": body})

    def _take(self):
        with self._lock:
            mode, delay = self.mode, self.delay_s
            if self.count > 0:
                self.count -= 1
                if self.count == 0:
                    self.mode, self.delay_s = "ok", 0.0
            return mode, delay

    def set_mode(self, mode, count=-1, delay_s=0.0):
        if mode not in MODES:
            raise ValueError(mode)
        with self._lock:
            self.mode, self.count, self.delay_s = mode, count, delay_s

    def chat_requests(self):
        with self._lock:
            return [r for r in self.requests if r["path"] == "/v1/chat/completions"]

    def __enter__(self):
        self._thread.start()
        return self

    def start(self):
        self._thread.start()
        return self

    def __exit__(self, *_):
        self.stop()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="A stand-in for llama.cpp's llama-server (tests only)")
    parser.add_argument("-m", "--model", default="/models/fake.gguf")
    parser.add_argument("--alias", default="fake-model:0123456789ab")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--parallel", "-np", type=int, default=2)
    parser.add_argument("--fake-loading-s", type=float, default=0.0)
    parser.add_argument("--fake-delay-s", type=float, default=0.0, help="every answer takes this long")
    args, _unknown = parser.parse_known_args(argv)  # the real server's other flags are accepted and ignored
    server = FakeLlamaServer(alias=args.alias, model_path=args.model, host=args.host, port=args.port,
                             loading_s=args.fake_loading_s, slots=args.parallel, base_delay_s=args.fake_delay_s)
    print(f"fake llama-server listening on {args.host}:{server.port}", flush=True)
    try:
        server.server.serve_forever(poll_interval=0.05)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
