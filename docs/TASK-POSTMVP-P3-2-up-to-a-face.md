# P3.2: an extrusion that stops at a face — the investigation

**Date:** 2026-08-04 · **Status:** designed, not built. Nothing in this document changes
CAD-IR; it is what the next version needs to say, and why.

Rib was blocked on one sentence, written twice — in `docs/POST-MVP-ROADMAP.md` and in the
POSTMVP-020/021 acceptance record:

> Rib needs "extend to the next face", which is `extrude(until=…)` — probed and failing on
> the first attempt with `Extrusion is None`, so it needs its own investigation rather than
> a guess.

This is that investigation. It was done with the kernel, not from documentation, and it
ends somewhere other than where it started: **`extrude(until=…)` should not be used at
all.** What P3.2 needs is a distance trusted code computes, and the kernel does the
extrusion it has always done.

## What `extrude(until=…)` actually does

build123d 0.11.1, `Solid.extrude_until`: extrude the profile by `find_max_dimension`, cut
the target with it, sew the affected target faces into shells, sort those by distance from
the profile, take the first (`NEXT`/`PREVIOUS`) or last (`LAST`/`FIRST`), and split the
long extrusion by it keeping `Keep.TOP` or `Keep.BOTTOM`.

Sixteen cases against a 40 × 40 × 10 block, eight rows because the modes pair up. Only the
first row is the behaviour anybody wants:

| case | result |
|---|---|
| pad at z=30, `dir=-Z`, `NEXT` / `LAST` | **correct** — z 10 … 30, one valid solid |
| pad at z=30, no `dir`, `PREVIOUS` / `FIRST` | correct — the modes that reverse |
| pad at z=30, `dir=-Z`, `PREVIOUS` / `FIRST` | `ValueError: No intersection` |
| pad **on** the top face, `dir=-Z`, `NEXT` | `RuntimeError: Extrusion is None` |
| pad **inside** the block at z=5, `+Z`, `NEXT` | "succeeds": a spike to **z = 62.45** |
| pad 60 × 60 over a 40 × 40 block, `NEXT` | `ValueError: Null TopoDS_Shape object` |
| cut from z=20 downwards, `NEXT` | "succeeds", removes **nothing** (16 000 → 16 000) |
| cut from z=20 downwards, `LAST` | removes the full 10 mm bore |

Three of those deserve names.

**`Extrusion is None` is not a general failure — it is one geometry.** It reproduces when
the profile sits *on* the face it is extruding into: the nearest limit surface is then at
distance 0, the split has nothing on the requested side, and step 5 raises. Two of the
sixteen cases above are plainly correct, so the blocked sentence generalised from one
geometry to the whole argument. Corrected here.

**A profile inside the material produces a spike into open space and reports success.** The
pad at z=5 extruded `+Z` `until=NEXT` should stop at the top face, 5 mm away. It returns a
valid one-solid part of 21 244.56 mm³ reaching **z = 62.45** — `Keep.TOP` kept the wrong
side of the limit, so what came back is the far end of the trial extrusion:
5 + √(40² + 40² + 10²) = 5 + 57.446 = 62.446, which is `find_max_dimension` and has nothing
to do with the drawing. This is the fourth instance of the finding ADR-033 states as a rule:
*this kernel's failure mode is a plausible answer.*

**A cut to the next surface can remove nothing.** From z=20 downwards the first surface is
the block's top at z=10, so the tool occupies z 10 … 20 — entirely outside the block. One
valid solid, unchanged volume, no error.

## Why no post-check can catch those

Every over-driven operation so far has been caught by comparing the result against a number
the document stated: `SHELL_NO_CAVITY` compares volume before and after, `SWEEP_BEND_…`
compares a bend radius against the profile's reach, `EXTRUDE_DRAFT_TOO_STEEP` compares the
built height against the stated distance.

**`until` states no number at all.** That is its entire appeal — the drawing says "up to
the web" rather than "17.5 mm" — and it is also why the pattern that has caught the last
three defects has nothing to compare with. A `feature.extrude` with `until: next` is a
document that cannot be checked, by construction.

## The design: name the face, compute the distance

The rest of the contract already answers this. ADR-019: *a new operation must name its
faces and edges with a selector, never an index.* ADR-024: a revolve names its axis. The
same move here removes the problem instead of managing it.

Given a profile on a plane with origin `o` travelling along unit `d`, and a **planar** face
the document names by a selector, with plane normal `n` through point `p`:

