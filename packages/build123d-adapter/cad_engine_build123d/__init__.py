"""The trusted CAD-IR to build123d mapping.

The engine that replaces KOMPAS (ADR-023). CAD-IR stays the parametric source of
truth; this package is one implementation of it, chosen so the build can run in a
Linux container with no licence and no desktop application.

The rule that matters most here: **AI-generated Python is never executed.** The
document names shapes from a fixed vocabulary and every name has a hand-written
branch. There is no `eval`, no `exec`, no import of a generated module and no
generated script. An engine written in Python does not weaken that rule; it makes
stating it again worthwhile.
"""

from .adapter import BuildOutcome, BuiltArtifact, build, build_part
from .errors import CadEngineError, unsupported
from .identity import ARTIFACTS, ArtifactKind, EngineDescription, describe

__all__ = [
    "ARTIFACTS",
    "ArtifactKind",
    "BuildOutcome",
    "BuiltArtifact",
    "CadEngineError",
    "EngineDescription",
    "build",
    "build_part",
    "describe",
    "unsupported",
]
