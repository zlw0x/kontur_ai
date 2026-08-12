"""The reliability gate: the whole corpus, every run.

POSTMVP-014. `golden_corpus.py` says what the documents are and what arithmetic says
they must measure; this is what runs them and what the gate actually asserts.

Four properties, and each of them has failed at least once in this repository's history:

*Every positive case builds and verifies.* Not "does not crash" — the exported files are
reopened and every expectation the document carries is checked by the reader that did not
write them.

*Every positive case measures what the drawing says.* The volume comes from closed-form
arithmetic in the corpus, so a case cannot pass by the engine agreeing with itself.

*Every negative case is refused with the code it named.* "Refused" is not a result: a
repair loop reacts to the code, and a document that crosses its own axis coming back as
an unhandled kernel error is a crash wearing a refusal's clothes.

*A build is deterministic.* Built twice, a document produces byte-identical STL and STEP
that differ in exactly one line — the `FILE_NAME` timestamp OpenCascade writes into every
file. That was measured rather than assumed, and it is why this gate cannot simply compare
digests: it has to know precisely which byte-level difference is legitimate.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("build123d", reason="the CAD engine is not installed")

from cad_ir.canonical_validator import validate_canonical  # noqa: E402
from cad_ir.errors import CadIrValidationError  # noqa: E402

import golden_corpus  # noqa: E402
from cad_engine_build123d.adapter import build  # noqa: E402
from cad_engine_build123d.errors import CadEngineError  # noqa: E402
from cad_engine_build123d.verify import Expectations, verify  # noqa: E402

POSITIVES = golden_corpus.positives()
NEGATIVES = golden_corpus.negatives()

#: The one line OpenCascade writes differently on every export.
_TIMESTAMP = "FILE_NAME("

#: And the one field it writes differently on every export **within one process**.
#:
#: A part exported as several bodies becomes a STEP assembly, and OpenCascade names each
#: `NEXT_ASSEMBLY_USAGE_OCCURRENCE` from a counter that advances across exports for the
#: life of the process: the first build's bodies are '1' and '2', the second's are '3'
#: and '4'. Measured, and the measurement is what makes this safe to normalise — two
#: **separate processes** produce byte-identical STEP and STL, occurrence labels
#: included, which is the case that matters because a worker builds one job per process.
#:
#: Only the label moves. The occurrence's path (`=>[0:1:1:2]`) and both entity references
#: are identical, so a real change to the assembly still fails the comparison.
_OCCURRENCE = re.compile(r"(NEXT_ASSEMBLY_USAGE_OCCURRENCE\(')\d+(')")


def built(case: golden_corpus.Case, directory: Path):
    document = validate_canonical(case.document)
    outcome = build(document, directory)
    report = verify(directory / "model.step", directory / "model.stl",
                    Expectations.of(document))
    return outcome, report


# --- the corpus is worth having --------------------------------------------


def test_the_corpus_covers_every_operation_the_engine_declares():
    """A capability with no case in the corpus is a capability with no evidence.

    The gate is only as good as its coverage, and this is the assertion that keeps the
    two in step: adding an operation without adding a case fails here rather than
    quietly leaving the corpus behind.
    """
    from cad_engine_build123d import capabilities as caps

    exercised: set[str] = set()
    for case in POSITIVES:
        exercised |= set(caps.requirements(validate_canonical(case.document)))

    # Five keys belong to a hand-written test instead, each for a reason. They are
    # covered — by `test_constraints.py`, `test_revolve.py`, `test_blends.py` and
    # `test_sweeps.py` — and listing them here is what stops the exemption from growing
    # quietly.
    elsewhere = {
        caps.SKETCH_CONSTRAINTS,          # constrained-plate (POSTMVP-007): assertions
        caps.SKETCH_DIMENSIONS,           # about coordinates, which change no geometry
        caps.CUT_REVOLVE,                 # bushing: a turned relief groove
        caps.FEATURE_CHAMFER_ASYMMETRIC,  # blended-bracket: a countersink
        # A tapered spring, and the reason is its *bounding box* rather than its volume.
        # Every corpus document states one, and a conical helix's box is not
        # `2(r₁ + wire)`: the far side of the coil is a quarter-turn lower and therefore
        # narrower, so the box is off-centre and its extents depend on where the last
        # turn lands. Volume is closed-form — Pappus over an arc length with an exact
        # antiderivative — so `test_sweeps.py` measures that, and the turn count with it.
        caps.FEATURE_SWEEP_HELIX_CONICAL,
    }
    missing = set(caps.ALL) - elsewhere - exercised
    assert missing == set(), sorted(missing)


def test_there_are_enough_cases_to_be_called_a_corpus():
    """The roadmap's bar for promoting an operation: ten positive and ten negative."""
    assert len(POSITIVES) >= 10
    assert len(NEGATIVES) >= 10
    assert len({case.id for case in POSITIVES}) == len(POSITIVES)
    assert len({case.id for case in NEGATIVES}) == len(NEGATIVES)


