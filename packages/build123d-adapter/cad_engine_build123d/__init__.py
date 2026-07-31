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

from .capabilities import CapabilityGate, requirements
from .errors import CadEngineError, unsupported
from .identity import ARTIFACTS, ArtifactKind, EngineDescription, describe

#: Reached lazily, because importing them imports build123d.
#:
#: The constraint checks and the selector matching work on numbers and know
#: nothing about a kernel — that is what makes them testable on a machine with no
#: CAD library installed, and it is the same property the neutral .NET package
#: keeps by targeting plain net8.0. Importing the adapter eagerly here would
#: quietly take it away: `from cad_engine_build123d.constraints import validate`
#: runs this file first, and this file would then need OpenCascade.
_LAZY = {
    "BuildOutcome": "adapter",
    "BuiltArtifact": "adapter",
    "build": "adapter",
    "build_part": "adapter",
    "VerificationReport": "verify",
}


def __getattr__(name: str):
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(f".{module_name}", __name__), name)


__all__ = [
    "ARTIFACTS",
    "ArtifactKind",
    "BuildOutcome",
    "BuiltArtifact",
    "CadEngineError",
    "CapabilityGate",
    "EngineDescription",
    "VerificationReport",
    "build",
    "build_part",
    "describe",
    "requirements",
    "unsupported",
]
