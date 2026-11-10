"""Application-layer access to AI models (LLMs). Core (``neuron_flow``) never imports this.

Agents call :func:`structured_answer` with text from :func:`mask` (personal data masked first); providers
are ``mock`` (offline keyword simulation for tests), ``anthropic`` (Claude over HTTPS), ``typhoon``
(Typhoon over HTTPS, OpenAI chat-completions format, free within rate limits; ADR-021) and ``local`` (an
open-weight model on a server we run ourselves, by default llama.cpp on this machine; ADR-026).
"""

from .config import LLMConfig
from .errors import (InvalidModelOutput, LLMConfigError, LLMRequestError, LLMTransientError,
                     ModelDeclined, UnmaskedText)
from .gateway import structured_answer
from .prompts import PromptTemplate, load_prompt
from .redaction import REDACTION_VERSION, MaskedText, mask

__all__ = ["LLMConfig", "PromptTemplate", "load_prompt", "structured_answer", "mask", "MaskedText",
           "REDACTION_VERSION", "InvalidModelOutput", "LLMConfigError", "LLMRequestError", "LLMTransientError",
           "ModelDeclined", "UnmaskedText"]
