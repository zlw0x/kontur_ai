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

**The type libraries export no enumerations at all** - zero, in both kAPI7 and
kAPI5. So unlike `pTop_Part` or the plane types, which at least had a discovered
number, `ConstraintType` had to be identified by applying each candidate to
deliberately wrong geometry and reading where KOMPAS put it.

One reference pair cannot separate everything, so the probe has scenarios. Three
traps, each of which produced a wrong table before it was understood:

- With a **horizontal** reference segment, "make B horizontal" and "make B
  parallel to A" give the same answer and the two types are indistinguishable.
  The reference is oblique for that reason.
- With a reference **sharing a coordinate** with the subject - the first version
  started both at x = 0 - a constraint that aligns those coordinates reads as
  "unchanged". No coordinate is shared now.
- **Tangency and concentricity cannot appear between two straight lines**, and
  the types that express them fail to create there. A subset that creates for
  segments is not the subset that creates for circles, so the probe sweeps 0 to
  40 rather than a curated list.

Reference geometry is wrong in every respect the constraints could fix: not
parallel, not perpendicular, different lengths, not concentric, not tangent.

| `ConstraintType` | Effect measured | Reading |
|---|---|---|
| 1 | creates with no partner, moves nothing, `Valid` true | **fixed** |
| 2 | the defining point moves onto the reference *line*; a circle's centre lands on it | **point on curve** |
| 3 | the subject becomes horizontal whatever the reference is | **horizontal** |
| 4 | the subject becomes vertical | **vertical** |
| 5 | the pair becomes parallel | **parallel** |
| 6 | the pair becomes perpendicular | **perpendicular** |
| 7 | equal length; fails between circles | **equal length** |
| 8 | equal radius; fails between segments | **equal radius** |
| 9 | defining points end at the same *y* | **horizontally aligned points** |
| 10 | defining points end at the same *x* | **vertically aligned points** |
| 11 | defining points coincide; between circles that is centre to centre | **coincident**, which for circles reads as **concentric** |
| 15 | circles become externally tangent; a circle becomes tangent to a line | **tangent** |
| 16 | with `Axis` set, the reference lands exactly on the subject's mirror image | **symmetric about an axis** |
| 17 | parallel *and* the defining point on the reference line | **collinear** |
| 20 | the defining point lands on the reference's **midpoint** | **midpoint** |

That is all twelve constraints P1.2 asks for, with `equal` turning out to be two
distinct types rather than one.

Type 16 was confirmed arithmetically rather than by eye: the axis is the vertical
line x = 10, the subject starts at (3, 14), and the reference's start moved to
exactly (17, 14) - the mirror image.

**`Valid` is not a success signal.** Types 3 to 7 plainly work and all report
`Valid = False`; 9, 10 and 11 report true. The geometric effect is the only
reliable evidence, which is why the probe measures rather than asks.

**Reading coordinates after `EndEdit` returns zeros for every entity.** That
looks exactly like a constraint which collapsed the sketch to the origin, and it
cost one wrong table before the probe read inside the edit instead.

### Driving dimensions are a different mechanism, and one link is still missing

Setting `Value` on a geometric constraint does nothing: no type from 0 to 40
drives a segment's length, span, radius or diameter that way.

Dimensions are separate objects, and they live on `ISymbols2DContainer` rather
than the geometry container - `LineDimensions` `[10001]`, `RadialDimensions`
`[10002]`, `DiametralDimensions` `[10003]`, `AngleDimensions` `[10004]`.

What is established:

- A dimension drawn over a segment must be bound to it first.
  `IDrawingObject1.Associate()` takes no arguments - it binds the dimension to
  whatever its own points already sit on - and returns true.
- Only **after** association do constraint types **13 and 14** create on the
  dimension object. Both fail on geometry, and every other type fails on a
  dimension. So the driving-dimension constraint is one of those two.

What is not established: setting `Value` and `Variable` on type 13 or 14 after
association still leaves the geometry where it was. The likely missing link is
the part's variable table - `IPart7.AddVariable` `[21]` exists, and
`IParametriticConstraint` carries `Variable` `[8]` and `Expression` `[6]` - so a
dimension probably drives by *naming* a variable which is then set, rather than
by carrying a value itself. That is one probe away and it is not done.

## Not done yet

Everything after the probe.

- **How a driving dimension actually drives.** Types 13 and 14 are the
  candidates and association is required; the variable table is the untested
  link. Everything in P1.3 waits on this.
- **`Index` and `PartnerIndex` semantics** - which endpoint of a segment a
  coincidence refers to. Every constraint above was created with both left at
  their defaults, which is why the table says "defining point" rather than
  naming an end.
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