```
reach = ((p - o) · n) / (d · n)          refused when |d · n| < 1e-9
```

Then extrude by `reach` — the operation the engine has performed since ENGINE-MIG-003, with
its existing post-checks, its existing arithmetic, and its existing determinism.

**Measured against the kernel's own answer**, on a boss growing from a block's top face to
the underside of a plate 20 mm above it:

```
closed form   26261.946711 mm3      (40x40x10 + 40x40x5 + pi x 6^2 x 20)
computed      26261.946711 mm3      13 faces, valid
until=NEXT    26261.946711 mm3      13 faces, valid
difference         0.000e+00
```

Bit-for-bit the same part, and the computed one has a volume the corpus can state in closed
form — which `until` never could, because the distance was the kernel's secret.

The three failures above become three different things:

| case | with a named face |
|---|---|
| profile inside the material | reach = 5, material 5 … 10 inside what is there: 16 000 mm³, z max 10 — a harmless no-op instead of a spike |
| profile on the terminating face | reach = 0, refused by the contract as a zero distance |
| profile that misses the face laterally | a floating column, **2 solids** where the document declares 1 — caught by `body_count` |

The last one is worth stating plainly: a named plane is infinite, so the arithmetic always
answers. What it cannot know is whether the extrusion actually lands on the face. It does
not need to — the part comes back in two pieces and the expectation the document already
carries sees it (measured: 2 solids, x reaching 105 on a 40 mm block).

## What CAD-IR would say

A new *mode* on the extrusions that already exist, beside `distance`, `through_all`,
`both_directions` and `taper_deg` — not a new feature type, for the reason POSTMVP-011
refused `feature.hole`: another type is another thing to validate saying what the contract
already says.

```
until_face: FaceSelector   # exactly_one, and never a cardinality that permits zero
```

Rules the measurements above earn, each of which is a refusal in trusted code:

1. **`exactly_one`.** ADR-026's rule for blends, and for a sharper reason: two faces are
   two different reaches and the engine would pick one.
2. **Planar only.** `UNTIL_FACE_NOT_PLANAR`. A cylinder has no single plane to reach, and
   "the nearest point of it" is a distance the drawing did not give.
3. **Not parallel to the travel.** `UNTIL_FACE_PARALLEL` when `|d · n| < 1e-9`. There is no
   intersection to compute, and a tolerance is the only honest way to say it.
4. **A positive reach.** `UNTIL_FACE_BEHIND` when the face's plane sits behind the profile
   along `direction`. The kernel's answer to this is `PREVIOUS`, which is a second way to
   state a direction the document already states.
5. **Mutually exclusive with `distance`, `through_all` and `taper_deg`.** The first two for
   the reason the contract already refuses `through_all` with a distance; the taper because
   the far end would then be a width nobody stated (the same argument ADR-033 makes).
6. **The reach is reported.** The manifest records the number trusted code computed, so a
   part built "up to the web" has an auditable dimension. Without it, this is the one
   operation whose size appears nowhere.

`both_directions` is refused as well: half of a reach in each direction is not a thing a
drawing says.

## What this unblocks, and what it does not

**Rib (P3.2)** becomes an ordinary extrusion of a web profile up to a named face, with the
rib thickness as `both_directions` on a *different* axis — that is, drawn on a plane and
extruded symmetrically, which the contract has done since 1.10. Only the reach was missing.

**Up-to-face extrusion (P2.1)** is the same feature under its own name; it was listed
separately and it is one contract change.

**The claim needs nothing new.** A boss up to a face is a lump of material, counted as one
solid exactly as it is today. What the reading stage would state is the *face*, and it
cannot: a face selector is dialect-legal since ADR-032 only as a **named selection** written
here, and "the face this rib lands on" is not a constant. So this arrives, like the shell
did, as an operation the corpus builds and the cycle cannot yet ask for.

**The thread callout (P2.3)** is untouched and still belongs with the annotation work.

## Reproducing the measurements

The probes are three short scripts and no fixture; they are not committed because they test
the kernel rather than this repository. Each is quoted in full in the tables above, and the
essential one is four lines:

```python
n = face.center_location.z_axis.direction
reach = (face.center() - profile_plane_origin).dot(n) / direction.dot(n)
```

One caution for whoever writes the tests: `Shape.is_valid` is a **property** in build123d
0.11.1, not a method. Calling it raises `TypeError: 'bool' object is not callable`, which
looks like a geometry failure and is not — it cost twenty minutes here.
