"""Run the sanitizer somewhere the API is not, and believe only its answer.

The same shape as the CAD engine's launcher, and for the same reason: the risky
work happens in a process that owns nothing, and this side checks what comes back
rather than trusting it. What differs is which way the danger points — the CAD
engine is *our* code given a validated document, and the sanitizer is a decoder
given bytes a stranger chose.

Three levels, weakest last, so a machine that cannot run the strongest still runs
one of them:

    container   the addendum's requirement — no network, read-only root,
                unprivileged, cap-drop ALL, one bind mount, memory/CPU/PID caps
    process     a child with `RLIMIT_AS` and `RLIMIT_CPU` and a wall clock, which
                is what runs when no image is configured
    (never)     in the API. There is no third mode: a decoder in this process is
                the thing the whole package exists to prevent.

The wall clock is here rather than in the child because a child that has stopped
responding cannot enforce its own timeout. `RLIMIT_CPU` catches a busy loop; a
decoder blocked on something catches nothing, and this kills it.

`RLIMIT_AS` and `RLIMIT_CPU` are POSIX, and the process mode runs on whatever
machine the API is on — which for an operator is Windows. So the process mode has
a fourth state nobody had named: a child that starts, decodes, and is confined by
nothing but the wall clock. It is not refused outright, because a laptop that
cannot run Docker still has to be able to run the service; it is refused **outside
the `local` environment**, where an operator has a container to configure and a
stranger's bytes to keep out of the kernel we share with the database.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .policy import POLICY, InputPolicy
from .quarantine import InputRejected, QuarantinedFile

#: What the child says it enforced. Mirrors `image_sanitizer.__main__`, which is a
#: separate package by design and is not imported here — this side is meant to
#: believe the answer only after checking it, and a shared constant would not
#: change that.
LIMITS_RLIMIT = "rlimit"

#: Whether *this* machine can give a child process kernel-enforced ceilings.
#:
#: Asked of the platform rather than of the child, because the answer has to be
#: known before a stranger's file is handed to a decoder. In the container mode it
#: says nothing useful — the image is Linux however the host is built — so it is
#: consulted only for the process mode.
KERNEL_LIMITS_AVAILABLE = importlib.util.find_spec("resource") is not None


@dataclass(frozen=True)
class SanitizedDrawing:
    """A page the pipeline may use, and the record of where it came from."""

    png: bytes
    width: int
    height: int
    source_format: str
    source_sha256: str
    source_bytes: int
    policy_version: str

    def manifest(self) -> dict:
        """The immutable record §5 requires. Hash, size, policy and result."""
        import hashlib

        return {
            "policy_version": self.policy_version,
            "source_sha256": self.source_sha256,
            "source_bytes": self.source_bytes,
            "source_format": self.source_format,
            "sanitized_sha256": hashlib.sha256(self.png).hexdigest(),
            "sanitized_bytes": len(self.png),
            "width": self.width,
            "height": self.height,
        }


class Sanitizer:
    """Runs `image_sanitizer` out of process and reads one JSON line back."""

    def __init__(
        self,
        policy: InputPolicy = POLICY,
        image: str | None = None,
        python: str | None = None,
        allow_unconfined_process: bool = False,
    ) -> None:
        self.policy, self.image = policy, image
        self.python = python or sys.executable
        #: Whether a child with no kernel ceilings may decode a stranger's file.
        #:
        #: Off by default, so a deployment that forgets to think about it gets the
        #: safe answer. `app.main` turns it on for the `local` environment only —
        #: the same shape as `reject_development_secrets_outside_local`, and for the
        #: same reason: the thing that must not escape a laptop is the laptop's
        #: convenience.
        self.allow_unconfined_process = allow_unconfined_process

    def sanitize(self, quarantined: QuarantinedFile, workspace: Path) -> SanitizedDrawing:
        if not self.image and not KERNEL_LIMITS_AVAILABLE and not self.allow_unconfined_process:
            # Before the file is handed over, not after. About the machine rather
            # than the drawing, so the customer is told to come back rather than
            # told their drawing is wrong.
            raise SanitizerUnavailable(
                "this platform has no RLIMIT_AS or RLIMIT_CPU, so the process mode "
                "cannot confine a decoder; configure sanitizer_image"
            )
        workspace.mkdir(parents=True, exist_ok=True)
        output = workspace / "page-001.png"
        command = self._command(quarantined.path, output)
        try:
            finished = subprocess.run(  # noqa: S603 - a fixed argv, no shell
                command,
                capture_output=True,
                text=True,
                timeout=self.policy.page_timeout_seconds,
                # The child gets no environment of ours. A decoder does not need
                # our database URL, our tokens or our PATH, and the cheapest way to
                # be sure it never reads them is not to hand them over.
                #
                # Which is why the import path is *computed* rather than inherited.
                # An empty environment also drops the variables an interpreter uses
                # to find its own third-party packages — `APPDATA` on Windows, `HOME`
                # on POSIX — so a Pillow installed into the user site becomes
                # invisible and the child dies with `ModuleNotFoundError` and an
                # empty stdout, which this side can only report as "the sanitizer
                # said nothing readable". Naming the directories keeps the
                # environment empty and the answer the same on every machine.
                env={"PYTHONPATH": _import_path(), "PYTHONDONTWRITEBYTECODE": "1"},
            )
        except subprocess.TimeoutExpired as expired:
            raise InputRejected(
                "INPUT_DECODE_TIMEOUT",
                f"The drawing took longer than {self.policy.page_timeout_seconds:g} seconds "
                "to read, which a drawing does not.",
            ) from expired
        except FileNotFoundError as missing:
            # The machine, not the file. A customer must not be told their drawing
            # is wrong because an operator has not installed the sanitizer.
            raise SanitizerUnavailable(str(missing)) from missing

        answer = _one_json_line(finished.stdout)
        if answer is None:
            raise SanitizerUnavailable(
                f"the sanitizer said nothing readable (exit {finished.returncode})"
            )
        # Checked before the verdict is read, because it is not a fact about the
        # drawing: a decode that happened with no ceilings happened with no ceilings
        # whether the decoder liked what it found or not. Compared rather than
        # assumed, the way the CAD launcher compares the engine's digests against
        # the bytes on disk — the check above asked the platform, and this asks the
        # process that actually ran.
        if answer.get("limits") != LIMITS_RLIMIT and not self.allow_unconfined_process:
            raise SanitizerUnavailable(
                f"the sanitizer decoded with limits={answer.get('limits')!r}, "
                f"where {LIMITS_RLIMIT!r} was required"
            )
        if not answer.get("ok"):
            raise InputRejected(
                str(answer.get("code", "INPUT_DECODE_FAILED")),
                str(answer.get("message", "The image could not be read.")),
            )
        if not output.exists():
            raise SanitizerUnavailable("the sanitizer reported success and wrote nothing")

        png = output.read_bytes()
        # Believed only after it is measured, the way the launcher compares the
        # engine's digests against the bytes on disk. A sanitizer that reported one
        # size and wrote another is a sanitizer to stop trusting.
        if len(png) != int(answer.get("bytes", -1)):
            raise SanitizerUnavailable("the sanitizer's page is not the size it reported")
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise SanitizerUnavailable("the sanitizer's page is not a PNG")
        return SanitizedDrawing(
            png=png,
            width=int(answer["width"]),
            height=int(answer["height"]),
            source_format=str(answer.get("source_format", "UNKNOWN")),
            source_sha256=quarantined.sha256,
            source_bytes=quarantined.size_bytes,
            policy_version=self.policy.version,
        )

    def _command(self, source: Path, output: Path) -> list[str]:
        limits = [
            "--max-width", str(self.policy.max_width),
            "--max-height", str(self.policy.max_height),
            "--max-pixels", str(self.policy.max_pixels),
            "--max-frames", str(self.policy.max_frames),
            "--max-output-bytes", str(self.policy.max_sanitized_bytes),
            "--memory-bytes", str(self.policy.memory_bytes),
            "--cpu-seconds", str(self.policy.cpu_seconds),
        ]
        if self.image:
            return [
                "docker", "run", "--rm",
                "--network", "none",
                "--read-only",
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                "--memory", str(self.policy.memory_bytes),
                "--memory-swap", str(self.policy.memory_bytes),
                "--cpus", "2",
                "--pids-limit", "64",
                "--user", "65534:65534",
                "-v", f"{source.parent}:/in:ro",
                "-v", f"{output.parent}:/out",
                self.image,
                "--source", f"/in/{source.name}", "--output", f"/out/{output.name}", *limits,
            ]
        return [
            self.python, "-m", "image_sanitizer",
            "--source", str(source), "--output", str(output), *limits,
        ]


class SanitizerUnavailable(Exception):
    """The sanitizer could not answer. About the machine, never about the drawing.

    Kept apart from `InputRejected` for the reason `BuildFeedback` keeps the two
    apart: telling a customer their drawing is malformed because an operator has
    not installed a decoder is a lie the service would repeat every time.
    """


def _one_json_line(stdout: str) -> dict | None:
    for line in reversed(stdout.strip().splitlines()):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


def _sanitizer_path() -> str:
    """Where `image_sanitizer` lives when it is run as a sibling package.

    Only for the process mode. In the container it is installed, and this is not
    consulted.
    """
    return str(Path(__file__).resolve().parents[4] / "packages" / "image-sanitizer")


def _import_path() -> str:
    """The sanitizer, and the directories its dependencies were installed into.

    Every one of them belongs to the interpreter this side is running on, so nothing
    here widens what the child can reach — it is the same code the same interpreter
    would import anyway. What it removes is the child's dependence on *environment*
    to find it, which is the part the empty environment took away.

    Deliberately not `sys.path`: that carries the API's own working directory and
    every path a test runner injected, and the child has no business importing this
    service's modules.
    """
    import site

    directories = [_sanitizer_path()]
    for found in (getattr(site, "getsitepackages", list)(), [site.getusersitepackages()]):
        directories.extend(str(entry) for entry in found if entry)
    # Order preserved, duplicates dropped: `getsitepackages` and the user site can
    # name the same directory, and a repeated entry is a repeated stat per import.
    return os.pathsep.join(dict.fromkeys(directories))


__all__ = ["SanitizedDrawing", "Sanitizer", "SanitizerUnavailable"]
