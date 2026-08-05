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
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .policy import POLICY, InputPolicy
from .quarantine import InputRejected, QuarantinedFile


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
    ) -> None:
        self.policy, self.image = policy, image
        self.python = python or sys.executable

    def sanitize(self, quarantined: QuarantinedFile, workspace: Path) -> SanitizedDrawing:
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
                env={"PYTHONPATH": _sanitizer_path(), "PYTHONDONTWRITEBYTECODE": "1"},
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


__all__ = ["SanitizedDrawing", "Sanitizer", "SanitizerUnavailable"]
