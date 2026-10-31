"""Error classes that tell the Core runtime what to do next.

* ``TransientAgentError`` subclasses: Core may retry the step (bounded by
  ``max_attempts``). The classify agent turns the *last* failed attempt into an
  ``unavailable`` result instead, so the case still reaches a human reviewer.
* ``PermanentAgentError`` subclasses: Core fails the step immediately. These
  are setup problems (bad key, unknown model) that would affect every case, so
  they must be loud (and reach Sentry) rather than silently degrade.

Messages never contain API keys, request bodies or case text.
"""

from neuron_flow import PermanentAgentError, TransientAgentError


class LLMTransientError(TransientAgentError):
    """Provider temporarily unavailable: rate limit, overload, server error, timeout, network."""


class InvalidModelOutput(TransientAgentError):
    """The model answered, but not in the agreed shape (bad JSON, unknown value, cut off)."""


class ModelDeclined(Exception):
    """The model declined to answer (stop_reason ``refusal``); retrying the same text rarely helps."""


class LLMConfigError(PermanentAgentError):
    """Missing or rejected credentials, unknown provider or model, unsafe configuration."""


class LLMRequestError(PermanentAgentError):
    """The provider rejected the request itself (for example HTTP 400 or 413)."""
