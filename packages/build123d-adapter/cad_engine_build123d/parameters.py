"""Resolve a document's parameters to numbers, once, before anything is built.

CAD-IR allows exactly one indirection: a scalar may be a `{"parameter": "p_x"}`
reference instead of a number. Resolving it is the engine's job, and doing it in
one pass up front rather than lazily at each use is deliberate — a parameter that
does not exist should fail before a single face is made, not halfway through a
part.

Nothing is evaluated as code. A parameter's value is a number in the document;
`cad_ir.expression` exists for documents that carry expressions and is a real
parser with a fixed grammar, not `eval`.
"""

from __future__ import annotations

from typing import Mapping

from cad_ir.base import ParameterRef, ScalarNegation, ScalarQuotient
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
        """A scalar as a number: one, a named one, or one derived from a named one.

        The only place in this engine where a `Scalar` becomes a float, and it
        serves all twenty-four call sites — the contours, the distances, the blend
        sizes, the pattern steps. That is why CAD-IR 1.11 could give scalars
        arithmetic without touching any of them: the two new forms are handled
        here, recursively, and everything above carries on asking for a number.
        """
        if isinstance(scalar, ScalarQuotient):
            # The divisor is a constant and the contract already refused zero and
            # anything non-finite, so this cannot produce an infinity the geometry
            # would then be built from.
            return self.resolve(scalar.divide, what) / float(scalar.by)
        if isinstance(scalar, ScalarNegation):
            return -self.resolve(scalar.negate, what)
        if isinstance(scalar, ParameterRef):
            name = str(scalar.parameter)
            if name not in self._values:
                raise CadEngineError(
                    "PARAMETER_UNRESOLVED",
                    "prepare",
                    f"{what} names parameter {name}, which the document does not "
                    "define.",
                )
            return self._values[name]
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
