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

What is **not** established is how such a dimension drives anything. Four
orderings were tried and all four left the segment at its original 16.553 mm:

1. `Value` set before `Create()`.
2. `Value` set after `Create()`.
3. `Variable` named at `Create()`, then looked up to be set. `IPart7` has no
   `Variables` member at all; `IFeature7.Variables` `[2011]` exists but is a
   named property rather than an indexable collection, so the lookup itself did
   not work either.
4. `Expression` set to the literal instead of `Value`.

That is a negative result worth keeping: it rules out the obvious readings and
says the remaining candidates are `IVariableTable` `[7001-7015]` on the part,
which is a spreadsheet-shaped API with rows, columns and `ApplyVars()`, or a
sketch parametric mode that has to be switched on before a dimension can drive
at all.

**The probe stops here deliberately.** Every constraint P1.2 asks for is
identified, which is the larger half of the milestone and the half the trusted
validator needs. P1.3's driving dimensions need one more day of probing against
a spreadsheet API, and grinding at it now would hold up work that does not
depend on it.

## Done

1. **All twelve constraints** identified by measurement, with the traps that
   produced wrong tables recorded above.
2. **CAD-IR 1.3** — `packages/cad-ir/cad_ir/constraints.py`. Entities gain
   optional ids, constraints and driving dimensions name them, and a point
   constraint names its point.
3. **The trusted gate** — `packages/kompas-adapter/ConstraintValidator.cs`. Every
   constraint checked against the stated coordinates, every dimension against the
   geometry it dimensions, duplicates and flat contradictions refused, degrees of
   freedom counted and reported.
4. **Applied in KOMPAS** — `KompasConstraintApplier.cs`. Constraints and named
   dimensions go into the delivered model, and the geometry is re-read afterwards
   to confirm the solver moved nothing.
5. **A real run** — `docs/acceptance/POSTMVP-007-sketch-constraints.md` — and
   `docs/adr/ADR-022-constraints-are-assertions.md`.

Ten constraints and three driving dimensions on a real plate, verified exactly.
The delivered M3D carries `base_width = 60`, `base_height = 30`,
`hole_radius = 4`, read back in a fresh KOMPAS process. A misread drawing — the
top edge declared parallel to the left one — is refused with zero KOMPAS
processes started.

Three defects came out of the real runs, all written up in the acceptance
document: a construction line invisible to constraints, a dimension that must be
updated before it can be associated, and `IView.Variables` working for exactly
one dimension and then throwing.

## Closed afterwards

Three of the four open ends were closed by two more probes,
`scripts/probe_kompas_points.py` and `scripts/probe_kompas_driving.py`.

### Point constraints are applied

`Index` and `PartnerIndex` were measured by putting a coincidence between two
entities whose every named point is far from every other, and reading which pair
met:

| entity  | 0      | 1     | 2        |
|---------|--------|-------|----------|
| segment | start  | end   | midpoint |
| arc     | centre | start | end      |
| circle  | centre | —     | —        |

Values 3, 4 and -1 create nothing at all.

**The arc is the trap, and it is why the guess was never worth taking.** Its
numbering is not the segment's — index 0 is the centre. One table for both would
have turned every `concentric` between two arcs into a coincidence of their
*start points*: a constraint the document never stated, in a file a customer
opens, with the geometry still measuring correctly because the solver had nothing
to correct.

Which types read which index was measured the same way, by sweeping both and
watching what changed the answer:

- **11 coincident, 9 aligned horizontally, 10 aligned vertically** — both indices.
  9 and 10 equate one coordinate of the two named points rather than the points.
- **20 midpoint, 2 point on curve** — only the subject's. The partner contributes
  a whole entity by definition: its midpoint in one case, its curve in the other.
- **17 collinear** — neither. Every index pair gave the identical result,
  including -1, so it is a relation between two entities and nothing else.

All six kinds are now applied. Nothing is verified-but-skipped.

### A driving dimension needs two constraints, not one

Type 13 alone names a variable that *reports*: setting it changes nothing, and a
rebuild puts the measurement back, because the model computes it from the
geometry. Adding **type 14** on the same associated dimension turns it round.

Measured on a 16 mm segment, one document per attempt so that a sequence could
not be mistaken for a switch:

```text
fixed  external  setter      variable  segment   verdict
False  None      Value       16.000    16.0000   unchanged
False  True      Expression  16.000    16.0000   unchanged
True   None      Value       50.000    50.0000   DRIVEN
True   True      Expression  50.000    50.0000   DRIVEN
```

`External` makes no difference; both `Value` and `Expression` work. The four
readings ruled out earlier were all correct — they were just all missing the
second constraint.

Two dead ends worth keeping:

- `IParametriticConstraint.Reference` is not a "reference dimension" flag. It is
  the generic COM handle every KOMPAS interface carries, and it is read-only.
- The part's variable table is a *property*, `IPart7.VariableTable`, not an
  interface the part casts to. Every `QueryInterface` at it answers `COMError`,
  which reads as "this build has no variable table" and is what sent the previous
  probe looking for a spreadsheet it could never have reached. It turned out not
  to be needed.

### Angular dimensions exist

`IAngleDimensions.Add` takes a type. The previous probe tried 0 to 4, found
nothing, and recorded that angular dimensions do not exist — a statement about
the range swept, not about KOMPAS. Sweeping -2 to 64: **only 10 and 39 create.**

Type 10 is the one. Driven to 55 degrees it leaves the two arms 55 degrees apart.

**Type 39 measures something else.** Driven to 55 it leaves them 27.5 degrees
apart — exactly half — so it is taken against a bisector rather than between the
arms, and using it would put a number in the delivered file that is twice what
the drawing said.

An angle names the two objects it measures through `BaseObject1` and
`BaseObject2`, so unlike every other dimension it needs no `Associate()` and
answers false to it without being any less bound.

### One probe mistake, recorded because it nearly became a finding

An earlier run of the driving probe concluded that the dimension's variable does
not exist until the sketch is closed, and that the adapter's read-back was
therefore a silent no-op. That was wrong: the probe had already called `EndEdit`,
and a view proxy from a closed edit answers nothing at all — indistinguishable
from a variable that was never created. The variable is readable inside the edit
that made it, and the check the adapter performs does run.

## Still not done

- **Constraints are not offered to Codex.** The structured-output dialect has no
  optional properties, so `to`, `axis` and now `to` on a dimension would be
  forced onto every one. They reach the adapter through the manual API, the same
  as selectors.

## Constraint carried forward

No operation may rely on the solver having moved geometry. A constraint is a
statement that is already true, not an instruction that makes it true — and the
check that enforces that is `SOLVER_MOVED_THE_GEOMETRY`.
