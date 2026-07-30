"""Record the KOMPAS sketch, plane and face API that POSTMVP-006 will call.

AGENTS.md forbids inventing COM members, so the sketch builder cannot be
written from memory of the SDK documentation. This reads the installed type
library and prints every member involved, with its DispId.

    python scripts/probe_kompas_sketch.py [--tlb <path to kAPI7.tlb>]

Reads a file; starts no KOMPAS process and opens no model. Four findings could
only come from a live run, and are recorded in
docs/TASK-POSTMVP-006-sketch-primitives.md rather than here:

* `IArc` is built from centre, radius and two angles. Setting the endpoint
  properties X1/Y1/X2/Y2 instead leaves `Update()` returning false and the
  radius at zero.
* `IPlanes3D.Add(14)` is the offset plane; 15 is by angle and 16 through three
  points. The type library exports no named constant for any of them.
* `IPart7.FindObjectsByPoint(x, y, z, firstLevel)` returns an `object[]`, of
  which one entry casts to `IFace`. This is how a face resolved by a semantic
  selector — which is measured through API5 — becomes something a sketch can
  be placed on, since API7 has no face collection to look it up in.
* A sketch whose plane is such a face extrudes normally.
"""

from __future__ import annotations

import argparse
import re
import sys

DEFAULT_TLB = r"C:\Program Files\ASCON\KOMPAS-3D v22\Bin\kAPI7.tlb"

#: The interfaces a sketch builder has to drive, and the members worth
#: printing for each. `None` prints everything the interface declares.
INTERFACES: tuple[tuple[str, str | None], ...] = (
    ("IPart7", r"Sketchs|Extrusions|DefaultObject|RebuildModel|FindObjects|SelectByPoint"),
    ("IAuxiliaryGeomContainer", None),
    ("IPlanes3D", None),
    ("IPlane3DByOffset", None),
    ("IPlane3D", None),
    ("ISketch", None),
    ("IDrawingContainer", r"LineSegments|Arcs|Circles|Points"),
    ("ILineSegments", None),
    ("ILineSegment", None),
    ("IArcs", None),
    ("IArc", None),
    ("ICircles", None),
    ("ICircle", None),
    ("IPoints", None),
    ("IPoint", None),
    ("IFace", None),
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

    print(f"# KOMPAS sketch API, read from {arguments.tlb}\n")
    for name, only in INTERFACES:
        interface = getattr(module, name, None)
        if interface is None:
            print(f"## {name}\n\nNOT EXPORTED by this type library.\n")
            continue
        print(f"## {name}  {interface._iid_}\n")
        for member in getattr(interface, "_methods_", []):
            if only and not re.search(only, member.name, re.IGNORECASE):
                continue
            dispids = [flag for flag in (getattr(member, "idlflags", None) or []) if isinstance(flag, int)]
            print(f"    [{dispids[0] if dispids else '?'}] {member.name}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
