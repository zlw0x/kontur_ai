"""Typed failures from the CAD engine.

Every refusal carries a code and a stage, because a build that stops has to say
*what* it refused and *where* — an operator reading "build failed" learns
nothing, and a repair loop cannot react to prose.

The codes are the ones the KOMPAS adapter already uses wherever the failure is
the same failure. A caller that switched engines should not have to learn a new
vocabulary for "this document says two contradictory things".
"""

from __future__ import annotations


class CadEngineError(Exception):
    """A refusal the caller can act on."""

    def __init__(self, code: str, stage: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        #: Safe to show a user: it describes the document, never the machine.
        self.safe_message = message

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.code} ({self.stage}): {self.safe_message}"


def unsupported(what: str, stage: str = "prepare") -> CadEngineError:
    """Something the document asks for that this engine does not do yet.

    Deliberately distinct from an invalid document. A caller that cannot tell
    "you wrote this wrong" from "we cannot do this yet" will report the wrong
    thing to a user and file the wrong bug.
    """
    return CadEngineError("UNSUPPORTED_FEATURE", stage, what)
