# ADR-022: A constraint is an assertion about the geometry, not an instruction

## Status

Accepted on 2026-07-30.

## Context

POSTMVP-006 made the sketch a real object with every coordinate a literal. That
is enough to build a part and not enough to deliver one: a customer who opens the
M3D finds unconstrained geometry, and changing a width means moving four lines by
hand.

Adding constraints raises one question that decides everything else. **Who
solves?**

Writing our own 2D constraint solver is the same mistake as reimplementing the
modelling kernel: numerically delicate, and KOMPAS already has one. So KOMPAS
solves. But letting the solver be *authoritative* — the document states
constraints and the kernel produces the coordinates — would give up the property
every earlier milestone was built to protect: that the geometry which reaches the
kernel is the geometry that was validated.

## Decision

### The coordinates stay the truth; a constraint says something about them

A constraint is an assertion about the geometry the document already states. The
trusted gate checks that the assertion holds, and refuses the document when it
does not. Then the constraints are applied to the KOMPAS sketch, and the geometry
is re-read to confirm the solver moved nothing.

That keeps three things at once.

*Determinism.* Nothing solves the geometry into something else, so the part built
is the part validated. The acceptance run's bounding box is exact rather than
within tolerance, because there was nothing to round.

*Parametricity.* The constraints and the named dimensions are in the delivered
file. Read back out of the saved M3D in a fresh process: `base_width = 60.0`,
`base_height = 30.0`, `hole_radius = 4.0`. The same words appear in the document,
in the file the customer receives, and in any later diff.

*A new class of error becomes catchable.* An extraction that says two edges are
parallel while the coordinates it also extracted say otherwise has misread one of
the two. Before this, nothing could tell. It is now
`CONSTRAINT_NOT_SATISFIED`, naming both operands, raised before any COM object
exists.

### Nothing is repaired

The geometry is not nudged to satisfy the constraint, and the constraint is not
dropped to satisfy the geometry. Either would be a guess about which half of the
document was right, and a guess that builds is worse than a refusal that
explains.

### The solver is asked, and its answer is checked

After the constraints are applied, every named entity is re-read and compared
with what was drawn. A correct solver has nothing to do — every constraint was
already true — so any correction means our arithmetic and the kernel's disagree
about the same relation, and building on either would be building on a guess. A
micron of drift is allowed for double arithmetic; more is
`SOLVER_MOVED_THE_GEOMETRY`.

### A point constraint names its point

Consecutive segments of a closed contour meet end-to-start, so a coincidence that
always meant "start to start" would be false for every corner of every rectangle.
A check that is false for the commonest case gets turned off rather than fixed, so
both contracts carry `of_point` and `to_point`. Stating one where a point means
nothing is refused: noise a reader has to decide to ignore is noise the next
reader decides differently about.

### A driving dimension carries the document's own name

`base_width`, not `v1`. The name becomes the KOMPAS variable's name, which is
what makes the delivered file legible. The variable reads back as what KOMPAS
measured, and the document's stated value is compared against it — a dimension
that disagrees with what it dimensions is a document contradicting itself.

### Degrees of freedom are reported, never enforced

A document with explicit coordinates is normally under-constrained, and that is
correct: the coordinates are the truth and the constraints exist so the delivered
model can be edited. Over-constrained is reported the same way. KOMPAS is the
authority on whether its own solver is satisfied, and a count of our own is
exact for independent constraints and optimistic for redundant ones.

### The KOMPAS integers were measured, not read

The type libraries export **no enumerations at all**, so every `ConstraintType`
was identified by applying it to deliberately wrong geometry and reading where the
kernel put things. All twelve constraints the roadmap asks for are covered, with
`equal` turning out to be two distinct types. The integers are pinned by a test,
so a wrong edit fails a build rather than silently doing something else.

## Consequences

The buildable geometry is unchanged. What changed is that a document can now
contradict itself in a way the service notices, and that the file a customer
receives can be edited.

Two limits are real and stated rather than hidden.

**Point constraints are verified but not applied.** `Index` and `PartnerIndex`
select which endpoint, and which values mean what is unmeasured. Applying one
with the defaults would put a constraint in the delivered file that the document
did not state, which is worse than leaving it out. Six kinds are affected;
all six are still checked.

**No driving dimension drives programmatically.** The variable reports the
measurement, and setting it does not move the geometry. The confirmatory design
does not need it to — the document carries the coordinates — and a customer
editing the file in the KOMPAS UI can drive it there. Four ways of trying are
recorded, which narrows what a later attempt should try next.

A third limit is by choice: a document whose coordinates the AI could not compute
— a tangent arc between two lines, where the tangent point needs trigonometry —
is still not expressible, because the coordinates have to be there to be compared
against. Making the solver authoritative is a later decision and needs a way to
record that the geometry delivered is not the geometry written.

## Alternatives rejected

**Our own solver.** Numerically delicate, and duplicates the kernel.

**An authoritative KOMPAS solver.** It would express the tangent-arc case, and it
would mean the part built is not the part validated. Every gate this service has
depends on those being the same thing.

**Applying point constraints with the default indices.** A constraint in the
delivered file that the document did not state is a lie in the artifact, and a
quiet one.

**Dropping a constraint that does not hold.** That is the misread-drawing case
resolving itself silently, which is exactly the failure this milestone was built
to surface.
