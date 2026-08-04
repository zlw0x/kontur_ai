"""Shared helpers for the engine's tests.

`pruned` exists because of CAD-IR 1.11. Many tests here take a fixture and cut it
down — delete the countersink, keep one feature of three, disable everything — to
isolate one behaviour of the engine. That leaves the fixture's dimensions declared
and nothing driving them, which `PARAMETER_DRIVES_NOTHING` correctly refuses: a
cut-down document is a different document and its parameter list has to match.

The alternative would be to stop cutting fixtures down, and the tests would be worse
for it. So the dimensions go with the features that used them.
"""

from __future__ import annotations

from typing import Any

from cad_ir.base import ParameterRef
from cad_ir.canonical import CadIrDocument

# The contract's own reference walk, so this helper and the rule it serves cannot
# disagree about what "referenced" means. A second walk written here would be a
# second definition, and the first thing it would get wrong is construction
# geometry — which the rule deliberately does not count.
from cad_ir.canonical_validator import _references  # noqa: PLC2701


def pruned(value: dict[str, Any]) -> dict[str, Any]:
    """The same document with the dimensions no surviving feature references removed.

    Only `parameters` is touched, and only entries nothing points at, so this cannot
    change what gets built. A parameter a *disabled* feature names is kept, for the
    reason the rule keeps it: a feature turned off by a flag still names the
    dimensions it would build with.
    """
    document = CadIrDocument(**value)
    referenced = {
        reference.parameter
        for index, feature in enumerate(document.features)
        for path, reference in _references(
            feature.inputs, f"$.features[{index}].inputs", ParameterRef
        )
        if ".construction[" not in path
    }
    kept = [
        parameter
        for parameter in value.get("parameters", [])
        if parameter["id"] in referenced or parameter.get("type") not in ("length", "angle")
    ]
    return {**value, "parameters": kept}
