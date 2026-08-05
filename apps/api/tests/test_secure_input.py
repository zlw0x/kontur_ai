"""What reaches the pipeline, and what the API does before anything reads a byte.

`docs/SECURE-INPUT-ADDENDUM.md` is the approved requirement and had not been built.
What stood in its place was one line:

    payload = await request.body()

which read the whole upload into memory, checked eight magic bytes, and wrote the
file a stranger sent straight into the directory the worker downloads from. Three
separate problems, and the third is the one the addendum calls its central
invariant: **the raw upload must not cross into the pipeline.**

These tests are the API's half — the counting, the refusals it can make without a
decoder, and the boundary. What a decoder does to a hostile image is
`packages/image-sanitizer/tests`, because the tests for that need an image encoder
and this side must not have one.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest
from app.input.policy import POLICY
from app.input.quarantine import InputRejected, Quarantine
from app.input.sanitizer import Sanitizer, SanitizerUnavailable
from tests.drawing_fixture import TINY_PNG


@pytest.fixture()
def quarantine(tmp_path) -> Quarantine:
    return Quarantine(tmp_path / "quarantine")


def held(quarantine: Quarantine, chunks, media_type="image/png", declared=None):
    return asyncio.run(quarantine.accept(chunks, media_type, declared))


def refusal(quarantine: Quarantine, chunks, media_type="image/png", declared=None) -> str:
    with pytest.raises(InputRejected) as raised:
        held(quarantine, chunks, media_type, declared)
    return raised.value.code


# --- the read itself ----------------------------------------------------------


def test_an_upload_is_hashed_and_counted_as_it_arrives(quarantine):
    file = held(quarantine, [TINY_PNG[:20], TINY_PNG[20:]])

    assert file.size_bytes == len(TINY_PNG)
    assert file.sha256 == hashlib.sha256(TINY_PNG).hexdigest()
    assert file.path.read_bytes() == TINY_PNG


def test_the_customers_filename_is_never_a_path(quarantine):
    """A filename is attacker-controlled and a path is not a place to find that out.
    The object is keyed by a UUID this side made up."""
    file = held(quarantine, [TINY_PNG])

    assert file.path.name == str(file.file_id)
    assert file.path.parent == quarantine.root


def test_a_body_over_the_limit_stops_being_read_rather_than_being_measured(quarantine):
    """The difference between a limit and a description of what already happened.

    The old handler awaited the entire body and then looked at its length. Here the
    read stops at the limit: the chunks after it are never written and never hashed,
    which is what stops a 4 GiB upload from being a 4 GiB allocation.
    """
    chunk = b"\x89PNG\r\n\x1a\n" + b"\x00" * (1024 * 1024 - 8)
    read = 0

    def endless():
        nonlocal read
        while True:
            read += len(chunk)
            yield chunk

    assert refusal(quarantine, endless()) == "INPUT_TOO_LARGE"
    # Read a little past the limit and then stopped — not the whole stream, which
    # has no end.
    assert read < POLICY.max_upload_bytes + 2 * len(chunk)
    assert list(quarantine.root.iterdir()) == []


def test_a_lying_content_length_does_not_get_through(quarantine):
    """`Content-Length` is a claim, and is absent under chunked transfer. It is used
    as a fast pre-filter and never as the accepted size."""
    oversize = b"\x89PNG\r\n\x1a\n" + b"\x00" * (POLICY.max_upload_bytes + 1)

    assert refusal(quarantine, [oversize], declared=10) == "INPUT_TOO_LARGE"


def test_a_declared_length_over_the_limit_is_refused_before_the_read(quarantine):
    huge = POLICY.max_upload_bytes + 1

    with pytest.raises(InputRejected) as raised:
        held(quarantine, [TINY_PNG], declared=huge)
    assert (raised.value.code, raised.value.status_code) == ("INPUT_TOO_LARGE", 413)


@pytest.mark.parametrize("media_type", ["image/gif", "application/pdf", "text/html", None, ""])
def test_only_png_and_jpeg_are_admitted(quarantine, media_type):
    with pytest.raises(InputRejected) as raised:
        held(quarantine, [TINY_PNG], media_type=media_type)
    assert (raised.value.code, raised.value.status_code) == ("INPUT_MEDIA_TYPE_UNSUPPORTED", 415)


def test_content_that_is_not_what_the_type_claims_is_refused(quarantine):
    """The first line of defence, and only the first: the addendum is explicit that a
    signature, a content type and an extension together are still not enough, and
    that only a full decode into a new pixel-only copy is."""
    assert refusal(quarantine, [b"GIF89a" + b"\x00" * 40]) == "INPUT_SIGNATURE_MISMATCH"
    assert refusal(quarantine, [TINY_PNG], media_type="image/jpeg") == "INPUT_SIGNATURE_MISMATCH"


def test_an_empty_upload_is_refused_and_leaves_nothing_behind(quarantine):
    assert refusal(quarantine, [b""]) == "INPUT_EMPTY"
    assert list(quarantine.root.iterdir()) == []


def test_a_refused_upload_is_not_left_in_quarantine(quarantine):
    refusal(quarantine, [b"GIF89a" + b"\x00" * 40])

    assert list(quarantine.root.iterdir()) == []


# --- the boundary --------------------------------------------------------------


def test_the_page_that_comes_back_is_a_png_and_carries_its_manifest(quarantine, tmp_path):
    """The end-to-end shape, through a real child process.

    Whether the sanitizer's own package is installed decides whether this runs; it
    is not skipped when Pillow is missing, because a skip reads like a pass and this
    is the assertion that the boundary works at all.
    """
    file = held(quarantine, [TINY_PNG])

    page = Sanitizer().sanitize(file, tmp_path / "accepted")

    assert page.png.startswith(b"\x89PNG\r\n\x1a\n")
    assert (page.width, page.height) == (8, 6)
    manifest = page.manifest()
    assert manifest["policy_version"] == POLICY.version
    assert manifest["source_sha256"] == file.sha256
    assert manifest["sanitized_sha256"] == hashlib.sha256(page.png).hexdigest()


def test_the_sanitizer_runs_somewhere_else(quarantine, tmp_path):
    """Not a detail: a decoder is the largest attack surface in the service, and the
    process it runs in should own nothing worth taking. The argv is the assertion —
    a separate interpreter, a fixed argument list, no shell."""
    command = Sanitizer()._command(Path("/in/x.png"), Path("/out/page-001.png"))

    assert command[1:3] == ["-m", "image_sanitizer"]
    assert "--max-pixels" in command and str(POLICY.max_pixels) in command
    assert "--memory-bytes" in command and "--cpu-seconds" in command


def test_the_container_mode_drops_everything_it_can(quarantine):
    """What production runs. The flags are the addendum's §2.2 list, and they are
    asserted rather than described because a missing one is invisible."""
    command = Sanitizer(image="cad-ai/sanitizer:1")._command(
        Path("/tmp/in/x.png"), Path("/tmp/out/page-001.png")
    )

    for flag in ("--network", "none", "--read-only", "--cap-drop", "ALL",
                 "--security-opt", "no-new-privileges", "--pids-limit"):
        assert flag in command
    assert "--user" in command and "65534:65534" in command
    # One mount in, one out, and the input read-only.
    assert "/tmp/in:/in:ro" in command
    assert "docker" == command[0]


def test_a_sanitizer_that_cannot_run_is_about_the_machine(quarantine, tmp_path):
    """Kept apart from a refusal for the reason `BuildFeedback` keeps them apart:
    telling a customer their drawing is malformed because an operator has not
    installed a decoder is a lie the service would repeat every time."""
    file = held(quarantine, [TINY_PNG])

    with pytest.raises(SanitizerUnavailable):
        Sanitizer(python="/nonexistent/python").sanitize(file, tmp_path / "accepted")


def test_the_raw_upload_can_be_discarded_and_the_page_survives(quarantine, tmp_path):
    """§5: the raw file goes as soon as processing ends. Nothing downstream can
    reach quarantine, so what is left is only a window — and a window worth closing."""
    file = held(quarantine, [TINY_PNG])
    page = Sanitizer().sanitize(file, tmp_path / "accepted")

    quarantine.discard(file.file_id)

    assert not file.path.exists()
    assert page.png


# --- and through the endpoint --------------------------------------------------


def test_the_worker_downloads_the_cleaned_page_and_never_the_upload(monkeypatch, tmp_path):
    """The addendum's central invariant, as one assertion.

    The upload carries a comment no drawing needs. The job directory the worker
    downloads from must contain a page that does not.
    """
    import base64
    import json

    from fastapi.testclient import TestClient

    from app.main import app
    from app.input.quarantine import Quarantine
    from app.workers.artifact_store import LocalArtifactStore
    from tests.test_worker_api import memory_protocol

    memory_protocol(monkeypatch)
    monkeypatch.setattr("app.main.artifact_store", LocalArtifactStore(tmp_path / "store", 10_000_000))
    monkeypatch.setattr("app.main.quarantine", Quarantine(tmp_path / "quarantine"))
    client = TestClient(app)

    # The same 8 x 6 page, re-encoded with a text chunk in it.
    marked = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAGCAIAAABxZ0isAAAAFnRFWHRDb21tZW50AFNFQ1JFVC1QQV"
        "lMT0FEZmYvugAAABVJREFUeNpj/PXrFwM2wMSAA9BDAgC1wQL6BkZgrAAAAABJRU5ErkJggg=="
    )
    assert b"SECRET-PAYLOAD" in marked

    created = client.post(
        "/api/v1/drawing-jobs",
        headers={"x-manual-api-token": "local-development-manual-api-token-change-me",
                 "content-type": "image/png"},
        content=marked,
    )
    assert created.status_code == 201, created.text
    job_id = created.json()["job_id"]

    stored = (tmp_path / "store" / "jobs" / job_id / "input" / "page-001.png").read_bytes()
    assert stored.startswith(b"\x89PNG\r\n\x1a\n")
    assert b"SECRET-PAYLOAD" not in stored
    # And nothing else of the upload is anywhere the worker can reach.
    assert sorted(p.name for p in (tmp_path / "store" / "jobs" / job_id / "input").iterdir()) == [
        "page-001.manifest.json", "page-001.png",
    ]
    manifest = json.loads(
        (tmp_path / "store" / "jobs" / job_id / "input" / "page-001.manifest.json").read_text()
    )
    assert manifest["source_sha256"] == hashlib.sha256(marked).hexdigest()
    assert manifest["policy_version"] == POLICY.version
    # Quarantine is empty: the raw upload did not outlive the request.
    assert list((tmp_path / "quarantine").iterdir()) == []


def test_an_upload_that_is_not_an_image_is_refused_by_the_endpoint(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.input.quarantine import Quarantine
    from app.workers.artifact_store import LocalArtifactStore
    from tests.test_worker_api import memory_protocol

    memory_protocol(monkeypatch)
    monkeypatch.setattr("app.main.artifact_store", LocalArtifactStore(tmp_path / "store", 10_000_000))
    monkeypatch.setattr("app.main.quarantine", Quarantine(tmp_path / "quarantine"))
    client = TestClient(app)

    refused = client.post(
        "/api/v1/drawing-jobs",
        headers={"x-manual-api-token": "local-development-manual-api-token-change-me",
                 "content-type": "image/png"},
        content=b"\x89PNG\r\n\x1a\n" + b"not an image at all" * 8,
    )

    assert refused.status_code == 422
    assert list((tmp_path / "quarantine").iterdir()) == []
