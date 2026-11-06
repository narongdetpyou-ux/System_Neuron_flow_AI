"""Application-layer access to AI models (LLMs). Core (``neuron_flow``) never imports this.

Agents call :func:`structured_answer` with text from :func:`mask` (personal data masked first); providers
are ``mock`` (offline keyword simulation for tests), ``anthropic`` (Claude over HTTPS) and ``github``
(GitHub Models over HTTPS, free within rate limits; ADR-020).
"""

from .config import LLMConfig
from .errors import (InvalidModelOutput, LLMConfigError, LLMRequestError, LLMTransientError,
                     ModelDeclined)
from .gateway import structured_answer
from .prompts import PromptTemplate, load_prompt
from .redaction import REDACTION_VERSION, MaskedText, mask

__all__ = ["LLMConfig", "PromptTemplate", "load_prompt", "structured_answer", "mask", "MaskedText",
           "REDACTION_VERSION", "InvalidModelOutput", "LLMConfigError", "LLMRequestError", "LLMTransientError",
           "ModelDeclined"]
