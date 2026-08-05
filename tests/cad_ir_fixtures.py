"""Where a CAD-IR fixture is, derived from the version rather than written down.

A fixture's filename carries the contract version — `plate.v1_10.json` — so every
version bump renames all of them, and until now every test that opened one carried the
version in its own source. Nineteen files, edited by hand or by text substitution on
each bump.

That cost something real. Three of the container tests in `packages/build123d-launcher`
still named a version the previous bump had renamed away, and nobody found out, because
those tests skip themselves unless `CAD_ENGINE_IMAGE` names an image and a skip in the
summary line looks exactly like a pass. **What is not executed is not checked**, and a
filename is only the mildest thing that can hide there.

So the version appears in exactly one place — `cad_ir.canonical.CAD_IR_VERSION`, which
is the contract's own declaration — and a test asks for `plate`. A bump becomes a rename
of files and nothing else.

`test_fixture_versions.py` is what keeps it true: it refuses a version literal in any
source file, so the habit cannot come back one call site at a time.
"""

from __future__ import annotations

import json
from pathlib import Path

from cad_ir.canonical import CAD_IR_VERSION

#: The directory the fixtures live in. Beside this module, because this module is part
#: of the same thing.
DIRECTORY = Path(__file__).resolve().parent / "fixtures" / "cad-ir"


def suffix() -> str:
    """The version as a filename fragment: `1.10` is `v1_10`."""
    return "v" + CAD_IR_VERSION.replace(".", "_")


def fixture_path(name: str) -> Path:
    """The file `name` refers to at the version this build speaks.

    `name` is the part before the version — `plate`, `lever-plate`, `boolean-bracket`.
    """
    return DIRECTORY / f"{name}.{suffix()}.json"


def fixture(name: str) -> dict:
    """The parsed document, which is what almost every caller wants."""
    return json.loads(fixture_path(name).read_text(encoding="utf-8"))


def names() -> list[str]:
    """Every fixture of the current version, by the name a test asks for.

    The two files with no version at all — `plate.json` and `plate-with-hole.json` — are
    0.1.0 documents kept for the normalizer's own tests, and they are deliberately not
    here: a caller wanting one of those wants the legacy shape and should say so.
    """
    return sorted(path.name.split(".")[0] for path in DIRECTORY.glob(f"*.{suffix()}.json"))