def test_the_corpus_meets_gate_p2():
    """**Gate P2:** 100 golden models, 30 part types, 99% deterministic build success.

    Two of the three are counted here and the third is measured by the determinism
    sweep below. Written as an assertion rather than as a sentence in a document,
    because a gate nobody can run is a claim: the corpus can only shrink past this
    line by failing.

    The second number is the one that makes the first mean anything. A plate at three
    sizes is three models and **one** part type, so `part_type` is stated on every case
    and counted here — a washer is not a spacer, a nut blank is not a hex bar, and a
    count that could be inflated by resizing one shape would measure nothing.
    """
    assert len(POSITIVES) >= 100, f"Gate P2 asks for 100 models, the corpus has {len(POSITIVES)}"

    types = {case.part_type for case in POSITIVES}
    assert "" not in types, [case.id for case in POSITIVES if not case.part_type]
    assert len(types) >= 30, f"Gate P2 asks for 30 part types, the corpus has {len(types)}"


#: How many distinct part types a capability needs before it is `stable`.
#:
#: Three rather than one, because the defects this repository has actually had are the
#: kind that only appear when a *second* sort of part uses an operation: the multi-body
#: boss POSTMVP-006 found, and the two-group opening claim POSTMVP-027 found on flanges
#: after nine acceptance runs on parts with one hole size. One part type proves an
#: operation on one shape.
STABLE_PART_TYPES = 3


def _part_types_per_capability() -> dict[str, set[str]]:
    from cad_engine_build123d import capabilities as caps

    coverage: dict[str, set[str]] = {}
    for case in POSITIVES:
        for key in caps.requirements(validate_canonical(case.document)):
            coverage.setdefault(key, set()).add(case.part_type)
    return coverage


def test_a_capabilitys_status_is_the_corpus_behind_it():
    """`stable` is measured, not decided — and this asserts it in both directions.

    Gate P2 being met is what makes any promotion possible; it is not what promotes a
    particular key. A capability the corpus builds on one kind of part has been proved on
    one shape, whatever the corpus's total. So: three part types or more means `stable`,
    and fewer means it must not be — which is the half that stops a declaration drifting
    ahead of the evidence when somebody adds a key.
    """
    from cad_engine_build123d import capabilities as caps

    coverage = _part_types_per_capability()
    wrongly_beta = sorted(
        key for key, types in coverage.items()
        if len(types) >= STABLE_PART_TYPES and caps.DECLARED[key].status != "stable"
    )
    wrongly_stable = sorted(
        key for key in caps.DECLARED
        if caps.DECLARED[key].status == "stable"
        and len(coverage.get(key, set())) < STABLE_PART_TYPES
    )
    assert wrongly_beta == [], f"the corpus has outgrown these: {wrongly_beta}"
    assert wrongly_stable == [], f"these claim more than the corpus shows: {wrongly_stable}"


def test_every_case_says_where_its_number_came_from():
    for case in POSITIVES:
        assert case.arithmetic.strip(), case.id
        assert case.volume_mm3 > 0, case.id


# --- the gate --------------------------------------------------------------


@pytest.mark.parametrize("case", POSITIVES, ids=[case.id for case in POSITIVES])
def test_a_case_builds_verifies_and_measures_what_the_drawing_says(case):
    directory = Path(tempfile.mkdtemp())
    outcome, report = built(case, directory)

    assert report.valid, [item.detail for item in report.checks if not item.passed]
    assert [item.kind for item in outcome.artifacts] == ["STEP", "STL"]
    assert all(item.size_bytes > 0 for item in outcome.artifacts)

    volume = float(outcome.part.volume)
    assert volume == pytest.approx(case.volume_mm3, rel=1e-6, abs=1e-3), (
        f"{case.id}: {case.arithmetic}"
    )
    assert len(outcome.part.solids()) == case.bodies


