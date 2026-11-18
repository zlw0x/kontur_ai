"""Editing must remain true when the exported files are reopened by the engine."""

import pytest

pytest.importorskip("build123d")

from app.projects.editor import (
    EditRefused,
    add_hole,
    edit_parameters,
    edit_text,
    enclosure,
)
from cad_engine_build123d.adapter import build
from cad_engine_build123d.verify import Expectations, verify
from cad_ir.canonical_validator import validate_canonical
from cad_ir_fixtures import fixture


def checked(value, directory):
    document = validate_canonical(value)
    outcome = build(document, directory)
    report = verify(
        directory / "model.step", directory / "model.stl", Expectations.of(document)
    )
    assert report.valid, report.as_dict()
    return outcome


def test_enclosure_survives_three_edits_hole_and_reopen(tmp_path):
    original = enclosure(120, 80, 40, 3)
    checked(original, tmp_path / "v1")
    current = edit_parameters(original, {"p_width": 140})
    checked(current, tmp_path / "v2")
    current = edit_text(current, "длина 90")
    checked(current, tmp_path / "v3")
    current = edit_text(current, "увеличь глубину на 10")
    checked(current, tmp_path / "v4")
    current = add_hole(current, 6, 0, 0)
    result = checked(current, tmp_path / "v5")
    assert result.part.bounding_box().size.X == pytest.approx(140)
    assert result.part.bounding_box().size.Y == pytest.approx(90)
    assert result.part.bounding_box().size.Z == pytest.approx(50)
    assert original["parameters"][0]["value"] == 120


def test_existing_rounded_enclosure_keeps_its_features_and_three_mounting_holes(
    tmp_path,
):
    original = fixture("enclosure")
    current = original
    for number, (parameter, size) in enumerate(
        (("p_width", 140), ("p_height", 90), ("p_depth", 50)), 1
    ):
        current = edit_parameters(current, {parameter: size})
        checked(current, tmp_path / f"edit-{number}")
    current = add_hole(current, 6, 0, 0)
    checked(current, tmp_path / "with-hole")
    assert [f["id"] for f in current["features"][:-1]] == [
        f["id"] for f in original["features"]
    ]
    assert (
        next(
            e["value"]
            for e in current["expectations"]
            if e["type"] == "through_hole_count"
        )
        == 3
    )


def test_hole_outside_the_body_fails_independent_geometry_check(tmp_path):
    with pytest.raises(EditRefused):
        add_hole(enclosure(120, 80, 40, 3), 6, 500, 0)
    value = add_hole(enclosure(120, 80, 40, 3), 6, 0, 0)
    # A second hole overlapping the first must not silently count as two.
    value = add_hole(value, 6, 0, 0)
    document = validate_canonical(value)
    build(document, tmp_path)
    report = verify(
        tmp_path / "model.step", tmp_path / "model.stl", Expectations.of(document)
    )
    assert not report.valid
