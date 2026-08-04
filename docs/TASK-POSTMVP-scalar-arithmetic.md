# A parameter that drives something: arithmetic in a canonical scalar

**Date:** 2026-08-04 · **Status:** designed, with the model and the resolver built and
tested. Not in `Scalar` — that is a CAD-IR version.

This is the open end of run 5 (`docs/acceptance/POSTMVP-016-runs-2-6-what-the-cycle-states.md`),
and it is the only defect the nine real Codex runs turned up that is still unfixed.

## The defect, in one sentence

A flange document carried `outer_diameter: 80` from the reading stage — cited to the Ø80
callout — drew a literal `radius: 40`, and restated 80 as a literal in its bounding-box
expectation. **Change `outer_diameter` to 100 and the flange stays Ø80**, measured:

```text
valid: true
  bounding_box   expected [80.0, 80.0, 8.0], measured [80.0, 80.0, 8.0]
```

Three copies of one dimension, and the copy with the best provenance — the one the
*reading* stage wrote with a citation — is the one nothing reads. The two that survive
into the geometry share an author, so a slip that lands in both agrees with itself.

## Why the obvious check cannot ship

`PARAMETER_DRIVES_NOTHING` — a document may not declare a dimensional parameter nothing
references — was written, measured against everything in the repository, and reverted. It
named the three parameters found by hand on the flange, and also refused four of the ten
canonical fixtures. Every refusal has the same cause:

| parameter | value | what the geometry needs | the arithmetic |
|---|---|---|---|
| `outer_diameter` | 80 | radius 40 | × 0.5 |
| `hole_diameter` | 6 | radius 3 | × 0.5 |
| `hole_pcd` | 60 | centres at 30 | × 0.5 |
| `param.cap_radius` | 15 | y = +15 **and** −15 | × −1 |
| `param.length` | 80 | nothing — it is 2 × (25 + 15) | — |

A `Scalar` is `float | ParameterRef`. It can carry a magnitude and not a half of one, so
**the parameters are unused because the contract gives them nowhere to go.** Shipping the
check would force one of two worse documents: delete a dimension read off the drawing with
a citation, or reference the parameter on one side of a symmetric outline and write a
literal on the other.

The last row resolves separately and needs no arithmetic: an *overall* dimension belongs
in an expectation, where it is actually compared against the built part, rather than in a
parameter nothing consumes.

## What already exists, and what that settles

Run 5 recorded the blocker as needing "a CAD-IR version, an evaluator in trusted code, and
a decision about how much expression language is safe to accept from a model."

**Two of those three are already in the tree.** `packages/cad-ir/cad_ir/expression.py` is a
recursive-descent parser with a fixed grammar: bounded input (512 characters), bounded
result (1e6), `+ - * / ( )`, unary minus, a whitelist of three functions (`min`, `max`,
`abs`), the constant `pi`, and no name that is not a declared parameter. It refuses
`__import__('os').system('whoami')` and `1 / 0`, and there is a test for each. It is not
`eval` and never was.

It is reachable only from `cad_ir/validator.py`, the 0.1.0 validator, which nothing in the
pipeline calls any more — CAD-IR 0.1.0 had `{"expr": "p_depth"}` and the canonical form
replaced expressions with plain references. So the safety question was answered in 0.1.0
and the answer is still shipped and still tested. **What is blocked is the canonical
representation, not the evaluation.**

## Why not simply re-admit `{"expr": …}`

Because it cannot be canonical, and canonical form is what the trust boundary is made of.

ADR-018 makes a document's meaning a byte-stable hash of a unique representation.
`"d/2"`, `"d / 2"`, `"d*0.5"` and `"0.5*d"` are the same part with four different hashes.
Every downstream property depends on that not happening: the audit trail, the
determinism check that rebuilds a part and compares bytes, and the repair loop's ability
to say "this is the same document you gave me". A canonicaliser for expressions — parse,
normalise, re-print — is possible and is another correctness problem nobody has to take on.

