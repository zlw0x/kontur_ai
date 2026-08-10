"""CAD-IR 1.13: an extrusion that stops at a face the document names.

The rule three milestones arrived at is that an operation earns its place only when
it says what composition cannot. This one says: *this far, and I am not the one who
knows how far that is.*

**The kernel's own answer was measured and rejected.**
`docs/TASK-POSTMVP-P3-2-up-to-a-face.md` put sixteen cases of
`Solid.extrude_until` through build123d 0.11.1. Two are correct. Three raise. Three
**succeed wrongly**, and the middle one of those is the reason nothing here calls it:

    a profile inside the material, extruded +Z "until the next face", returns one
    valid solid reaching z = 62.45 -- which is 5 + sqrt(40² + 40² + 10²), the trial
    extrusion's own length, and has nothing to do with the drawing.

That is the fourth instance of the finding ADR-033 states as a rule: this kernel's
failure mode is a plausible answer. Every over-driven operation before this was
caught by a post-check comparing the result against a number the document stated —
`SHELL_NO_CAVITY`, `SWEEP_BEND_TIGHTER_THAN_PROFILE`, `EXTRUDE_DRAFT_TOO_STEEP`.
**`until` states no number at all.** That is its whole appeal and it is exactly why
the pattern that caught the last three defects has nothing to compare with.

So the document names the face and trusted code computes the reach:

    reach = ((p - o) · n) / (d · n)

`o` is the sketch plane's origin, `d` the unit travel, and `p`/`n` a point on the
named face and its plane normal. Then the engine extrudes by `reach` — the operation
it has performed since ENGINE-MIG-003, with its existing post-checks and its
existing determinism.

Measured against the kernel on a boss growing to the underside of a plate 20 mm up:

    closed form   26261.946711 mm3
    computed      26261.946711 mm3
    until=NEXT    26261.946711 mm3
    difference         0.000e+00

Bit-for-bit the same part, and the computed one has a volume the corpus can state in
closed form — which `until` never could, because the distance was the kernel's
secret.

The three failures become three different things, and none of them is silent: a
profile inside the material reaches the surface it is already under and adds nothing
visible; a profile *on* the face gets a zero reach and is refused; a profile that
misses the face laterally comes back as two solids, which `body_count` already sees.
"""

from __future__ import annotations

from .selectors import Cardinality, ExactlyN, FaceSelector

#: Below this, the travel is parallel to the face's plane and there is no
#: intersection to compute.
#:
#: A tolerance rather than an equality, because `d · n` is a dot product of two unit
#: vectors that came out of a kernel: exact zero is not a value floating point
#: reliably produces, and the honest way to say "parallel" is to say how parallel.
PARALLEL_TOLERANCE = 1e-9


class UntilFaceError(ValueError):
    """A reach the contract refuses to let the engine guess at.

    Carries a code because the repair loop decides on codes: a message telling the
    compiling agent to name a different face is only useful if something classified
    it as repairable first.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        # The code is in the *message* as well as on the exception, because this is
        # raised inside a pydantic validator and everything raised there arrives at
        # the caller as `SCHEMA_INVALID`. The loop decides on the code and the
        # compiling agent reads the message, so the rule that fired has to be in the
        # text or the agent is told only that something was wrong.
        super().__init__(f"{code}: {message}")


def validate_until_face(selector: FaceSelector) -> None:
    """The face an extrusion stops at is exactly one face.

    `all`, `zero_or_one` and `one_or_more` are refused, and the reason is sharper
    than the blend rule ADR-026 states. A blend that matched nothing is a feature
    that silently did not happen; **two faces here are two different reaches**, and
    the engine would compute one of them and build a part whose length nobody chose.

    `exactly_n` with n = 1 is accepted, because it is the same statement written the
    way the output profile is able to write it (ADR-032).
    """
    cardinality = selector.cardinality
    if isinstance(cardinality, ExactlyN):
        if cardinality.count != 1:
            raise UntilFaceError(
                "UNTIL_FACE_NOT_ONE",
                f"selector {selector.id} names {cardinality.count} faces; an extrusion "
                "stops at exactly one, because two faces are two different reaches",
            )
        return
    if cardinality is not Cardinality.EXACTLY_ONE:
        raise UntilFaceError(
            "UNTIL_FACE_NOT_ONE",
            f"selector {selector.id} declares {cardinality}; an extrusion stops at "
            "exactly one face, because two faces are two different reaches",
        )


__all__ = ["PARALLEL_TOLERANCE", "UntilFaceError", "validate_until_face"]
