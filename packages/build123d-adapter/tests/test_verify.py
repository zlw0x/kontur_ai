"""A successful export is not evidence that the model is right.

These exercise the half of the verifier that reads the mesh, which is
deliberately written against the file rather than through the CAD library: a
reader that shares code with the writer agrees with it about anything they both
get wrong. That is also why they need no CAD library to run.
"""

import struct

import pytest

from cad_engine_build123d.verify import Expectations, _parse_stl, _read_stl


def binary_stl(triangles) -> bytes:
    payload = b"\0" * 80 + struct.pack("<I", len(triangles))
    for triangle in triangles:
        payload += struct.pack("<3f", 0.0, 0.0, 1.0)
        for point in triangle:
            payload += struct.pack("<3f", *point)
        payload += struct.pack("<H", 0)
    return payload


def tetrahedron():
    """The smallest closed, consistently wound surface there is."""
    a, b, c, d = (0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)
    return [(a, c, b), (a, b, d), (a, d, c), (b, c, d)]


def report_for(payload: bytes, tmp_path, expectations=Expectations()):
    path = tmp_path / "model.stl"
    path.write_bytes(payload)
    checks: list = []
    mesh = _read_stl(path, checks, expectations)
    return {item.name: item for item in checks}, mesh


def test_a_closed_mesh_passes_every_structural_check(tmp_path):
    checks, mesh = report_for(binary_stl(tetrahedron()), tmp_path)

    assert checks["stl_structure"].passed
    assert checks["closed_manifold_mesh"].passed
    assert checks["consistent_normals"].passed
    assert checks["finite_non_degenerate_triangles"].passed
    assert mesh.triangles == 4
    assert mesh.vertices == 4


def test_a_mesh_with_a_missing_face_is_not_watertight(tmp_path):
    """What a printer sees as a hole. Three of the four faces leave three edges
    with only one triangle each."""
    checks, _ = report_for(binary_stl(tetrahedron()[:3]), tmp_path)

    assert not checks["closed_manifold_mesh"].passed
    assert "3 edges" in checks["closed_manifold_mesh"].detail


def test_a_face_wound_the_wrong_way_is_caught_even_though_the_mesh_is_closed(tmp_path):
    """The subtler failure: every edge still has two triangles, but two of them
    disagree about which side is out."""
    triangles = tetrahedron()
    first = triangles[0]
    triangles[0] = (first[0], first[2], first[1])  # reversed

    checks, _ = report_for(binary_stl(triangles), tmp_path)

    assert checks["closed_manifold_mesh"].passed
    assert not checks["consistent_normals"].passed


def test_a_zero_area_triangle_is_degenerate(tmp_path):
    flat = [((0, 0, 0), (1, 0, 0), (2, 0, 0))]

    checks, _ = report_for(binary_stl(flat), tmp_path)

    assert not checks["finite_non_degenerate_triangles"].passed


def test_a_header_that_disagrees_with_the_file_length_is_refused(tmp_path):
    payload = bytearray(binary_stl(tetrahedron()))
    struct.pack_into("<I", payload, 80, 99)

    checks, mesh = report_for(bytes(payload), tmp_path)

    assert not checks["stl_structure"].passed
    assert mesh is None


def test_an_ascii_mesh_is_read_as_well_as_a_binary_one():
    ascii_stl = b"""solid part
  facet normal 0 0 1
    outer loop
      vertex 0 0 0
      vertex 1 0 0
      vertex 0 1 0
    endloop
  endfacet
endsolid part
"""
    assert len(_parse_stl(ascii_stl)) == 1


def test_a_truncated_ascii_triangle_is_refused():
    with pytest.raises(ValueError, match="part-way through"):
        _parse_stl(b"solid p\n facet normal 0 0 1\n vertex 0 0 0\n vertex 1 0 0\n")


def test_the_through_hole_count_comes_from_the_mesh_genus(tmp_path):
    """A closed surface with no handles is genus 0, whatever else it is.

    The count is derived from Euler's formula on the triangulation rather than
    from the B-rep, where a full circle is one edge with one vertex and the
    formula answers 0 for a plate that plainly has a hole in it.
    """
    checks, mesh = report_for(
        binary_stl(tetrahedron()), tmp_path, Expectations(through_hole_count=0)
    )

    assert checks["through_hole_count"].passed
    assert mesh.genus == 0


def test_a_document_expecting_a_hole_in_a_solid_lump_is_refused(tmp_path):
    checks, _ = report_for(
        binary_stl(tetrahedron()), tmp_path, Expectations(through_hole_count=1)
    )

    assert not checks["through_hole_count"].passed
    assert "expected 1" in checks["through_hole_count"].detail


def test_an_empty_file_is_reported_rather_than_parsed(tmp_path):
    checks, mesh = report_for(b"", tmp_path)

    assert not checks["stl_readable"].passed
    assert mesh is None
