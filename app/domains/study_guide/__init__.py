"""Study-guide domain (roadmap Phase 3): the first-response rule of the owner's design philosophy.

Built so far (roadmap 3.1): the versioned topic catalog and the verified resource library in ``catalog/``,
their loader and checks (``library.py``), and the weekly link check (``link_check.py``). The workflow
itself (``study_guide.v1``, roadmap 3.2) is not built yet.
"""

from .library import (LEVEL_LABELS_TH, LEVELS, OUT_OF_SCOPE, Library, LibraryError, Resource, Topic,
                      load_library)

__all__ = ["LEVELS", "LEVEL_LABELS_TH", "OUT_OF_SCOPE", "Library", "LibraryError", "Resource", "Topic",
           "load_library"]
