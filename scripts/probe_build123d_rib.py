"""What build123d actually does when an extrusion is told to stop at geometry.

P3.2 asks for a rib, and the roadmap notes `extrude(until=…)` "fails on the first
attempt" without saying how. This finds out, because the rule here is that a CAD
kernel is driven only through a trusted adapter and API members are never invented
— they are cited or probed.

It also asks a question that has to come before any of that. POSTMVP-011 refused
`feature.hole` because everything it offered was already expressible by
composition, and a second way to say what CAD-IR already says is another thing to
validate. **A rib may be the same.** A drawing that dimensions a rib gives its
thickness and its height, and a trapezoid extruded that far is a rib — no
`until` anywhere. So the probe measures both, and the interesting outcome is
whether they agree.

Run it in the engine image, which is where build123d imports:

    docker run --rm -v "${PWD}:/work" cad-ai/cad-worker:ci \
        python /work/scripts/probe_build123d_rib.py

Nothing here is part of the service. It is a way to find out what the kernel does
before anything in the contract commits to it.
"""

from __future__ import annotations

import traceback


def heading(text: str) -> None:
    print()
    print("=" * 72)
    print(text)
    print("=" * 72)


def attempt(label: str, thunk):
    """Run one probe and report what happened, including how it failed.

    A probe that swallows its exception tells you a thing does not work and not
    what the kernel objected to, which is the half worth having.
    """
    try:
        result = thunk()
    except Exception as error:  # noqa: BLE001 - reporting is the point
        print(f"  {label}: FAILED  {type(error).__name__}: {error}")
        for line in traceback.format_exc().splitlines()[-4:-1]:
            print(f"      {line.strip()}")
        return None
    print(f"  {label}: ok  -> {result}")
    return result


def main() -> int:
    import build123d as bd

    heading("what the library offers")
    print(f"  build123d {bd.__version__ if hasattr(bd, '__version__') else '?'}")
    print(f"  Until members: {[m.name for m in bd.Until]}")
    print(f"  extrude signature: {__import__('inspect').signature(bd.extrude)}")

    # --- the part every probe below stands on -----------------------------
    # An L: a base plate with an upright wall on one end. A rib belongs in the
    # inside corner, joining the two.
    base_l, base_w, base_t = 60.0, 40.0, 8.0
    wall_t, wall_h = 8.0, 40.0

    with bd.BuildPart() as lbracket:
        with bd.BuildSketch(bd.Plane.XY):
            bd.Rectangle(base_l, base_w)
        bd.extrude(amount=base_t)
        with bd.BuildSketch(bd.Plane.YZ.offset(-base_l / 2 + wall_t / 2)):
            bd.Rectangle(base_w, wall_h)
        bd.extrude(amount=wall_t / 2, both=True)
    bracket = lbracket.part
    print()
    print(f"  L-bracket volume {bracket.volume:.4f} mm3, "
          f"{len(bracket.faces())} faces, valid={bracket.is_valid}")

    heading("A. the rib as composition — no `until` at all")
    # The drawing gives the rib its thickness and its reach. A trapezoid in the
    # plane of the corner, extruded that thickness, is the rib. If this is enough,
    # P3.2 needs no new operation, exactly as POSTMVP-011 concluded for holes.
    rib_t, rib_run, rib_rise = 6.0, 30.0, 30.0

    def composed():
        x0 = -base_l / 2 + wall_t
        with bd.BuildPart() as built:
            bd.add(bracket)
            with bd.BuildSketch(bd.Plane.XZ) as profile:
                with bd.BuildLine():
                    bd.Polyline(
                        (x0, base_t),
                        (x0 + rib_run, base_t),
                        (x0, base_t + rib_rise),
                        close=True,
                    )
                bd.make_face()
            bd.extrude(amount=rib_t / 2, both=True)
        return (f"volume {built.part.volume:.4f} "
                f"(bracket + {built.part.volume - bracket.volume:.4f}), "
                f"solids {len(built.part.solids())}, valid {built.part.is_valid}")

    composed_part = attempt("triangular rib, stated dimensions", composed)
    print(f"      closed form for the added wedge: "
          f"{rib_run * rib_rise / 2 * rib_t:.4f} mm3")

    heading("B. extrude(until=…) — what the roadmap says fails")
    # Four spellings, because "fails on the first attempt" does not say which
    # argument the kernel objected to.
    def until_next():
        with bd.BuildPart() as built:
            bd.add(bracket)
            with bd.BuildSketch(bd.Plane.XZ):
                bd.Rectangle(rib_t, rib_rise, align=(bd.Align.CENTER, bd.Align.MIN))
            bd.extrude(until=bd.Until.NEXT)
        return f"volume {built.part.volume:.4f}, solids {len(built.part.solids())}"

    attempt("until=Until.NEXT, builder mode", until_next)

    def until_last():
        with bd.BuildPart() as built:
            bd.add(bracket)
            with bd.BuildSketch(bd.Plane.XZ):
                bd.Rectangle(rib_t, rib_rise, align=(bd.Align.CENTER, bd.Align.MIN))
            bd.extrude(until=bd.Until.LAST)
        return f"volume {built.part.volume:.4f}, solids {len(built.part.solids())}"

    attempt("until=Until.LAST, builder mode", until_last)

    def until_with_target():
        sketch = bd.Plane.XZ * bd.Rectangle(rib_t, rib_rise)
        return bd.extrude(to_extrude=sketch, until=bd.Until.NEXT, target=bracket)

    attempt("algebra mode, explicit target", until_with_target)

    def until_no_target():
        sketch = bd.Plane.XZ * bd.Rectangle(rib_t, rib_rise)
        return bd.extrude(to_extrude=sketch, until=bd.Until.NEXT)

    attempt("algebra mode, no target (expected to fail)", until_no_target)

    heading("C. does `until` even help a rib?")
    print("""  A rib on a drawing is dimensioned: a thickness and a reach, or a
  thickness and an angle. `until` answers a question the drawing has already
  answered, and it answers it by asking the kernel — which means the number that
  ends up in the part is one no document states and no expectation can check.

  So the useful outcome of B is not whether it works. It is whether a rib needs
  it. If A builds the right wedge from stated numbers, P3.2 is composition and
  the contract gains nothing by growing.""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
