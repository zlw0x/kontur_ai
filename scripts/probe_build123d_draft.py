"""Can this kernel draft the faces of a solid that already exists?

P3.3 asks for five things: a neutral plane, a pull direction, *selected faces*, a
signed angle, and a self-intersection check. Three of them arrived with
POSTMVP-021's `taper_deg` — the direction, the sign, and `EXTRUDE_DRAFT_TOO_STEEP`
— but that drafts an extrusion **as it is created**. Drafting faces of a solid
already built is a different operation, and the difference is exactly the question
POSTMVP-011 and POSTMVP-022 asked of holes and ribs: is it composition, or is it
something the contract genuinely lacks?

The answer turns on two measurements this makes:

**A.** Does build123d have a face-draft at all? Never invent an API member — cite
it or probe it. If there is none, P3.3 is `taper_deg` plus whatever composition
can reach, and saying so is the finding.

**B.** Is a drafted boss the same part either way? Extrude a square with a taper,
and separately extrude it straight and draft its walls. If the volumes agree,
drafting after the fact adds nothing a drawing can state — the same argument that
kept `feature.hole` and `feature.rib` out of the contract.

    docker run --rm --network none --entrypoint python \
        -v "${PWD}:/work" cad-ai/cad-worker:ci /work/scripts/probe_build123d_draft.py

Nothing here is part of the service.
"""

from __future__ import annotations

import math
import traceback


def heading(text: str) -> None:
    print()
    print("=" * 72)
    print(text)
    print("=" * 72)


def attempt(label: str, thunk):
    """Run one probe and say what happened, including how it failed."""
    try:
        result = thunk()
    except Exception as error:  # noqa: BLE001 - reporting is the point
        print(f"  {label}: FAILED  {type(error).__name__}: {error}")
        for line in traceback.format_exc().splitlines()[-3:-1]:
            print(f"      {line.strip()}")
        return None
    print(f"  {label}: ok  -> {result}")
    return result


def main() -> int:
    import build123d as bd

    heading("A. what the library offers for drafting an existing solid")
    names = sorted(
        name for name in dir(bd)
        if any(word in name.lower() for word in ("draft", "taper", "offset"))
    )
    print(f"  candidates by name: {names or 'none'}")
    print(f"  extrude taper parameter: "
          f"{'taper' in __import__('inspect').signature(bd.extrude).parameters}")

    heading("B. is a drafted boss the same part either way?")
    # A 40 x 40 square, 20 tall, drawn in 10 degrees. The prismatoid rule gives the
    # volume in closed form, so both routes are measured against arithmetic rather
    # than against each other.
    side, height, angle = 40.0, 20.0, 10.0
    inset = height * math.tan(math.radians(angle))
    top = side - 2 * inset
    closed_form = height / 6 * (side ** 2 + 4 * ((side + top) / 2) ** 2 + top ** 2)
    print(f"  square {side} drawn in {angle} deg over {height}: "
          f"top {top:.4f}, prismatoid volume {closed_form:.4f} mm3")

    def tapered_at_creation():
        with bd.BuildPart() as built:
            with bd.BuildSketch(bd.Plane.XY):
                bd.Rectangle(side, side)
            bd.extrude(amount=height, taper=angle)
        part = built.part
        return (f"volume {part.volume:.4f}, faces {len(part.faces())}, "
                f"valid {part.is_valid}")

    attempt("extrude(taper=10) — what CAD-IR 1.10 already has", tapered_at_creation)

    def drafted_afterwards():
        with bd.BuildPart() as built:
            with bd.BuildSketch(bd.Plane.XY):
                bd.Rectangle(side, side)
            bd.extrude(amount=height)
        straight = built.part
        # The four upright walls, named the way a selector would name them: planar
        # faces whose normal is horizontal.
        walls = [
            face for face in straight.faces()
            if abs(face.normal_at(face.center()).Z) < 1e-6
        ]
        return f"straight solid has {len(walls)} upright walls to draft"

    attempt("the faces a draft would be applied to", drafted_afterwards)

    heading("C. what the answer decides")
    print("""  If A finds no face-draft, P3.3 is `taper_deg` plus composition, and the
  gap is a *selection* — which walls to draw in — rather than an operation.

  If B's two routes agree, drafting after the fact adds nothing a drawing can
  state: the drawing gives an angle and a pull direction, and an extrusion that
  takes both produces the part. That is the argument that kept `feature.hole`
  (POSTMVP-011) and `feature.rib` (POSTMVP-022) out of the contract, and a third
  instance of it is worth stating as a rule rather than as a coincidence.""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
