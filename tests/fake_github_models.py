"""Replies in GitHub Models' chat-completion shape, served by the same local fake server as the Claude tests."""
import json

from tests.fake_anthropic import FakeAnthropic as FakeServer  # a generic recording HTTP fake

__all__ = ["FakeServer", "completion", "gh_error"]


def completion(answer, *, finish_reason="stop", model="gpt-4.1-mini-2025-04-14", refusal=None):
    """A chat completion whose message content holds the JSON answer (structured output)."""
    content = answer if isinstance(answer, str) or answer is None else json.dumps(answer, ensure_ascii=False)
    return {"id": "chatcmpl-test", "object": "chat.completion", "created": 1_762_400_000, "model": model,
            "choices": [{"index": 0, "finish_reason": finish_reason,
                         "message": {"role": "assistant", "content": content, "refusal": refusal}}],
            "usage": {"prompt_tokens": 140, "completion_tokens": 25, "total_tokens": 165}}


def gh_error(status, code, *, inner=None):
    error = {"code": code, "message": "echo: SECRET-CASE-TEXT", "status": status}
    if inner:
        error["innererror"] = {"code": inner, "content_filter_result": {"jailbreak": {"filtered": True}}}
    return status, {"error": error}
