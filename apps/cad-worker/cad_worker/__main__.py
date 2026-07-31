"""The CAD worker: one job in, STEP and STL out.

    python -m cad_worker build --job /work/job-123 [--disable KEY ...]
    python -m cad_worker describe [--disable KEY ...]

A job directory has `cad-ir.json` in it and gets an `output/` written beside it.
Nothing else is read and nothing outside it is written.

This process is deliberately small. It takes a document, validates it, builds it
and writes two files; it has no network, no shell, and no way to be told to run
anything. The scheduling, the leases and the retries stay where they are — a CAD
worker that also talked to the API would be a second place for both to go wrong.

**Feature flags arrive on the command line, and nowhere else.** ADR-021 puts a
rollback switch on the worker rather than on the server, because the thing that
has to stop is the thing that drives the kernel and it has to stop even when the
server cannot be reached to say so. This process is not that worker: it is a
container with a read-only root, started per job, with nothing durable to store a
flag in. The worker that launches it holds the flag file and passes the keys
down, and `describe` applies the same keys to the manifest it publishes — so the
statuses the API schedules against and the gate the build actually enforces come
from one place.

An unknown key is refused rather than ignored. A typo in a rollback switch must
not leave an operator believing an operation is off while it runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cad_engine_build123d import CadEngineError, build, describe
from cad_engine_build123d.capabilities import CapabilityGate
# Imported from the module rather than the package: a submodule named erify` and
# a function named `verify` cannot both live in one namespace, and the one that
# wins is whichever was imported last.
from cad_engine_build123d.verify import Expectations, verify
from cad_ir.canonical_validator import validate_canonical

#: A document larger than this is not a plate with holes in it. Bounded before
#: parsing rather than after, because the cost of a huge document is paid in the
#: parser.
MAX_CAD_IR_BYTES = 1_048_576


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cad_worker", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    build_command = commands.add_parser("build", help="build one job directory")
    build_command.add_argument("--job", required=True, help="the job directory")
    _add_flags(build_command)

    _add_flags(commands.add_parser("describe", help="print what this engine is and does"))

    arguments = parser.parse_args(argv)
    try:
        gate = CapabilityGate.disabling(arguments.disable)
    except CadEngineError as error:
        # Before anything else, and on both commands. A manifest published with
        # a flag the engine did not understand would advertise the wrong thing.
        print(json.dumps(_failure(error)))
        return 1

    if arguments.command == "describe":
        print(json.dumps(describe(gate).as_dict(), indent=2))
        return 0
    return _build(Path(arguments.job), gate)


def _add_flags(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--disable",
        action="append",
        default=[],
        metavar="CAPABILITY",
        help="turn one operation off for this run; repeatable",
    )


def _build(job: Path, gate: CapabilityGate) -> int:
    try:
        document = _read_document(job)
        outcome = build(document, job / "output", gate)
        # Reopened by a reader that did not build them. A successful export is
        # not evidence that the model is right, and the expectations come from
        # the document rather than from the plan that produced the geometry.
        report = verify(
            job / "output" / "model.step",
            job / "output" / "model.stl",
            Expectations.of(document),
        )
        (job / "output" / "validation-report.json").write_text(
            json.dumps(report.as_dict(), indent=2), encoding="utf-8"
        )
        if not report.valid:
            failed = [item for item in report.checks if not item.passed]
            raise CadEngineError(
                "GEOMETRY_VALIDATION_FAILED",
                "validation",
                "; ".join(f"{item.name}: {item.detail}" for item in failed),
            )
    except CadEngineError as error:
        print(json.dumps(_failure(error)))
        return 1

    print(
        json.dumps(
            {
                "status": "COMPLETED",
                "engine": outcome.engine.as_dict(),
                # Echoed back so the caller can see the flags it meant to pass
                # actually arrived. A launcher that dropped one would otherwise
                # produce a perfectly successful build of something an operator
                # had turned off.
                "disabled_capabilities": sorted(gate.disabled),
                "verified": report.valid,
                "artifacts": [
                    {
                        "kind": artifact.kind,
                        "file": artifact.path.name,
                        "size_bytes": artifact.size_bytes,
                        "sha256": artifact.sha256,
                    }
                    for artifact in outcome.artifacts
                ],
            },
            indent=2,
        )
    )
    return 0


def _failure(error: CadEngineError) -> dict:
    """A typed failure, on stdout as JSON, because the caller is a program.

    The message describes the document and never the machine.
    """
    return {
        "status": "FAILED",
        "code": error.code,
        "stage": error.stage,
        "message": error.safe_message,
    }


def _read_document(job: Path):
    path = job / "cad-ir.json"
    if not path.is_file():
        raise CadEngineError(
            "CAD_IR_MISSING", "prepare", f"No cad-ir.json in {job.name}."
        )
    if path.stat().st_size > MAX_CAD_IR_BYTES:
        raise CadEngineError(
            "CAD_IR_TOO_LARGE",
            "prepare",
            f"cad-ir.json is larger than {MAX_CAD_IR_BYTES} bytes.",
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise CadEngineError(
            "CAD_IR_INVALID", "prepare", f"cad-ir.json is not valid JSON: {error}"
        ) from error
    try:
        # The same validator the API uses. The engine does not get its own
        # opinion of what a valid document is: two validators that disagree is
        # how a document becomes buildable on one side of a boundary and not the
        # other.
        return validate_canonical(value)
    except Exception as error:  # noqa: BLE001 - the validator raises its own types
        raise CadEngineError("CAD_IR_INVALID", "prepare", str(error)) from error


if __name__ == "__main__":
    sys.exit(main())
