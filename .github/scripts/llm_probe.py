"""One connection check against an OpenAI-format provider (Typhoon, or a local model server, ADR-026), written to
the run summary, before a scorecard run.

It sends one fixed synthetic sentence (never a case from the set) with the same request the provider sends,
then reports what came back (one request; the verdict is about the reply shown): HTTP status, content type and encoding, rate-limit headers, the body's size
and its first characters, and how the provider itself classified the reply. The token is never printed.
A broken connection only writes the findings: the scorecard step runs either way.

Run from the repository root: ``PYTHONPATH=. python .github/scripts/llm_probe.py "$GITHUB_STEP_SUMMARY"``
"""

import io
import json
import os
import sys
import urllib.error
import urllib.request

from app.llm import InvalidModelOutput, LLMConfig, ModelDeclined, load_prompt
from app.llm.gateway import _CUT_OFF, parse_answer
from app.llm.config import KEY_ENVS, OPTIONAL_KEY_PROVIDERS
from app.llm.providers import openai_compat

SENTENCE = "I cannot upload a file to my ticket."  # fixed and synthetic: safe to send and to show
SHOWN_HEADERS = ("content-type", "content-encoding", "content-length", "x-ratelimit-limit-requests",
                 "x-ratelimit-remaining-requests", "retry-after")
PREVIEW_CHARS = 600


def raw_call(config, token):
    """The provider's own request, sent without its parsing, so the reply can be shown as it arrived."""
    prompt = load_prompt("triage_classify_v1")
    body = json.dumps(openai_compat.build_request_body(config, prompt, SENTENCE), ensure_ascii=False).encode()
    request = urllib.request.Request(openai_compat.endpoint(config), data=body, method="POST",
                                     headers=openai_compat.request_headers(config, token))
    try:
        with openai_compat.OPENER.open(request, timeout=config.request_timeout_s) as response:
            return response.status, response.headers, response.read(200_000)
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, exc.headers, exc.read(200_000)


def verdict(config, prompt, status, headers, raw):
    """How the provider and gateway classify this very reply (no second request): the answer, or the error."""
    if status >= 300:
        error = urllib.error.HTTPError("probe", status, "probe", headers, io.BytesIO(raw))
        reply = openai_compat.for_status(error, config)  # raises, unless a content filter blocked the sentence
    else:
        reply = openai_compat.parse_completion(raw, config)
    if reply["stop_reason"] == "refusal":
        raise ModelDeclined("The model declined to answer")
    if reply["stop_reason"] in _CUT_OFF:
        raise InvalidModelOutput(f"The answer was cut off ({reply['stop_reason']})")
    return parse_answer(reply["text"], prompt.output_schema), reply["served_model"]


def describe(status, headers, raw):
    text = raw.decode("utf-8", errors="replace")
    lines = [f"- HTTP status: `{status}`, body: {len(raw)} bytes"
             + (" (starts with a UTF-8 BOM)" if raw.startswith(b"\xef\xbb\xbf") else "")]
    for name in SHOWN_HEADERS:
        if headers.get(name):
            lines.append(f"- `{name}`: `{headers.get(name)[:120]}`")
    preview = text[:PREVIEW_CHARS].replace("```", "'''")
    lines += ["- first characters of the body:", "", "```text", preview or "(empty)", "```"]
    return lines


def main(summary_path):
    lines = ["### ตรวจการเชื่อมต่อ AI (connection check)", "",
             f"ส่งประโยคทดสอบ 1 ประโยค: \"{SENTENCE}\" (One fixed synthetic sentence, not a case.)", ""]
    token = ""
    try:
        config = LLMConfig.from_env()
        if config.provider not in KEY_ENVS or config.provider == "anthropic":
            raise ValueError(f"the check covers OpenAI-format providers, not {config.provider}")
        token = os.environ.get(KEY_ENVS[config.provider], "").strip()
        key_state = "yes" if token else "not needed" if config.provider in OPTIONAL_KEY_PROVIDERS else "no"
        lines.append(f"- provider: `{config.provider}`, model: `{config.model}`, key present: {key_state}")
        status, headers, raw = raw_call(config, token)
        lines += describe(status, headers, raw)
        try:
            answer, served = verdict(config, load_prompt("triage_classify_v1"), status, headers, raw)
            lines.append(f"- provider verdict: **answered** `{json.dumps(answer, ensure_ascii=False)}`, "
                         f"served model `{served}`")
        except Exception as exc:  # the class and our own message (status and codes only), never the reply
            lines.append(f"- provider verdict: **{type(exc).__name__}**: {str(exc)[:200]}")
    except Exception as exc:
        lines.append(f"- the check itself could not run: {type(exc).__name__}: {str(exc)[:200]}")
    text = "\n".join(lines) + "\n\n"
    if token:
        text = text.replace(token, "***")
    print(text)
    with open(summary_path, "a", encoding="utf-8") as stream:
        stream.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else os.devnull))
