"""The decode-and-rebuild step. Runs where nothing else valuable is."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

#: The decoders this program will use, whatever the bytes claim to be. Pillow
#: dispatches on content, so a JPEG named `.png` still reaches the JPEG decoder —
#: and a GIF, an ICO or a TIFF would reach theirs, which are not in the approved
#: input contour and must not be driven by a stranger's bytes. The addendum states
#: this as a requirement: the sanitizer restricts the decoder list itself.
ALLOWED_FORMATS = frozenset({"PNG", "JPEG"})


class SanitizerRejected(Exception):
    """The upload will not become a page, with a typed code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


@dataclass(frozen=True)
class SanitizedPage:
    png: bytes
    width: int
    height: int
    source_format: str


def sanitize_file(source: Path, max_width: int, max_height: int, max_pixels: int,
                  max_frames: int, max_output_bytes: int) -> SanitizedPage:
    return sanitize_bytes(Path(source).read_bytes(), max_width, max_height, max_pixels,
                          max_frames, max_output_bytes)


def sanitize_bytes(payload: bytes, max_width: int, max_height: int, max_pixels: int,
                   max_frames: int, max_output_bytes: int) -> SanitizedPage:
    # Pillow's own bomb guard, set to the policy rather than left at its default.
    # A second line: the explicit check below fires first and says which limit was
    # passed, which a `DecompressionBombError` does not.
    Image.MAX_IMAGE_PIXELS = max_pixels

    try:
        opened = Image.open(io.BytesIO(payload))
    except UnidentifiedImageError as error:
        raise SanitizerRejected("INPUT_NOT_AN_IMAGE", "The file is not a readable image.") from error
    except Image.DecompressionBombError as error:
        # Pillow's guard fires inside `open()`, before the explicit check below can
        # run — so without this the customer is told "the image could not be read"
        # about a file whose actual problem is that it is a 900-megapixel canvas in
        # 109 KiB. Measured: that is the exact shape of a decompression bomb, and
        # naming it is the difference between a bug report and a refusal.
        raise SanitizerRejected(
            "INPUT_PIXELS_TOO_MANY",
            f"A drawing must be at most {max_pixels} pixels.",
        ) from error
    except Exception as error:  # noqa: BLE001 - every decoder failure is one answer
        raise SanitizerRejected("INPUT_DECODE_FAILED", "The image could not be read.") from error

    with opened:
        if (opened.format or "").upper() not in ALLOWED_FORMATS:
            raise SanitizerRejected(
                "INPUT_FORMAT_NOT_ALLOWED", "A drawing must be a PNG or a JPEG."
            )
        # Dimensions before pixels: both are refused, and saying which is which is
        # the difference between "too big" and "this is a bomb".
        if opened.width > max_width or opened.height > max_height:
            raise SanitizerRejected(
                "INPUT_DIMENSIONS_TOO_LARGE",
                f"A drawing must be at most {max_width} x {max_height} pixels; "
                f"this one is {opened.width} x {opened.height}.",
            )
        if opened.width * opened.height > max_pixels:
            raise SanitizerRejected(
                "INPUT_PIXELS_TOO_MANY",
                f"A drawing must be at most {max_pixels} pixels; this one is "
                f"{opened.width * opened.height}.",
            )
        if getattr(opened, "n_frames", 1) > max_frames:
            # A sequence is not a drawing, and picking a frame would be choosing on
            # the customer's behalf which page they meant.
            raise SanitizerRejected("INPUT_ANIMATED", "A drawing must be a single still image.")

        source_format = opened.format or "UNKNOWN"
        try:
            # The step `verify()` cannot do: drive the decoder over every byte.
            opened.load()
            upright = ImageOps.exif_transpose(opened) or opened
            flattened = _onto_white(upright)
        except SanitizerRejected:
            raise
        except Exception as error:  # noqa: BLE001 - a decoder that failed part way
            raise SanitizerRejected("INPUT_DECODE_FAILED", "The image could not be read.") from error

    # Built from pixels rather than saved from the parsed object: nothing the
    # decoder attached travels, because none of it is held. `frombytes` rather than
    # `putdata`, which Pillow 14 removes — and which materialised the whole image as
    # a Python list of tuples on the way, sixty times the memory of the pixels.
    clean = Image.frombytes("RGB", flattened.size, flattened.tobytes())

    sink = io.BytesIO()
    clean.save(sink, format="PNG", optimize=True)
    png = sink.getvalue()
    if len(png) > max_output_bytes:
        raise SanitizerRejected(
            "SANITIZED_PAGE_TOO_LARGE",
            "The cleaned drawing is larger than the service accepts.",
        )
    return SanitizedPage(png=png, width=clean.width, height=clean.height,
                         source_format=source_format)


def _onto_white(image: Image.Image) -> Image.Image:
    """Composite onto white rather than dropping the channel.

    Dropping alpha keeps whatever RGB sits *under* transparent pixels — data the
    uploader believed was invisible, handed to a model that reads everything. A
    drawing is ink on paper, so paper is what the transparent part becomes.
    """
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        paper = Image.new("RGB", rgba.size, (255, 255, 255))
        paper.paste(rgba, mask=rgba.split()[-1])
        return paper
    return image.convert("RGB")
