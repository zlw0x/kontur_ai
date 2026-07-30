# ADR-023: build123d replaces KOMPAS, and M3D leaves the product

**Status:** accepted, 2026-07-30 · **Supersedes in part:** ADR-018 through ADR-022
remain correct about CAD-IR; what changes is what executes it.

## Context

Everything the service builds today goes through `KompasApi7Adapter`, driving
KOMPAS-3D v22 over COM on an STA thread on one trusted Windows machine. Eight
milestones were delivered that way and each of them works. The reason to change
engines is not that the adapter is bad — it is what the adapter *requires*.

Driving KOMPAS means, permanently and per machine:

- **Windows.** The whole CAD half of the service is `net8.0-windows`, and the
  production worker cannot be a Linux container.
- **A licence.** Every machine that builds needs one, so capacity costs licences
  rather than CPU.
- **A GUI application, driven headlessly.** KOMPAS is an interactive program
  being told what to do by a program. Three of the defects found in POSTMVP-005
  and 006 were process-lifecycle traps of exactly this shape: a second API5
  activation quietly starting a second KOMPAS process, twice.
- **Constants nobody can read.** The type libraries export **no enumerations at
  all**. Every integer this repository relies on — extrusion types, arc
  direction, unit bit vectors, sixteen constraint types, point indices, angle
  dimension types — was identified by building geometry and measuring what moved.
  That work is real engineering and it is recorded honestly, but it is a cost
  paid again for every new operation, and some of it was paid twice because a
  wrong table looked plausible.

Against that, the operations the roadmap still wants — fillet and chamfer,
patterns and mirror, hole families, booleans and multi-body, and eventually
sweep, loft and shell — are all ordinary modelling-kernel operations that
OpenCascade exposes directly and documents.

## Decision

**build123d, on OpenCascade, becomes the only CAD engine.** KOMPAS, M3D, COM,
the Windows session and CAD licensing leave the target architecture.

```text
drawing -> AI analysis -> validated CAD-IR
                              |
                        Build123dAdapter
                              |
                         STEP + STL
                              |
                    independent geometry checks
```

Four things this decision fixes in place.

### CAD-IR is the single parametric source of truth

It already was, and nothing about it changes here. The AI writes a document, a
trusted validator checks it, and only then does trusted code drive the kernel.
ADR-018's canonical form, ADR-019's semantic selectors, ADR-020's contours and
ADR-022's constraints-as-assertions all survive the engine change intact —
which is the point of having had a trust boundary that was not a CAD API.

The engine is an implementation of that document, not its owner.

### Two user-facing results, and M3D is not one of them

- **`model.step`** — the exact BREP geometry. This is the deliverable a customer
  takes into any CAD system.
- **`model.stl`** — a mesh, for preview and for manufacturing.

`model.m3d` was the KOMPAS-native format. It is not an interchange format, it
requires KOMPAS to open, and it exists in the pipeline only because KOMPAS is
what built the model. It leaves the product.

The manifest, the validation report and the audit events remain **internal**.
They are how the service knows the model is right; they are not files a customer
receives.

### AI-generated Python is never executed

build123d is a Python API, and that makes one wrong turn newly available and
newly attractive: asking the model to write build123d code and running it.

**This is prohibited.** It is the same rule as before, stated in the terms the
new engine makes tempting. The AI produces CAD-IR JSON and nothing else. The
mapping from CAD-IR to build123d calls is fixed code written by hand in this
repository, reviewed like any other code. No `eval`, no `exec`, no importing a
generated module, no running a generated script, no shelling out.

The reason is unchanged from `AGENTS.md`: AI output is data, it passes a
versioned JSON Schema and a trusted semantic validator, and it is never
executed. An engine written in Python does not weaken that; it makes stating it
again worthwhile.

### The build runs on Linux, in a container, with nothing it does not need

Fixed Python and build123d versions, one temporary directory per job, CPU,
memory, wall-clock and output-size limits, no network during a build, and a
read-only root filesystem. None of that was available while the engine was a
Windows desktop application.

## Consequences

**Good.**

- The production CAD worker becomes a Linux container. Capacity is CPU, not
  licences.
- CI can run real geometry. Today CI cannot build anything at all, and every
  acceptance run in `docs/acceptance/` had to happen on one physical machine.
- New operations stop needing a constant-hunting probe each. `fillet`, `chamfer`,
  `mirror` and the booleans are named, documented calls.
- STEP becomes the primary result, which is what a customer wanted from a
  service that promises an editable model.

**Costs, stated plainly.**

- **Constraints do not carry over as constraints.** KOMPAS has a 2D solver and
  build123d does not. ADR-022's rule survives — a constraint is an assertion
  about coordinates the document already states — but where KOMPAS could also
  *store* those assertions in the delivered file, build123d cannot. The
  parametricity that POSTMVP-007 put into the delivered M3D does not exist in a
  STEP file at all, because STEP is a geometry format, not a feature-tree one.
  What is kept is the checking: an assertion that does not hold still refuses the
  build. What is lost is the customer opening the result and dragging a
  dimension. That is a real reduction and it is recorded here rather than
  discovered later.
- **Selectors need re-implementing on a different topology model.** ADR-019's
  rule — name geometry by meaning, never by index — carries over; the resolver
  does not. See ENGINE-MIG-004.
- **Eight milestones of measured KOMPAS facts stop being load-bearing.** They
  stay in the repository history and in the task documents, because they are the
  record of how the current behaviour was arrived at, and because a claim in an
  acceptance document has to remain checkable against what produced it.
- **POSTMVP-008 revolve was not built on KOMPAS**, deliberately. It was next in
  the plan when this decision was taken, and building it against COM constants
  would have been a week of work that ENGINE-MIG-008 then deletes. It moves to
  ENGINE-MIG-006 and lands on build123d instead. The CAD-IR contract for it is
  written once either way and survives the change.

**Superseded.** The remaining open items on the KOMPAS side are closed as
overtaken rather than done: the auxiliary plane types `Planes3D.Add(15)` and
`Add(16)`, which are COM constants that mean nothing to another kernel; and
POSTMVP-009 onwards as originally scoped against KOMPAS.

The KOMPAS implementation is **not deleted yet**. It stays until build123d
reaches parity on the existing fixtures, because deleting the only working engine
before the replacement is proven is how a migration becomes an outage. Removal is
ENGINE-MIG-008, and it happens after the acceptance of everything before it.

## Alternatives rejected

**Keep KOMPAS and add build123d beside it.** Two engines means every operation is
specified twice, every defect is diagnosed twice, and the fixture corpus has to
prove agreement between them. The neutral engine interface (ENGINE-MIG-002) is
worth having regardless — it is what makes the fake adapter and CI possible — but
running two real engines in production is a permanent tax to avoid a one-time
migration.

**Move to a different commercial kernel.** Same licence and platform constraints,
different vendor. The specific problem is the desktop-application dependency, and
another desktop CAD keeps it.

**Drive OpenCascade directly rather than through build123d.** More control, and a
great deal more code for the same result. build123d is a thin, documented layer
over the kernel this decision is actually choosing; if it ever gets in the way,
dropping to `OCP` underneath it is a local change rather than another migration.

## The rule this carries forward

The engine is replaceable; the trust boundary is not. AI output is data, it is
validated before trusted code consumes it, and it is never executed — in JSON,
and now especially in Python.
