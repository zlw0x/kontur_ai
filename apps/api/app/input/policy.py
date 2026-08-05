"""What a drawing may be, as a versioned policy rather than as numbers in a handler.

`docs/SECURE-INPUT-ADDENDUM.md` §3 is the source of these, and it calls them a
versioned policy on purpose: they are load-test findings, not constants, and the
version travels with every accepted file so an audit can say which limits a
document was admitted under. A number changed without changing the version makes
every earlier acceptance unexplainable.

The limits are applied **at every level** the addendum lists — the proxy, the API
during the actual streaming read, the sanitizer, and the accepted document. Not
because any one of them is untrusted, but because each sees a different lie:
`Content-Length` is a claim, a decoded pixel count is not visible until the decode
starts, and a 25 MiB PNG can decompress to a hundred gigabytes.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Bumped whenever any number below changes. Written into every manifest.
POLICY_VERSION = "input-policy-1"

MIB = 1024 * 1024


@dataclass(frozen=True)
class InputPolicy:
    """The limits an upload is admitted under."""

    #: Bytes actually read, counted independently of `Content-Length` — which is a
    #: claim, and absent entirely under chunked transfer.
    max_upload_bytes: int = 25 * MIB
    #: One. An animated PNG or a multi-frame WEBP is a sequence, and a drawing is
    #: not: accepting one would mean choosing a frame on the customer's behalf.
    max_frames: int = 1
    max_width: int = 12_000
    max_height: int = 12_000
    #: The one that matters most. Width and height are each within reach of a
    #: legitimate large sheet; their *product* is what turns a 40 KiB file into an
    #: allocation that ends the process — the decompression bomb, and the reason
    #: `Image.verify()` is not enough.
    max_pixels: int = 60_000_000
    max_sanitized_bytes: int = 40 * MIB
    #: Wall clock for one page. A decoder that has not finished in ten seconds is
    #: not slow, it is being driven.
    page_timeout_seconds: float = 10.0
    #: Address space for the sanitizer process. Below what a 60 Mpx RGB image needs
    #: at three bytes a pixel plus working room, and far below the machine.
    memory_bytes: int = 768 * MIB
    cpu_seconds: int = 20

    @property
    def version(self) -> str:
        return POLICY_VERSION


#: The formats the pilot admits. WEBP is in the addendum's approved list and is not
#: here yet: static-only enforcement is a decoder question, and a format admitted
#: without the check that rejects its animated form is a format admitted by mistake.
#: PDF is a separate contour with its own rasterizer, and is deliberately not this.
ACCEPTED_MEDIA_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
}

#: The bytes a file must start with to be what it says it is. A first line of
#: defence and nothing more — the addendum is explicit that a signature check, a
#: `Content-Type` and an extension are together still not enough, and that only a
#: full decode into a new pixel-only copy is.
SIGNATURES = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
}

POLICY = InputPolicy()

__all__ = ["ACCEPTED_MEDIA_TYPES", "POLICY", "POLICY_VERSION", "SIGNATURES", "InputPolicy"]
