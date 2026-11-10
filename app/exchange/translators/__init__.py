"""Translators: pure, versioned code on each side of the common language (ADR-030).

* An **out**-translator reads what the queue database holds for a finished job of its skill (input, result, and
  for ``APPROVED`` the person's decision) and returns facts.
* An **in**-translator reads the facts a route carries and returns its skill's own input, which must then pass
  that skill's own ``check_input``.

They live here, outside ``app/domains/``, so no skill is edited to join a route and no skill knows the exchange.
Rules for every translator: no AI, no network, no files, no clock, no randomness. The same input always gives the
same output, so a translation repeated after a crash gives the same envelope. A changed output is a new version:
``tests/test_exchange.py`` pins each one's output for fixed inputs.
"""

from . import case_triage
from .base import SourceIncomplete, SourceView, Translator

_ALL = (
    Translator("out.case_triage.v2", 1, "out", "case_triage.v2", case_triage.OUT_FACTS, case_triage.triage_v2_out,
               states=("APPROVED",)),
    Translator("in.case_triage.v2.apply", 1, "in", "case_triage.v2.apply", case_triage.APPLY_READS,
               case_triage.apply_in),
)
TRANSLATORS = {translator.tag: translator for translator in _ALL}

__all__ = ["TRANSLATORS", "SourceIncomplete", "SourceView", "Translator"]
