"""No source file names a CAD-IR version, and every fixture is reachable without one.

A fixture's filename carries the contract version, so a bump renames all of them. Until
now every test that opened one carried the version in its own source — nineteen files,
edited by hand or by text substitution on each of four bumps.

That is how the defect got in. Three of the container tests in
`packages/build123d-launcher` still named a version the previous bump had renamed away,
and nobody found out: those tests skip themselves unless `CAD_ENGINE_IMAGE` names an
image, and **a skip in the summary line looks exactly like a pass**. The suite reported
green while three of its tests could not have opened the file they asked for.

The fix is that the version lives in one place per language — `CAD_IR_VERSION` in the
contract, `CadIr.Version` in `CadAi.CadEngine` — and a caller asks for `plate`. This is
what keeps it that way: a version literal in any source file fails here, in a test that
always runs, rather than in one that might be skipped.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from cad_ir.canonical import CAD_IR_VERSION
from cad_ir_fixtures import DIRECTORY, fixture_path, names, suffix

ROOT = Path(__file__).parents[3]

#: The shape of a versioned fixture name, whatever the version happens to be.
VERSION_IN_A_NAME = re.compile(r"\bv\d+_\d+\b")

#: The other spelling, found the hard way on the 1.12 bump: a version inside a
#: *sentence* rather than inside a filename. `Assert.Contains("canonical CAD-IR 1.11",
#: compilation)` passed every bump until the prompt it checks started saying 1.12, and
#: the rule above could not see it because there is no `v1_11` in it.
#:
#: Matched only in CAD-IR's own context, because the bare number is not this project's
#: alone: a *capability* declares a version too, and `capability_version_tuple("1.11")`
#: is a different 1.11 that must keep saying so.
#:
#: And only the version **this build speaks**. An older one written down deliberately is
#: not a stale copy but a statement — a worker manifest declaring 0.1.0, a launcher test
#: proving an engine's own 1.7 is echoed back, a document refused for saying 1.5. Those
#: mean what they say and do not move when the contract does.
CAD_IR_CONTEXT = re.compile(r"cad[ _-]ir", re.IGNORECASE)


def version_in_a_sentence() -> re.Pattern[str]:
    return re.compile(r"""["'][^"']*""" + re.escape(CAD_IR_VERSION) + r"""[^"']*["']""")

#: Where source lives. Documentation is deliberately excluded: an acceptance record
#: saying "lever-plate.v1_7.json was built" is history, and history does not move.
SOURCE_SUFFIXES = (".py", ".cs", ".yml", ".yaml")

#: Directories with nothing hand-written in them.
IGNORED = {"node_modules", "bin", "obj", ".git", ".next", "__pycache__", ".venv"}

#: The files whose subject *is* the version, and which therefore have to be able to
#: write it down: the two declarations, the helper that turns one into a filename, and
#: this file. Everything else derives it from them.
ALLOWED = {
    Path("packages/cad-ir/cad_ir/canonical.py"),
    Path("packages/cad-engine-contracts/CadIr.cs"),
    Path("tests/cad_ir_fixtures.py"),
    Path("apps/api/tests/test_fixture_versions.py"),
}


def sources() -> list[Path]:
    found: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
            continue
        if IGNORED & set(path.relative_to(ROOT).parts):
            continue
        found.append(path)
    return found


def test_there_are_sources_to_check():
    """A scan that found nothing would pass every assertion below."""
    assert len(sources()) > 50


def test_no_source_file_writes_a_fixture_version_down():
    """The check that stops the habit coming back one call site at a time."""
    offenders: dict[str, list[str]] = {}
    for path in sources():
        relative = path.relative_to(ROOT)
        if relative in ALLOWED:
            continue
        hits = [
            f"{number}: {line.strip()}"
            for number, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
            )
            if VERSION_IN_A_NAME.search(line)
        ]
        if hits:
            offenders[str(relative)] = hits

    assert offenders == {}, (
        "these name a CAD-IR version instead of deriving it — Python should use "
        "`cad_ir_fixtures.fixture(name)`, .NET `CadIr.FileSuffix`: " + repr(offenders)
    )


def test_no_source_file_writes_a_cad_ir_version_into_a_string():
    """The spelling the rule above cannot see, and the one the 1.12 bump was caught by.

    A quoted string that carries a version *and* mentions CAD-IR on the same line is a
    copy of `CAD_IR_VERSION` — in a prompt assertion, in a worker manifest, in a
    fixture's `schema_version`. Comments are not scanned, because a sentence saying
    "CAD-IR 1.11 refuses a document that…" is history and history does not move.
    """
    current = version_in_a_sentence()
    offenders: dict[str, list[str]] = {}
    for path in sources():
        relative = path.relative_to(ROOT)
        if relative in ALLOWED:
            continue
        hits = []
        for number, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            stripped = line.lstrip()
            if stripped.startswith(("#", "//", "*", '"""', "'''")):
                continue
            if CAD_IR_CONTEXT.search(line) and current.search(line):
                hits.append(f"{number}: {line.strip()}")
        if hits:
            offenders[str(relative)] = hits

    assert offenders == {}, (
        "these state a CAD-IR version in a string instead of deriving it from "
        "`CAD_IR_VERSION` or `CadIr.Version`: " + repr(offenders)
    )


def test_the_suffix_is_the_contracts_own_version():
    assert suffix() == "v" + CAD_IR_VERSION.replace(".", "_")


def test_every_fixture_of_this_version_is_reachable_by_name():
    """The other direction: a fixture on disk that no name resolves to is unusable."""
    on_disk = {path.name for path in DIRECTORY.glob(f"*.{suffix()}.json")}
    assert on_disk, f"no fixtures at {suffix()} — did a bump rename them without the code?"
    # Compared as sets: `plate-with-hole` sorts before `plate` by filename and after it
    # by bare name, and the question here is reachability rather than order.
    assert on_disk == {fixture_path(name).name for name in names()}


def test_the_legacy_fixtures_are_left_out_of_the_versioned_set():
    """`plate.json` and `plate-with-hole.json` are 0.1.0 documents.

    They are what `test_cad_ir_normalizer.py` migrates *from*, so they carry no version
    and must not be swept into the current set by the glob.
    """
    legacy = {path.name for path in DIRECTORY.glob("*.json")} - {
        path.name for path in DIRECTORY.glob(f"*.{suffix()}.json")
    }
    assert legacy == {"plate.json", "plate-with-hole.json"}
    assert "plate" in names()  # the versioned one, which is a different document


@pytest.mark.parametrize("name", names())
def test_every_name_opens_a_document_of_the_declared_version(name):
    from cad_ir_fixtures import fixture

    assert fixture(name)["schema_version"] == CAD_IR_VERSION
