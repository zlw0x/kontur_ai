"""The CAD worker: one job in, STEP and STL out.

    python -m cad_worker build --job /work/job-123
    python -m cad_worker describe

A job directory has `cad-ir.json` in it and gets an `output/` written beside it.
Nothing else is read and nothing outside it is written.

This process is deliberately small. It takes a document, validates it, builds it
and writes two files; it has no network, no shell, and no way to be told to run
anything. The scheduling, the leases and the retries stay where they already are
(ENGINE-MIG-007) — a CAD worker that also talked to the API would be a second
place for both to go wrong.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cad_engine_build123d import CadEngineError, build, describe
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

    commands.add_parser("describe", help="print what this engine is and produces")

    arguments = parser.parse_args(argv)
    if arguments.command == "describe":
        print(json.dumps(describe().as_dict(), indent=2))
        return 0
    return _build(Path(arguments.job))


def _build(job: Path) -> int:
    try:
        document = _read_document(job)
        outcome = build(document, job / "output")
    except CadEngineError as error:
        # A typed failure, on stdout as JSON, because the caller is a program.
        # The message describes the document and never the machine.
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "code": error.code,
                    "stage": error.stage,
                    "message": error.safe_message,
                }
            )
        )
        return 1

    print(
        json.dumps(
            {
                "status": "COMPLETED",
                "engine": outcome.engine.as_dict(),
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
