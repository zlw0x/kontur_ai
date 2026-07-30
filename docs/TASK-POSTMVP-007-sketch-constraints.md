# TASK-POSTMVP-007: sketch constraints

## Why this milestone exists

POSTMVP-006 made the sketch a real object, but every coordinate in it is a
literal. That is enough to build a part and not enough to *deliver* one: a
customer who opens the M3D finds unconstrained geometry, and changing a width
means moving four lines by hand. It is also the only reason the drawing agent
must do all the trigonometry itself — a tangent arc between two lines needs a
tangent point that nothing in 1.2 can ask for.

## Scope

**In**, from P1.2 and P1.3 of the roadmap: horizontal, vertical, parallel,
perpendicular, tangent, concentric, coincident, midpoint, equal, symmetry,
fixed, collinear; and driving dimensions — linear, aligned, horizontal,
vertical, radial, diametral, angular, coordinate, and distance between
entities, each bound to a stable name.

Plus the two P1.4 checks that were impossible without constraints: conflicting
constraints, and degrees of freedom.

**Out:** everything POSTMVP-006 deferred stays deferred — splines, ellipses,
text, projected geometry, DXF import, arbitrary formulas, open profiles, islands
nested deeper than one level, auto-repair of self-intersections.

## The design question this milestone turns on

Who solves?

**Not us.** A 2D constraint solver is numerically delicate, and KOMPAS already
has one. Writing a second would be the same mistake as reimplementing the
modelling kernel.

**KOMPAS solves, and must agree with the document.** The document keeps explicit
coordinates — POSTMVP-006's rule stands — and adds constraints as *assertions*
about that geometry. The adapter applies both, KOMPAS solves, and the solved
coordinates are compared with the declared ones. If the solver moved the
geometry, the document said two different things about the same part, and the
build stops.

This is stronger than either alternative. Determinism survives: the geometry
that reaches the kernel is still the geometry that was validated. Parametricity
arrives: the delivered M3D has real constraints in it, so a customer can edit
it. And a class of AI error becomes catchable that was invisible before — a
drawing read as "these two edges are parallel" when the extracted coordinates
say otherwise is a misreading, and it now has a name instead of quietly
producing a part nobody notices is wrong.

The residual is real and worth stating: a document whose coordinates the AI
could not compute — the tangent-arc case — is still not expressible, because
the coordinates must be there to be compared. Making the solver *authoritative*
rather than *confirmatory* is a later decision, and it needs a way to record
that the geometry delivered is not the geometry written.

## KOMPAS API evidence

`scripts/probe_kompas_constraints.py`, run against KOMPAS v22.

Constraints attach to the sketch entity, not to the sketch:
`IDrawingObject1.NewConstraint()` `[6002]` returns an `IParametriticConstraint`
carrying `ConstraintType` `[1]`, `Partner` `[3]`, `Index` `[2]` and
`PartnerIndex` `[4]`, `Value` `[5]`, `Expression` `[6]`, `Variable` `[8]`,
`Degrees`/`Minutes`/`Seconds` `[9-11]`, `Axis` `[15]`, `SegmentIndex` `[17]`,
and `Create()` `[13]`. `IDrawingObject1.ConstraintsState` `[6016]` and
`Constraints` `[6001]` read back what an entity carries.

`Variable` and `Expression` are the important pair: a driving dimension can be
bound to a *named* variable in the model, which is exactly what the roadmap asks
for when it says every driving dimension gets a stable name.

### The constants had to be observed, not read

**The type libraries export no enumerations at all** — zero, in both kAPI7 and
kAPI5. So unlike `pTop_Part` or the plane types, which at least had a discovered
number, `ConstraintType` had to be identified by applying each candidate to a
deliberately wrong pair of segments and reading where KOMPAS put them.

Two passes are needed. With a horizontal reference segment, "make B horizontal"
and "make B parallel to A" produce the same answer and the two types cannot be
told apart; an oblique reference separates them. That trap already caught this
probe once.

Reference: `A = (0,0)->(20,10)`, `B = (0,14)->(18,20)` — B neither parallel nor
perpendicular to A, and of a different length, so any of those becoming true is
the constraint speaking.

| `ConstraintType` | B afterwards | Reading |
|---|---|---|
| 3 | horizontal, whatever A is | **horizontal** |
| 4 | vertical | **vertical** |
| 5 | parallel to A | **parallel** |
| 6 | perpendicular to A | **perpendicular** |
| 7 | length equal to A's | **equal** |
| 9 | B's start moved onto A's start | **coincident** (point to point) |
| 17 | parallel to A *and* start on A's line | **collinear** |
| 2 | start moved onto A's line, direction unchanged | **point on curve** |
| 11 | start onto A's start, **A moved too** | a coincidence that adjusts both |
| 20 | start onto A's line, **A moved too** | unidentified |
| 1, 10, 18, 19 | created, nothing moved | unidentified on this geometry |

`Valid` is not a success signal: types 3 to 7 plainly worked and all report
`Valid = False`, while 9, 10 and 11 report true. The geometric effect is the only
reliable evidence, which is why the probe measures rather than asks.

Reading coordinates after `EndEdit` returns zeros for every entity. That looks
exactly like a constraint which collapsed the sketch to the origin, and it cost
one wrong table before the probe read inside the edit instead.

## Not done yet

Everything after the probe.

- **The remaining constants.** Tangent and concentric cannot show up between two
  straight lines, and symmetry needs an axis, so those need reference geometry
  the current probe does not build. Five of the roadmap's twelve constraints are
  still unidentified: tangent, concentric, midpoint, symmetry, fixed.
- **`Index` and `PartnerIndex` semantics** — which endpoint of a segment a
  coincidence refers to. Unprobed.
- **Entity identity in CAD-IR.** Constraints have to name the geometry they
  constrain, and a path's segments are currently a positional list with no ids.
  A constraint referring to "segment 2" would change meaning when segments are
  reordered, which is the index problem ADR-019 exists to prevent, one level
  down. Segments need ids.
- **CAD-IR 1.3**: constraints, driving dimensions bound to named parameters, and
  the version negotiation that goes with it.
- **Trusted validation**: every constraint must hold for the declared
  coordinates within tolerance; contradictory and duplicate constraints
  rejected; degrees of freedom computed and reported.
- **Adapter**: apply constraints and dimensions, let KOMPAS solve, compare the
  solved coordinates with the declared ones and refuse the difference.
- **A real acceptance run**, and an ADR.

## Constraint carried forward

No operation may rely on the solver having moved geometry. Until the comparison
above exists and passes, a constraint is a statement about the part that must
already be true — not an instruction that makes it true.