A structured AST (`{"op": "divide", "left": …, "right": …}`) is unique up to associativity
and commutativity, which is to say not unique: `a + b` and `b + a` are two hashes again.
It also needs a recursion depth, a cycle check, and an operator vocabulary offered to the
model through the Codex dialect.

## The design: a parameter times a constant

```json
{ "parameter": "outer_diameter", "times": 0.5 }
```

One node. No parser, no recursion, no precedence, no depth bound, one multiplication in
trusted code — and **one spelling per part**, so the hash stays what ADR-018 says it is.

It covers every row of the table above that arithmetic can fix, which is the reason to
stop there rather than at a general expression:

- a diameter driving a radius, three times over: `times: 0.5`
- one parameter driving both sides of a symmetric outline: `times: -1`
- the near edge of a centred rectangle: `times: -0.5`

Two rules, each of which is a refusal in the model rather than a convention:

- **`times` is never 1.** That is a plain `ParameterRef`, and a second spelling of one part
  is what canonical form exists to prevent.
- **`times` is never 0.** A factor of zero drives nothing, which is the defect this form
  was added to fix.

Bounded at ±1e6, the same bound the expression evaluator has always applied to its result —
and the bound is checked again **after** the multiplication, because 900 000 × 100 is two
legal numbers and a part the size of a county.

### What it deliberately does not do

**No sums.** `a + b` brings commutativity back and with it two hashes for one part. The one
row that wanted a sum (`param.length` = 2 × (25 + 15)) is the row that belongs in an
expectation.

**No trigonometry.** The flange's hole centres at 15 / 25.98 are `cos 60°` and `sin 60°` of
half the pitch circle — and the right way to state a bolt circle is
`pattern.circular`, which has been in the contract since 1.6 and states the count as well.
The runs found that the pattern is *offered and not taken* (a drawing saying "6 × Ø6 on a
Ø60 PCD" comes back as six islands in one sketch); a document that has to express the
centres in trigonometry to reference a parameter would have one more reason to compose them
by hand. Two problems, one fix, and the fix is the one already built.

**No parameter driving a parameter.** `Parameters.of` already refuses that, because the
order of resolution is something CAD-IR does not state. A scaled reference is one level of
indirection, exactly like a plain one.

## What is built, and what a version costs

Built and tested here, because a design whose arithmetic nobody ran is a guess:

- `cad_ir.base.ScaledParameterRef` — the model and its two refusals.
- `Parameters.resolve` in the engine — the multiplication and the range check.
- `packages/build123d-adapter/tests/test_parameters.py` — 22 tests, including the five
  rows of the table as parametrised cases, and the two refusals `Parameters` has carried
  untested since ENGINE-MIG-002.

**`Scalar` is untouched**, so no document the validator accepts can reach the new branch.
One test asserts that on purpose: it fails when the contract takes the form, which is when
it and the note in `base.py` should be deleted.

Wiring it is a CAD-IR version, and the work is:

1. `Scalar = float | ParameterRef | ScaledParameterRef`, and the generated schemas follow.
2. The version bump, which renames every fixture — `tests/cad_ir_fixtures.py` and
   `CadIr.FileSuffix` mean no source names one.
3. The output profile's `scalar` node gains a third `anyOf` branch. Dialect-legal as it
   stands: an object, both properties required, `additionalProperties: false`. Worth
   offering `times` as an **enum** of the factors a drawing actually implies — 0.5, −1,
   −0.5 — rather than a free number, on ADR-032's principle that the profile offers
   constants where the contract is general.
4. `PARAMETER_DRIVES_NOTHING` in `_parameter_issues`, restricted to `length` and `angle`
   parameters as it was when it was measured. A `count` records something no contour can be
   driven by, and refusing that would punish the honest act of carrying a hole count.
5. The four fixtures the check refused, rewritten to reference their parameters — which is
   the point of the exercise and the only way to know the check is right.
6. The compilation prompt, which has to be told that a diameter drives a radius through a
   factor rather than by restating it.

Steps 4 and 5 are the deliverable. Steps 1–3 are how they become possible.