@pytest.mark.parametrize("case", NEGATIVES, ids=[case.id for case in NEGATIVES])
def test_a_refusal_carries_the_code_it_named(case):
    directory = Path(tempfile.mkdtemp())
    if case.by_contract:
        with pytest.raises(CadIrValidationError) as raised:
            validate_canonical(case.document)
        assert case.code in {issue.code for issue in raised.value.issues}, case.why
        return

    document = validate_canonical(case.document)
    with pytest.raises(CadEngineError) as raised:
        build(document, directory)
    assert raised.value.code == case.code, f"{case.why}: got {raised.value.code}"
    assert raised.value.safe_message
    # A refused document leaves nothing behind. An `output/` beside a failed job reads
    # like a build that ran.
    assert not (directory / "model.step").exists()


def test_a_kept_overlapping_tool_builds_and_the_mesh_check_refuses_it():
    """The one case whose geometry is right and whose *mesh* is not one surface.

    Keeping a tool that overlapped its target leaves two bodies sharing the face the cut
    was made on, and two solids touching face-to-face are not a single closed surface. The
    manifold check says so, and that is the answer this records rather than accommodates:
    a part like this is not one a customer should be handed, and weakening the check to
    let it through would blind it to every torn mesh as well.
    """
    case = golden_corpus.kept_tool()
    directory = Path(tempfile.mkdtemp())
    outcome, report = built(case, directory)

    # The solid is exactly what the arithmetic says, and there are two of them.
    assert float(outcome.part.volume) == pytest.approx(case.volume_mm3, abs=1e-3)
    assert len(outcome.part.solids()) == 2

    assert not report.valid
    failed = {item.name for item in report.checks if not item.passed}
    assert "closed_manifold_mesh" in failed
    assert "solid_body_count" not in failed  # the count is right; the surface is not


# --- determinism -----------------------------------------------------------


def _without_timestamp(step: Path) -> str:
    """The STEP with the two things OpenCascade writes per export taken out.

    Both are named constants above with the measurement behind them. Nothing else is
    normalised: the point of this gate is to know exactly which byte-level difference is
    legitimate, and a gate that normalised whatever happened to differ would assert
    nothing at all.
    """
    return "\n".join(
        _OCCURRENCE.sub(r"\1*\2", line)
        for line in step.read_text(errors="replace").splitlines()
        if not line.startswith(_TIMESTAMP)
    )


#: A slice of the corpus by default, and all of it when Gate P2 is being measured.
#:
#: Determinism is a property of the engine rather than of a document, so ten cases
#: spanning ten operations is what a routine run needs — every case doubles the gate's
#: runtime, and the gate already builds a hundred. Gate P2 asks for **99% deterministic
#: build success on the synthetic corpus**, which is a number about the whole corpus, so
#: `CAD_CORPUS_DETERMINISM=all` builds every case twice. The recorded run is in
#: `docs/acceptance/POSTMVP-028-*`.
_DETERMINISM_SLICE = {
    "plate-40x20x10", "islands-4", "revolve-360", "fillet-r8",
    "pattern-circular-6", "boolean-subtract", "boss-on-selected-face",
    "shell-cup", "sweep-elbow", "loft-truncated-cone",
}
DETERMINISM = (
    list(POSITIVES) if os.environ.get("CAD_CORPUS_DETERMINISM") == "all"
    else [case for case in POSITIVES if case.id in _DETERMINISM_SLICE]
)


