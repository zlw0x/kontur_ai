"""Resolve a document's parameters to numbers, once, before anything is built.

CAD-IR allows exactly one indirection: a scalar may be a `{"parameter": "p_x"}`
reference instead of a number. Resolving it is the engine's job, and doing it in
one pass up front rather than lazily at each use is deliberate — a parameter that
does not exist should fail before a single face is made, not halfway through a
part.

Nothing is evaluated as code. A parameter's value is a number in the document;
`cad_ir.expression` exists for documents that carry expressions and is a real
parser with a fixed grammar, not `eval`.

`resolve` also handles a `ScaledParameterRef` — a parameter times a constant, so a
Ø80 callout can drive a radius of 40. That form is **not in `Scalar` yet**, so no
document the validator accepts can reach this branch; it is resolved here, and
tested, because adding it to the contract is a CAD-IR version and the arithmetic is
worth settling first. `docs/TASK-POSTMVP-scalar-arithmetic.md` has the argument.
"""

from __future__ import annotations

from typing import Mapping

from cad_ir.base import ParameterRef, ScaledParameterRef
from cad_ir.canonical import CadIrDocument, ParameterStatus

from .errors import CadEngineError


class Parameters:
    """The document's parameters, by id."""

    def __init__(self, values: Mapping[str, float]) -> None:
        self._values = dict(values)

    @classmethod
    def of(cls, document: CadIrDocument) -> "Parameters":
        values: dict[str, float] = {}
        for parameter in document.parameters:
            value = parameter.value
            if isinstance(value, ParameterRef):
                # One level of indirection is the contract. A parameter defined
                # as another parameter would need an order of resolution that
                # CAD-IR does not state, so it is refused rather than guessed.
                raise CadEngineError(
                    "CAD_IR_INVALID",
                    "prepare",
                    f"Parameter {parameter.id} is defined as another parameter; "
                    "CAD-IR allows one level of indirection, from a value to a "
                    "parameter, not from a parameter to a parameter.",
                )
            if value is None:
                raise CadEngineError(
                    "PARAMETER_UNRESOLVED",
                    "prepare",
                    f"Parameter {parameter.id} has no value, so nothing that uses "
                    "it can be built.",
                )
            values[str(parameter.id)] = float(value)
        return cls(values)

    def resolve(self, scalar, what: str) -> float:
        """A scalar as a number, whether it was one, named one, or scaled one."""
        if isinstance(scalar, (ParameterRef, ScaledParameterRef)):
            name = str(scalar.parameter)
            if name not in self._values:
                raise CadEngineError(
                    "PARAMETER_UNRESOLVED",
                    "prepare",
                    f"{what} names parameter {name}, which the document does not "
                    "define.",
                )
            value = self._values[name]
            if isinstance(scalar, ScaledParameterRef):
                # The one multiplication in the engine. It is here rather than in the
                # contract because a resolved number is the engine's business, and it
                # is a multiplication rather than an expression for the reason
                # `ScaledParameterRef` gives: one spelling per part.
                value *= scalar.times
                if not -1e6 < value < 1e6:
                    raise CadEngineError(
                        "PARAMETER_UNRESOLVED",
                        "prepare",
                        f"{what} scales {name} to {value}, which is outside the range "
                        "any part is built in.",
                    )
            return value
        if isinstance(scalar, bool) or not isinstance(scalar, (int, float)):
            raise CadEngineError(
                "CAD_IR_INVALID", "prepare", f"{what} is not a number."
            )
        return float(scalar)

    def unconfirmed(self, document: CadIrDocument) -> list[str]:
        """Parameters the document does not claim a user confirmed.

        Reported rather than refused. Whether an unconfirmed dimension may be
        built is a decision for the order, not for the engine — but an engine
        that could not say which numbers were guesses would make that decision
        impossible to take anywhere.
        """
        return [
            str(parameter.id)
            for parameter in document.parameters
            if parameter.status is not ParameterStatus.CONFIRMED
        ]


__all__ = ["Parameters"]
