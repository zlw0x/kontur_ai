"""Where an uploaded drawing lands, and what is known about it before anything reads it.

Three things this replaces, all in one line of the old handler:

    payload = await request.body()

**It read the whole upload into memory before checking anything.** A 25 MiB limit
enforced after the read is not a limit; it is a description of what already
happened. Bytes are counted as they arrive here, and the read stops at the limit
rather than reporting it afterwards.

**It trusted `Content-Length`.** Which is a claim, and is absent altogether under
chunked transfer. It is still used — as a fast pre-filter, so an obvious refusal
costs nothing — and the accepted size is the count of bytes actually read.

**It stored the raw file where the pipeline reads from.** The addendum's central
invariant is that the worker, Codex and the browser see only sanitized pages, and
the raw upload never crosses that line. Quarantine is a directory nothing else
opens, keyed by a server-side UUID: the customer's filename never becomes a path,
because a filename is attacker-controlled and a path is not a place to find that
out.

The state machine is the addendum's §5, minus the states this stage cannot reach:
a file is QUARANTINED once it is written and hashed, and what happens next belongs
to the sanitizer.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4

from .policy import ACCEPTED_MEDIA_TYPES, POLICY, SIGNATURES, InputPolicy


class InputState(StrEnum):
    QUARANTINED = "QUARANTINED"
    SANITIZING = "SANITIZING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    DELETED = "DELETED"


class InputRejected(Exception):
    """The upload is refused, with a typed code and text safe to show a customer."""

    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code, self.message, self.status_code = code, message, status_code


@dataclass(frozen=True)
class QuarantinedFile:
    file_id: UUID
    path: Path
    media_type: str
    extension: str
    size_bytes: int
    sha256: str
    state: InputState = InputState.QUARANTINED


class Quarantine:
    """Private storage for uploads that nothing has looked at yet."""

    def __init__(self, root: Path, policy: InputPolicy = POLICY) -> None:
        self.root, self.policy = Path(root), policy
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, file_id: UUID) -> Path:
        return self.root / str(file_id)

    async def accept(self, stream, media_type: str | None, declared_length: int | None = None):
        """Read an upload into quarantine, or refuse it before it is all here.

        `stream` yields chunks — `Request.stream()` in the API, an iterable in tests.
        Nothing about the file is believed: the media type is matched against the
        admitted list, the declared length is a hint, and the signature is checked
        against the bytes that actually arrived.
        """
        extension = ACCEPTED_MEDIA_TYPES.get((media_type or "").split(";", 1)[0].strip().lower())
        if extension is None:
            raise InputRejected(
                "INPUT_MEDIA_TYPE_UNSUPPORTED",
                "A drawing must be a PNG or a JPEG.",
                status_code=415,
            )
        if declared_length is not None and declared_length > self.policy.max_upload_bytes:
            # A pre-filter only. Refusing here saves reading a file we would refuse
            # anyway; believing it would let a lying header through.
            raise InputRejected(
                "INPUT_TOO_LARGE",
                f"A drawing must be under {self.policy.max_upload_bytes // (1024 * 1024)} MiB.",
                status_code=413,
            )

        file_id = uuid4()
        path = self.path_for(file_id)
        digest, size, head = hashlib.sha256(), 0, b""
        try:
            with path.open("wb") as sink:
                async for chunk in _aiter(stream):
                    size += len(chunk)
                    if size > self.policy.max_upload_bytes:
                        # Stop reading. The rest of the body is never written and
                        # never hashed, which is the difference between a limit and
                        # a measurement.
                        raise InputRejected(
                            "INPUT_TOO_LARGE",
                            f"A drawing must be under "
                            f"{self.policy.max_upload_bytes // (1024 * 1024)} MiB.",
                            status_code=413,
                        )
                    if len(head) < 16:
                        head += chunk[: 16 - len(head)]
                    digest.update(chunk)
                    sink.write(chunk)
        except InputRejected:
            path.unlink(missing_ok=True)
            raise
        except Exception:
            path.unlink(missing_ok=True)
            raise

        if size == 0:
            path.unlink(missing_ok=True)
            raise InputRejected("INPUT_EMPTY", "The upload was empty.")
        if not any(head.startswith(signature) for signature in SIGNATURES[extension]):
            path.unlink(missing_ok=True)
            raise InputRejected(
                "INPUT_SIGNATURE_MISMATCH",
                "The file's contents are not the format its type claims.",
            )
        return QuarantinedFile(
            file_id=file_id,
            path=path,
            media_type=(media_type or "").split(";", 1)[0].strip().lower(),
            extension=extension,
            size_bytes=size,
            sha256=digest.hexdigest(),
        )

    def discard(self, file_id: UUID) -> None:
        """Delete a quarantined file. Called once the sanitizer has answered.

        The addendum gives raw uploads one hour at the outside and says to delete
        them as soon as processing ends. Neither the worker nor Codex nor the
        browser can reach this directory, so what is left here is only a window,
        and a window is worth closing.
        """
        self.path_for(file_id).unlink(missing_ok=True)

    def empty(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)


async def _aiter(stream):
    """Accept an async stream or a plain iterable, so a test needs no server."""
    if hasattr(stream, "__aiter__"):
        async for chunk in stream:
            yield chunk
        return
    for chunk in stream:
        yield chunk


__all__ = ["InputRejected", "InputState", "Quarantine", "QuarantinedFile"]
