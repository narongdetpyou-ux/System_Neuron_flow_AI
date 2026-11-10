"""The parts every translator shares: what it may read, how it says it cannot, and how it is named."""

from dataclasses import dataclass, field
from typing import Callable, Optional


class SourceIncomplete(Exception):
    """The finished job does not hold what this out-translator needs, so nothing is guessed."""


@dataclass(frozen=True)
class SourceView:
    """What an out-translator may read: the queue database's record of the job, never Core's files (ADR-001)."""
    workflow_type: str
    state: str
    input: dict
    result: Optional[dict]
    decision: Optional[dict] = None


@dataclass(frozen=True)
class Translator:
    name: str              # "out.case_triage.v2"
    version: int
    direction: str         # "out" | "in"
    workflow_type: str     # the skill it speaks for
    facts: tuple           # out: the facts it may give; in: the facts it reads
    function: Callable
    states: tuple = field(default=())  # out only: the source states it can read

    @property
    def tag(self):
        return f"{self.name}@{self.version}"
