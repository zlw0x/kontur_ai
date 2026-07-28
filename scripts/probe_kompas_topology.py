"""Record the KOMPAS topology API this machine actually exposes.

AGENTS.md forbids inventing COM members, so the selector resolver cannot be
written from memory of the SDK documentation. This reads the installed type
library and prints every member the resolver will call, with its DispId.

    python scripts/probe_kompas_topology.py [--tlb <path to kAPI5.tlb>]

Reads a file; starts no KOMPAS process and opens no model.

Findings are written up in docs/TASK-POSTMVP-005-selectors.md. Two are worth
knowing before reading the output: KOMPAS API7's IPart7 exposes no body or
face collection at all — it offers FindBody, GetBodyById and DefaultObject —
so topology enumeration goes through API5, which the adapter already uses for
STEP and STL export.
"""

from __future__ import annotations

import argparse
import re
import sys

DEFAULT_TLB = r"C:\Program Files\ASCON\KOMPAS-3D v22\Bin\kAPI5.tlb"

#: The interfaces a semantic selector has to walk, and the members worth
#: printing for each. `None` prints everything the interface declares.
INTERFACES: tuple[tuple[str, str | None], ...] = (
    ("ksPart", r"collection|body|entity"),
    ("ksFaceCollection", None),
    ("ksFaceDefinition", None),
    ("ksEdgeCollection", None),
    ("ksEdgeDefinition", None),
    ("ksSurface", r"^(Is|GetNormal|GetGabarit|GetArea|GetPoint|GetSurfaceParam)"),
    ("ksCurve3D", r"^(Is|GetPoint|GetTangent|GetGabarit|GetLength|GetPlacement)"),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tlb", default=DEFAULT_TLB)
    arguments = parser.parse_args()

    try:
        import comtypes.client
    except ImportError:
        print("comtypes is required: pip install comtypes", file=sys.stderr)
        return 2

    try:
        module = comtypes.client.GetModule(arguments.tlb)
    except OSError as error:
        print(f"could not read {arguments.tlb}: {error}", file=sys.stderr)
        return 2

    print(f"# KOMPAS topology API, read from {arguments.tlb}\n")
    for name, only in INTERFACES:
        interface = getattr(module, name, None)
        if interface is None:
            print(f"## {name}\n\nNOT EXPORTED by this type library.\n")
            continue
        print(f"## {name}\n")
        for member in getattr(interface, "_disp_methods_", []):
            if only and not re.search(only, member.name, re.IGNORECASE):
                continue
            dispid = member.idlflags[0] if member.idlflags else "?"
            args = ", ".join(
                f"{'out ' if 'out' in (spec[0] or []) else ''}{spec[2]}"
                for spec in (member.argspec or [])
            )
            print(f"    [{dispid}] {member.name}({args})")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
