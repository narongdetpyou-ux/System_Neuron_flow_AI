"""The skill-handoff exchange (ADR-030, docs/skill_handoff.md).

Skills (workflow types and their domains) stay separate: none imports, calls or names another. Work moves from one
skill to the next only here, along a fixed route of a versioned table, through an out-translator, one common
language of versioned facts and the target's in-translator. The queue store writes the handoff in the same
transaction as the source job's new state.

* ``common.py``: the vocabulary and its fact checks; ``vocabulary_v1.json`` is the language itself.
* ``translators/``: pure, versioned code on each side of the language.
* ``routes.py``: the route table; ``routes_v1.json`` is the table itself.
* ``exchange.py``: :class:`Exchange`, which checks the table at start and prepares each handoff.
"""

from .common import FactInvalid, Vocabulary
from .exchange import ENVELOPE_VERSION, REASONS, REFUSED, STARTED, Exchange, ExchangeConfigError
from .routes import Route, RouteTable
from .translators import TRANSLATORS, SourceIncomplete, SourceView, Translator

__all__ = ["Exchange", "ExchangeConfigError", "RouteTable", "Route", "Vocabulary", "FactInvalid", "TRANSLATORS",
           "Translator", "SourceView", "SourceIncomplete", "ENVELOPE_VERSION", "REASONS", "STARTED", "REFUSED"]
