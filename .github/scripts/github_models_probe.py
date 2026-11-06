"""One connection check against GitHub Models, written to the run summary, before a scorecard run.

It sends one fixed synthetic sentence (never a case from the set) with the same request the provider sends,
then reports what came back: HTTP status, content type and encoding, rate-limit headers, the body's size
and its first characters, and how the provider itself classified the reply. The token is never printed.
A broken connection only writes the findings: the scorecard step runs either way.

Run from the repository root: ``PYTHONPATH=. python .github/scripts/github_models_probe.py "$GITHUB_STEP_SUMMARY"``
"""

import json
import os
import sys
import urllib.error
import urllib.request

from app.llm import LLMConfig, load_prompt, mask, structured_answer
from app.llm.config import DEFAULT_GITHUB_MODELS_BASE_URL, GITHUB_TOKEN_ENV
from app.llm.providers import github_models

SENTENCE = "I cannot upload a file to my ticket."  # fixed and synthetic: safe to send and to show
SHOWN_HEADERS = ("content-type", "content-encoding", "content-length", "x-ratelimit-limit-requests",
                 "x-ratelimit-remaining-requests", "retry-after", "x-github-request-id")
PREVIEW_CHARS = 600


def raw_call(config, token):
    """The provider's own request, sent without its parsing, so the reply can be shown as it arrived."""
    prompt = load_prompt("triage_classify_v1")
    url = (config.base_url or DEFAULT_GITHUB_MODELS_BASE_URL).rstrip("/") + "/chat/completions"
    body = json.dumps(github_models.build_request_body(config, prompt, SENTENCE), ensure_ascii=False).encode()
    request = urllib.request.Request(url, data=body, method="POST", headers={
        "authorization": f"Bearer {token}", "x-github-api-version": github_models.API_VERSION,
        "content-type": "application/json", "accept": "application/vnd.github+json"})
    try:
        with github_models.OPENER.open(request, timeout=config.request_timeout_s) as response:
            return response.status, response.headers, response.read(200_000)
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, exc.headers, exc.read(200_000)


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
    lines = ["### ตรวจการเชื่อมต่อ GitHub Models (connection check)", "",
             f"ส่งประโยคทดสอบ 1 ประโยค: \"{SENTENCE}\" (One fixed synthetic sentence, not a case.)", ""]
    token = os.environ.get(GITHUB_TOKEN_ENV, "").strip()
    try:
        config = LLMConfig.from_env()
        lines.append(f"- model: `{config.model}`, token present: {'yes' if token else 'no'}")
        lines += describe(*raw_call(config, token))
        try:
            result = structured_answer(config, load_prompt("triage_classify_v1"), mask(SENTENCE))
            lines.append(f"- provider verdict: **answered** `{json.dumps(result['answer'], ensure_ascii=False)}`, "
                         f"served model `{result['served_model']}`")
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
