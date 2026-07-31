"""The worker's command line is a program's interface, not a person's.

Everything it prints is JSON on stdout and everything it refuses carries a code
and a stage, because the caller is the worker that holds the lease and it has to
decide what to do next. A process that failed with prose on stderr would leave
that decision to a regular expression.

These exercise `main` in-process rather than by spawning a subprocess. The thing
worth testing is the contract — what is printed and what is returned — and
spawning would only add an interpreter start to every case.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

pytest.importorskip("build123d", reason="the CAD engine is not installed")

from cad_worker.__main__ import main  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "cad-ir"


def run(capsys, *argv: str) -> tuple[int, dict]:
    code = main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def job(tmp_path: Path, fixture: str) -> Path:
    directory = tmp_path / "job"
    directory.mkdir()
    shutil.copyfile(FIXTURES / fixture, directory / "cad-ir.json")
    return directory


# --- describe --------------------------------------------------------------


def test_describe_states_the_engine_and_everything_it_builds(capsys):
    code, described = run(capsys, "describe")
    assert code == 0
    assert described["engine_id"] == "build123d"
    assert described["cad_ir_version"] == "1.4"
    assert [item["kind"] for item in described["artifacts"]] == ["STEP", "STL"]
    # No M3D, from the engine that no longer produces one (ADR-023).
    assert "M3D" not in {item["kind"] for item in described["artifacts"]}
    assert described["capabilities"]["sketch.arc"]["status"] == "beta"


def test_describe_applies_the_same_flags_the_build_will(capsys):
    """The manifest and the gate come from one call.

    Publishing a capability as available and then refusing it at build time is
    the failure this shares a code path to avoid.
    """
    code, described = run(capsys, "describe", "--disable", "sketch.slot")
    assert code == 0
    assert described["capabilities"]["sketch.slot"]["status"] == "disabled"
    assert described["capabilities"]["sketch.arc"]["status"] == "beta"


@pytest.mark.parametrize("command", [("describe",), ("build", "--job", "unused")])
def test_an_unknown_flag_fails_before_anything_else(capsys, command):
    """On both commands, and before the job directory is even looked at.

    A manifest published with a key the engine did not understand would advertise
    the wrong thing, and a build that ignored one would run an operation an
    operator believes is off.
    """
    code, failure = run(capsys, *command, "--disable", "sketch.ark")
    assert code == 1
    assert failure["code"] == "CAPABILITY_UNKNOWN"
    assert failure["stage"] == "prepare"
    assert "sketch.ark" in failure["message"]


# --- build -----------------------------------------------------------------


def test_a_fixture_builds_and_the_flags_of_the_run_are_echoed_back(capsys, tmp_path):
    """Echoed so a launcher that dropped a flag is visible.

    Without it, a worker that meant to disable an operation and failed to pass
    the key would produce a perfectly successful build of exactly the thing it
    was trying to stop.
    """
    directory = job(tmp_path, "plate.v1_4.json")
    code, result = run(capsys, "build", "--job", str(directory))
    assert code == 0
    assert result["status"] == "COMPLETED"
    assert result["verified"] is True
    assert result["disabled_capabilities"] == []
    assert [item["kind"] for item in result["artifacts"]] == ["STEP", "STL"]
    assert (directory / "output" / "validation-report.json").is_file()


def test_a_disabled_operation_stops_the_build_before_any_file_is_written(
    capsys, tmp_path
):
    directory = job(tmp_path, "lever-plate.v1_4.json")
    code, failure = run(capsys, "build", "--job", str(directory), "--disable", "sketch.arc")
    assert code == 1
    assert failure["code"] == "CAPABILITY_DISABLED"
    assert failure["stage"] == "cad-ir"
    assert "sketch.arc" in failure["message"]
    assert not (directory / "output").exists()


def test_turning_off_an_operation_the_document_does_not_use_does_not_stop_it(
    capsys, tmp_path
):
    directory = job(tmp_path, "plate.v1_4.json")
    code, result = run(capsys, "build", "--job", str(directory), "--disable", "sketch.slot")
    assert code == 0
    assert result["disabled_capabilities"] == ["sketch.slot"]


def test_a_revolve_builds_even_though_it_is_declared_experimental(capsys, tmp_path):
    """Maturity is what the API schedules on; it is not a gate in the engine.

    Conflating the two would make `experimental` mean "refuses to run", and then
    nothing could ever be exercised into being beta.
    """
    directory = job(tmp_path, "bushing.v1_4.json")
    code, result = run(capsys, "build", "--job", str(directory))
    assert code == 0
    assert result["status"] == "COMPLETED"


# --- what it refuses to read -----------------------------------------------


def test_a_job_with_no_document_is_a_typed_failure(capsys, tmp_path):
    directory = tmp_path / "job"
    directory.mkdir()
    code, failure = run(capsys, "build", "--job", str(directory))
    assert code == 1
    assert failure["code"] == "CAD_IR_MISSING"


def test_a_document_that_is_not_json_is_a_typed_failure(capsys, tmp_path):
    directory = tmp_path / "job"
    directory.mkdir()
    (directory / "cad-ir.json").write_text("{not json", encoding="utf-8")
    code, failure = run(capsys, "build", "--job", str(directory))
    assert code == 1
    assert failure["code"] == "CAD_IR_INVALID"


def test_a_document_too_large_to_be_a_part_is_refused_before_parsing(capsys, tmp_path):
    """Bounded before parsing, because the cost of a huge document is paid there."""
    directory = tmp_path / "job"
    directory.mkdir()
    (directory / "cad-ir.json").write_text(" " * 1_048_577, encoding="utf-8")
    code, failure = run(capsys, "build", "--job", str(directory))
    assert code == 1
    assert failure["code"] == "CAD_IR_TOO_LARGE"


def test_a_document_of_an_older_version_is_refused_rather_than_migrated(capsys, tmp_path):
    """The engine does not normalise.

    Migration belongs to the API, which keeps the original as an artifact and
    records the lineage. An engine that also migrated would be a second
    implementation of a translation whose output nothing would compare.
    """
    directory = tmp_path / "job"
    directory.mkdir()
    value = json.loads((FIXTURES / "plate.v1_4.json").read_text("utf-8"))
    value["schema_version"] = "1.3"
    (directory / "cad-ir.json").write_text(json.dumps(value), encoding="utf-8")
    code, failure = run(capsys, "build", "--job", str(directory))
    assert code == 1
    assert failure["code"] == "CAD_IR_INVALID"
