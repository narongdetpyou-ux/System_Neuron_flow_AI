"""Study-guide domain (roadmap Phase 3): the first-response rule of the owner's design philosophy.

* Roadmap 3.1: the versioned topic catalog and the verified resource library in ``catalog/``, their loader
  and checks (``library.py``), and the weekly link check (``link_check.py``).
* Roadmap 3.2: the ``study_guide.v1`` workflow (``workflow.py``, ``agents.py``, ``planning.py``): a
  plain-language request in, up to 5 verified resources in study order out, with a layered answer.
"""

from .library import (LEVEL_LABELS_TH, LEVELS, OUT_OF_SCOPE, Library, LibraryError, Resource, Topic,
                      load_library)
from .workflow import build_study_workflow, check_message, study_registry

__all__ = ["LEVELS", "LEVEL_LABELS_TH", "OUT_OF_SCOPE", "Library", "LibraryError", "Resource", "Topic",
           "load_library", "build_study_workflow", "check_message", "study_registry"]
