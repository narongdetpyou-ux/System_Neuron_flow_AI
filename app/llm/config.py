"""Which AI provider and model a job uses, frozen into the job when it is submitted.

The configuration travels inside the step ``params`` (so it is recorded with the
job and covered by the job fingerprint) and inside the agent ``version`` (so Core
refuses to run an old job with a different model or prompt). API keys are never
part of it: the agent reads the provider's key from the environment at call time
(``ANTHROPIC_API_KEY`` for Claude, ``TYPHOON_API_KEY`` for Typhoon).

Providers:
* ``mock``: the offline keyword simulation (tests and CI; not an AI model);
* ``anthropic``: Claude, which needs a paid Anthropic API key;
* ``typhoon``: Typhoon by SCB 10X, a Thai-first model family whose hosted API is free (a research
  showcase, rate-limited, no card) and speaks the OpenAI chat-completions format (ADR-021).
  GitHub Models (ADR-020) was removed: GitHub retired it on 2026-07-30.
"""

from dataclasses import dataclass
import math
import os
import re
from typing import Optional
from urllib.parse import urlsplit

from .errors import LLMConfigError
from .redaction import REDACTION_VERSION

PROVIDERS = ("mock", "anthropic", "typhoon")
DEFAULT_MODELS = {"mock": "mock-keyword-1", "anthropic": "claude-haiku-5-5",
                  "typhoon": "typhoon-v2.5-30b-a3b-instruct"}
DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com"
DEFAULT_TYPHOON_BASE_URL = "https://api.opentyphoon.ai/v1"
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
API_KEY_ENV = "ANTHROPIC_API_KEY"
TYPHOON_KEY_ENV = "TYPHOON_API_KEY"
# Which environment variable holds each real provider's key, and which one may point it at another endpoint.
KEY_ENVS = {"anthropic": API_KEY_ENV, "typhoon": TYPHOON_KEY_ENV}
BASE_URL_ENVS = {"anthropic": "NEURON_FLOW_ANTHROPIC_BASE_URL", "typhoon": "NEURON_FLOW_TYPHOON_BASE_URL"}
DEFAULT_BASE_URLS = {"anthropic": DEFAULT_ANTHROPIC_BASE_URL, "typhoon": DEFAULT_TYPHOON_BASE_URL}
# What a provider's client tells the model about the answer format besides the prompt file (ADR-022). Typhoon's
# API ignores ``response_format``, so its client also states the format in words, built from the answer schema
# (``providers/openai_compat.py``). That text is part of what the model sees, so its version is part of the
# agent version: change it whenever the text changes.
ANSWER_FORMATS = {"typhoon": "json-instruction-v1"}
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_PARAM_KEYS = {"provider", "model", "max_tokens", "request_timeout_s", "effort", "base_url"}


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "mock"
    model: str = DEFAULT_MODELS["mock"]
    max_tokens: int = 2048
    request_timeout_s: float = 30.0
    effort: Optional[str] = None
    base_url: Optional[str] = None

    def __post_init__(self):
        if self.provider not in PROVIDERS:
            raise LLMConfigError(f"Unknown LLM provider {self.provider!r}; use one of {', '.join(PROVIDERS)}")
        if not isinstance(self.model, str) or not _MODEL.fullmatch(self.model):
            raise LLMConfigError("Model id must be 1-100 letters, digits, '.', '_', ':' or '-'")
        if self.provider == "mock" and not self.model.startswith("mock-"):
            raise LLMConfigError("The mock provider only accepts model ids starting with 'mock-'")
        if self.provider != "mock" and self.model.startswith("mock-"):
            raise LLMConfigError("A 'mock-' model id needs the mock provider")
        if type(self.max_tokens) is not int or not 16 <= self.max_tokens <= 16384:
            raise LLMConfigError("max_tokens must be an integer between 16 and 16384")
        timeout = self.request_timeout_s
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or not 0.1 <= timeout <= 300):
            raise LLMConfigError("request_timeout_s must be between 0.1 and 300 seconds")
        if self.effort is not None and self.effort not in EFFORT_LEVELS:
            raise LLMConfigError(f"effort must be one of {', '.join(EFFORT_LEVELS)}")
        if self.effort is not None and self.provider != "anthropic":
            # Only the Claude client sends an effort setting; refuse it here instead of ignoring it silently.
            raise LLMConfigError(f"effort is not used by the {self.provider} provider; "
                                 "leave NEURON_FLOW_LLM_EFFORT unset")
        if self.base_url is not None:
            if self.provider == "mock":
                raise LLMConfigError("base_url is only used by real providers")
            _check_base_url(self.base_url)

    @classmethod
    def from_env(cls, environ=None):
        env = os.environ if environ is None else environ
        provider = env.get("NEURON_FLOW_LLM_PROVIDER", "mock").strip() or "mock"
        if provider not in PROVIDERS:
            raise LLMConfigError(f"Unknown LLM provider {provider!r}; use one of {', '.join(PROVIDERS)}")
        values = {"provider": provider,
                  "model": env.get("NEURON_FLOW_LLM_MODEL", "").strip() or DEFAULT_MODELS[provider]}
        for key, name, convert in (("max_tokens", "NEURON_FLOW_LLM_MAX_TOKENS", int),
                                   ("request_timeout_s", "NEURON_FLOW_LLM_TIMEOUT_S", float)):
            raw = env.get(name, "").strip()
            if raw:
                try:
                    values[key] = convert(raw)
                except ValueError:
                    raise LLMConfigError(f"{name} must be a number") from None
        effort = env.get("NEURON_FLOW_LLM_EFFORT", "").strip()
        if effort:
            values["effort"] = effort
        base_url = env.get(BASE_URL_ENVS[provider], "").strip() if provider in BASE_URL_ENVS else ""
        if base_url:
            values["base_url"] = base_url
        return cls(**values)

    @property
    def key_env(self):
        """The environment variable that holds this provider's key (None for the mock)."""
        return KEY_ENVS.get(self.provider)

    def to_params(self):
        """JSON form stored in the job; contains no secrets."""
        return {"provider": self.provider, "model": self.model, "max_tokens": self.max_tokens,
                "request_timeout_s": float(self.request_timeout_s), "effort": self.effort,
                "base_url": self.base_url}

    @classmethod
    def from_params(cls, data):
        if not isinstance(data, dict) or set(data) != _PARAM_KEYS:
            raise LLMConfigError("LLM params must contain exactly: " + ", ".join(sorted(_PARAM_KEYS)))
        return cls(**data)

    def version_tag(self, prompt):
        """Agent version string: changing model, prompt, answer budget, masking rules or the answer-format text a
        client adds (ADR-022) means a new version."""
        tag = (f"llm={self.provider}/{self.model};prompt={prompt.id}@sha256:{prompt.sha256};"
               f"max_tokens={self.max_tokens};effort={self.effort or 'default'};redaction={REDACTION_VERSION}")
        if self.provider in ANSWER_FORMATS:
            tag += f";format={ANSWER_FORMATS[self.provider]}"
        return tag

    def check_ready(self, environ=None):
        """Fail before any job is submitted when a real provider has no key."""
        env = os.environ if environ is None else environ
        name = self.key_env
        if name and not env.get(name, "").strip():
            raise LLMConfigError(f"{name} is not set; the {self.provider} provider cannot run")


def _check_base_url(value):
    if not isinstance(value, str) or len(value) > 200:
        raise LLMConfigError("base_url must be a short URL")
    parts = urlsplit(value)
    if parts.username or parts.password or "@" in parts.netloc:
        raise LLMConfigError("base_url must not contain credentials")
    if parts.query or parts.fragment:
        raise LLMConfigError("base_url must not contain a query string or fragment")
    host = (parts.hostname or "").lower()
    if not host:
        raise LLMConfigError("base_url needs a host")
    if parts.scheme == "https":
        return
    if parts.scheme == "http" and host in _LOOPBACK:
        return  # local test servers only
    raise LLMConfigError("base_url must use https (plain http is allowed only for localhost tests)")
