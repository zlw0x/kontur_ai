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

    # Four keys belong to a hand-written fixture instead, each for a reason. They are
    # covered — by `test_constraints.py`, `test_revolve.py` and `test_blends.py` — and
    # listing them here is what stops the exemption from growing quietly.
    elsewhere = {
        caps.SKETCH_CONSTRAINTS,          # constrained-plate (POSTMVP-007): assertions
        caps.SKETCH_DIMENSIONS,           # about coordinates, which change no geometry
        caps.CUT_REVOLVE,                 # bushing: a turned relief groove
        caps.FEATURE_CHAMFER_ASYMMETRIC,  # blended-bracket: a countersink
    }
    missing = set(caps.ALL) - elsewhere - exercised
    assert missing == set(), sorted(missing)


def test_there_are_enough_cases_to_be_called_a_corpus():
    """The roadmap's bar for promoting an operation: ten positive and ten negative."""
    assert len(POSITIVES) >= 10
    assert len(NEGATIVES) >= 10
    assert len({case.id for case in POSITIVES}) == len(POSITIVES)
    assert len({case.id for case in NEGATIVES}) == len(NEGATIVES)


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
    return "\n".join(
        line for line in step.read_text(errors="replace").splitlines()
        if not line.startswith(_TIMESTAMP)
    )


#: A slice of the corpus, not all of it: determinism is a property of the engine rather
#: than of a document, and every case doubles the gate's runtime.
DETERMINISM = [
    case for case in POSITIVES
    if case.id in {
        "plate-40x20x10", "islands-4", "revolve-360", "fillet-r8",
        "pattern-circular-6", "boolean-subtract", "boss-on-selected-face",
        "shell-cup",
    }
]


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
