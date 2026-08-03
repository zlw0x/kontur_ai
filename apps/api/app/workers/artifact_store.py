from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID


class ArtifactIntegrityError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StoredObject:
    object_key: str
    sha256: str
    size_bytes: int
    path: Path


class LocalArtifactStore:
    """Filesystem object store for local MVP and tests.

    Object keys and filenames are server-generated; user-controlled names never
    participate in path construction.
    """

    _extensions = {
        "STEP": ".step",
        "STL": ".stl",
        "PREVIEW": ".png",
        "VALIDATION_REPORT": ".json",
        "DRAWING_ANALYSIS": ".json",
        "CLARIFICATION_QUESTIONS": ".json",
        "CAD_IR": ".json",
    }

    def __init__(self, root: str | Path, max_artifact_bytes: int) -> None:
        self.root = Path(root).resolve()
        self.max_artifact_bytes = max_artifact_bytes

    def put_cad_ir(self, job_id: UUID, value: dict) -> StoredObject:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        return self._write(f"jobs/{job_id}/input/cad-ir.json", payload, len(payload))

    def cad_ir(self, job_id: UUID) -> StoredObject:
        return self._read(f"jobs/{job_id}/input/cad-ir.json")

    def put_drawing(self, job_id: UUID, payload: bytes, extension: str) -> StoredObject:
        if extension not in {".png", ".jpg"}:
            raise ArtifactIntegrityError("unsupported drawing type")
        if len(payload) == 0 or len(payload) > self.max_artifact_bytes:
            raise ArtifactIntegrityError("drawing size is outside the allowed range")
        return self._write(f"jobs/{job_id}/input/page-001{extension}", payload, len(payload))

    def drawing(self, job_id: UUID) -> StoredObject:
        for extension in (".png", ".jpg"):
            try:
                return self._read(f"jobs/{job_id}/input/page-001{extension}")
            except ArtifactIntegrityError:
                pass
        raise ArtifactIntegrityError("drawing was not found")

    def put_answers(self, job_id: UUID, value: dict) -> StoredObject:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        return self._write(f"jobs/{job_id}/input/user-answers.json", payload, len(payload))

    def put_prior_analysis(self, job_id: UUID, payload: bytes) -> StoredObject:
        """Carry a round's reading into the next round's job.

        Each clarification round is a new job with a new directory, so without
        this the worker has nothing to reuse and re-reads the drawing — a second
        vision call, and a fresh set of question ids that the answers already sent
        no longer refer to.
        """
        return self._write(f"jobs/{job_id}/input/drawing-analysis.json", payload, len(payload))

    def prior_analysis(self, job_id: UUID) -> StoredObject | None:
        try:
            return self._read(f"jobs/{job_id}/input/drawing-analysis.json")
        except ArtifactIntegrityError:
            return None

    def answers(self, job_id: UUID) -> StoredObject | None:
        try:
            return self._read(f"jobs/{job_id}/input/user-answers.json")
        except ArtifactIntegrityError:
            return None

    def put_drawing_tracking(
        self,
        order_id: UUID,
        latest_job_id: UUID,
        source_job_id: UUID,
        round_number: int,
    ) -> StoredObject:
        payload = json.dumps(
            {
                "latest_job_id": str(latest_job_id),
                "source_job_id": str(source_job_id),
                "round": round_number,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return self._write(f"orders/{order_id}/drawing-tracking.json", payload, len(payload))

    def drawing_tracking(self, order_id: UUID) -> dict:
        stored = self._read(f"orders/{order_id}/drawing-tracking.json")
        try:
            value = json.loads(stored.path.read_text(encoding="utf-8"))
            return {
                "latest_job_id": UUID(value["latest_job_id"]),
                "source_job_id": UUID(value["source_job_id"]),
                "round": int(value["round"]),
            }
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise ArtifactIntegrityError("drawing tracking is invalid") from error

    def artifact(self, job_id: UUID, artifact_type: str) -> StoredObject:
        normalized = artifact_type.upper()
        extension = self._extensions.get(normalized)
        if extension is None:
            raise ArtifactIntegrityError("unsupported artifact type")
        return self._read(f"jobs/{job_id}/artifacts/{normalized.lower()}{extension}")

    def put_artifact(
        self,
        job_id: UUID,
        artifact_type: str,
        payload: bytes,
        expected_sha256: str,
    ) -> StoredObject:
        normalized = artifact_type.upper()
        extension = self._extensions.get(normalized)
        if extension is None:
            raise ArtifactIntegrityError("unsupported artifact type")
        if len(payload) == 0 or len(payload) > self.max_artifact_bytes:
            raise ArtifactIntegrityError("artifact size is outside the allowed range")
        actual = hashlib.sha256(payload).hexdigest().upper()
        if not _constant_hex_equal(actual, expected_sha256):
            raise ArtifactIntegrityError("artifact checksum mismatch")
        return self._write(f"jobs/{job_id}/artifacts/{normalized.lower()}{extension}", payload, len(payload))

    def verify_completion(self, job_id: UUID, artifact: dict) -> None:
        expected_prefix = f"jobs/{job_id}/artifacts/"
        object_key = artifact["object_key"]
        if not object_key.startswith(expected_prefix):
            raise ArtifactIntegrityError("artifact object key does not belong to the job")
        stored = self._read(object_key)
        if (
            stored.size_bytes != artifact["size_bytes"]
            or not _constant_hex_equal(stored.sha256, artifact["sha256"])
        ):
            raise ArtifactIntegrityError("completion metadata does not match uploaded artifact")

    def _write(self, object_key: str, payload: bytes, size: int) -> StoredObject:
        path = self._resolve_key(object_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, path)
        return StoredObject(object_key, hashlib.sha256(payload).hexdigest().upper(), size, path)

    def _read(self, object_key: str) -> StoredObject:
        path = self._resolve_key(object_key)
        if not path.is_file():
            raise ArtifactIntegrityError("stored object was not found")
        size = path.stat().st_size
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest().upper()
        return StoredObject(object_key, digest, size, path)

    def _resolve_key(self, object_key: str) -> Path:
        candidate = (self.root / object_key).resolve()
        if not candidate.is_relative_to(self.root):
            raise ArtifactIntegrityError("invalid object key")
        return candidate


def _constant_hex_equal(left: str, right: str) -> bool:
    import secrets

    return secrets.compare_digest(left.removeprefix("sha256:").upper(), right.removeprefix("sha256:").upper())