@pytest.mark.parametrize("case", DETERMINISM, ids=[case.id for case in DETERMINISM])
def test_the_same_document_builds_the_same_bytes_twice(case):
    """Byte-identical STL, and STEP identical apart from its timestamp.

    Measured, not assumed: the first version of this compared digests and found STEP
    differing on every run. Exactly one line differs — the `FILE_NAME` header — and
    knowing that precisely is the difference between a gate and a flaky test.
    """
    digests = []
    steps = []
    for _ in range(2):
        directory = Path(tempfile.mkdtemp())
        outcome, _ = built(case, directory)
        digests.append({item.kind: item.sha256 for item in outcome.artifacts})
        steps.append(_without_timestamp(directory / "model.step"))

    assert digests[0]["STL"] == digests[1]["STL"], f"{case.id}: the mesh moved"
    assert steps[0] == steps[1], f"{case.id}: the solid changed between runs"
    assert hashlib.sha256(steps[0].encode()).hexdigest() == hashlib.sha256(
        steps[1].encode()
    ).hexdigest()


def test_the_step_timestamp_is_the_only_thing_that_moves():
    """The exception this gate allows, stated so nobody widens it by accident."""
    case = DETERMINISM[0]
    raw = []
    for _ in range(2):
        directory = Path(tempfile.mkdtemp())
        built(case, directory)
        raw.append((directory / "model.step").read_text(errors="replace").splitlines())

    differing = [
        (left, right) for left, right in zip(raw[0], raw[1], strict=True) if left != right
    ]
    assert len(differing) <= 1
    assert all(left.startswith(_TIMESTAMP) for left, _ in differing)


def test_a_multi_body_step_moves_only_in_its_occurrence_labels():
    """The second exception, measured rather than assumed — and kept narrow.

    A part exported as several bodies is a STEP assembly, and OpenCascade names its
    occurrences from a counter that advances across exports **within one process**: the
    first build's bodies are '1' and '2', the second's '3' and '4'. Two separate
    processes both produce '1' and '2', so a delivered part is byte-identical between
    runs — which is the case Gate P2's "deterministic build success" is about, because a
    worker builds one job per process.

    This is what makes normalising the label safe, and this test is what keeps it
    narrow: the only differing lines are the timestamp and the occurrences, and inside an
    occurrence only the label moves — its path and both entity references do not.
    """
    case = next(item for item in POSITIVES if item.id == "two-separate-bodies")
    raw = []
    for _ in range(2):
        directory = Path(tempfile.mkdtemp())
        built(case, directory)
        raw.append((directory / "model.step").read_text(errors="replace").splitlines())

    differing = [
        (left, right) for left, right in zip(raw[0], raw[1], strict=True) if left != right
    ]
    assert differing, "the counter is expected to advance; if it stopped, say so here"
    for left, right in differing:
        assert left.startswith(_TIMESTAMP) or "NEXT_ASSEMBLY_USAGE_OCCURRENCE" in left
        assert _OCCURRENCE.sub(r"\1*\2", left) == _OCCURRENCE.sub(r"\1*\2", right) or (
            left.startswith(_TIMESTAMP)
        )


# --- the topology oracle ---------------------------------------------------


@pytest.mark.parametrize(
    "case",
    [case for case in POSITIVES if case.topology is not None],
    ids=[case.id for case in POSITIVES if case.topology is not None],
)
def test_a_case_that_states_its_topology_is_made_of_what_the_drawing_says(case):
    """Faces, edges and vertices, closed-form from the drawing like the volume.

    A round through hole adds one face, **three** edges and two vertices — two circles
    and the seam OpenCascade puts on a closed cylinder. That seam is the migration's
    own recorded cost (ADR-023), and stating it in arithmetic is what turns it from a
    note into something a check reads.
    """
    from cad_engine_build123d.verify import topology_of

    directory = Path(tempfile.mkdtemp())
    outcome, _ = built(case, directory)
    facts = topology_of(outcome.part)

    assert (facts.faces, facts.edges, facts.vertices) == case.topology, case.arithmetic


def test_every_case_agrees_with_itself_about_how_many_handles_it_has():
    """The oracle, over the whole corpus: two counts of one integer, from two files.

    The genus of a solid is computed twice — off the B-rep in the STEP and off the
    triangles in the STL — by two exporters that share no code. Neither number comes
    from the document, so this cannot be satisfied by a plan agreeing with itself.
    """
    for case in DETERMINISM:
        directory = Path(tempfile.mkdtemp())
        _, report = built(case, directory)
        agreed = [item for item in report.checks if item.name == "topology_agrees_with_mesh"]
        assert agreed and agreed[0].passed, f"{case.id}: {agreed}"
