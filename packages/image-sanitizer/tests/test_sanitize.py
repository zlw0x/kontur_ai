"""What the sanitizer refuses, and what it strips from what it accepts.

The API's own tests cannot be these: they must not have an image encoder, because
the API must not have an image decoder, and a test that builds a PNG needs one.
So the hostile inputs live here, beside the only part of the service allowed to
look at them.

Every case is a real file built for the test rather than a description of one. A
decompression bomb is not a scenario, it is 109 KiB that claims to be 900
megapixels, and the difference is the whole subject.
"""

from __future__ import annotations

import io

import pytest

pytest.importorskip("PIL", reason="the sanitizer's own decoder is not installed")

from PIL import Image  # noqa: E402
from PIL.PngImagePlugin import PngInfo  # noqa: E402

from image_sanitizer import SanitizerRejected, sanitize_bytes  # noqa: E402

#: The policy's numbers, passed in rather than imported: this package does not know
#: where the service keeps its settings, and that is deliberate.
LIMITS = dict(max_width=12_000, max_height=12_000, max_pixels=60_000_000,
              max_frames=1, max_output_bytes=40 * 1024 * 1024)


def encoded(image: Image.Image, **options) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, **options)
    return buffer.getvalue()


def clean(payload: bytes):
    return sanitize_bytes(payload, **LIMITS)


def refusal(payload: bytes) -> str:
    with pytest.raises(SanitizerRejected) as raised:
        clean(payload)
    return raised.value.code


# --- what comes out -----------------------------------------------------------


def test_a_drawing_comes_back_as_a_png_of_the_same_size():
    page = clean(encoded(Image.new("RGB", (60, 40), (200, 10, 10)), format="PNG"))

    assert (page.width, page.height) == (60, 40)
    assert page.png.startswith(b"\x89PNG\r\n\x1a\n")
    assert page.source_format == "PNG"


def test_a_jpeg_comes_back_as_a_png():
    """Lossless from here on. The product is thin lines and small dimension text,
    and JPEG on a drawing eats exactly those."""
    page = clean(encoded(Image.new("RGB", (32, 32), (255, 255, 255)), format="JPEG"))

    assert page.source_format == "JPEG"
    assert page.png.startswith(b"\x89PNG\r\n\x1a\n")


def test_metadata_does_not_travel():
    """The check that says why the page is rebuilt rather than re-saved.

    Anything the decoder attached — a comment, a colour profile, an ancillary chunk
    — would survive a `save()` of the parsed object. It does not survive being
    built from pixels, because none of it is ever held.
    """
    meta = PngInfo()
    meta.add_text("Comment", "SECRET-PAYLOAD")
    meta.add_text("Software", "something that should not reach a model")
    raw = encoded(Image.new("RGB", (20, 20), (0, 0, 0)), format="PNG", pnginfo=meta)
    assert b"SECRET-PAYLOAD" in raw

    assert b"SECRET-PAYLOAD" not in clean(raw).png


def test_what_hides_under_transparency_does_not_travel():
    """Dropping the alpha channel keeps the RGB underneath, which the uploader
    believed was invisible. Compositing onto white is what a drawing means."""
    page = clean(encoded(Image.new("RGBA", (8, 8), (255, 0, 0, 0)), format="PNG"))

    result = Image.open(io.BytesIO(page.png))
    assert result.mode == "RGB"
    assert result.getpixel((0, 0)) == (255, 255, 255)


def test_an_exif_rotation_is_applied_and_then_forgotten():
    """A drawing rotated by a tag the worker's reader ignores is a drawing analysed
    sideways. Applied here, so the pixels are upright and the tag is gone."""
    upright = Image.new("RGB", (40, 10), (0, 0, 0))
    exif = upright.getexif()
    exif[274] = 6  # rotate 90° clockwise
    turned = encoded(upright, format="JPEG", exif=exif)

    page = clean(turned)

    assert (page.width, page.height) == (10, 40)
    assert not Image.open(io.BytesIO(page.png)).getexif()


# --- what it refuses ----------------------------------------------------------


def test_a_decompression_bomb_is_refused_by_its_pixel_count():
    """109 KiB claiming 900 megapixels. The reason `Image.verify()` is not enough
    and the reason the limit is on the *product* rather than on either side."""
    bomb = encoded(Image.new("1", (30_000, 30_000)), format="PNG")
    assert len(bomb) < 200_000

    assert refusal(bomb) == "INPUT_PIXELS_TOO_MANY"


def test_a_sheet_wider_than_the_policy_is_refused_by_its_width():
    """Named separately from the bomb, because "too big" and "this is a bomb" are
    different things to tell somebody."""
    assert refusal(encoded(Image.new("RGB", (13_000, 100)), format="PNG")) \
        == "INPUT_DIMENSIONS_TOO_LARGE"


def test_a_format_outside_the_contour_is_refused_even_though_pillow_reads_it():
    """The requirement the addendum states in as many words: the sanitizer limits
    the decoders it will use. Pillow dispatches on content, so without this a GIF,
    an ICO or a TIFF reaches its own decoder — none of which is in the approved
    input contour."""
    assert refusal(encoded(Image.new("P", (10, 10)), format="GIF")) \
        == "INPUT_FORMAT_NOT_ALLOWED"


def test_an_animated_png_is_refused_rather_than_having_a_frame_chosen_for_it():
    frames = [Image.new("RGB", (10, 10), colour) for colour in ((255, 0, 0), (0, 255, 0))]
    animated = io.BytesIO()
    frames[0].save(animated, format="PNG", save_all=True, append_images=frames[1:])

    assert refusal(animated.getvalue()) == "INPUT_ANIMATED"


def test_a_truncated_image_is_refused_rather_than_half_read():
    whole = encoded(Image.new("RGB", (200, 200), (1, 2, 3)), format="PNG")

    assert refusal(whole[: len(whole) // 2]) == "INPUT_DECODE_FAILED"


def test_bytes_that_are_not_an_image_are_refused():
    assert refusal(b"\x89PNG\r\n\x1a\n" + b"nonsense" * 40) == "INPUT_DECODE_FAILED"


def test_a_page_larger_than_the_policy_allows_is_refused_after_encoding():
    """The last limit, and the one only the output can fail: a legal input can
    encode to more than the service will store."""
    noisy = Image.effect_noise((400, 400), 128).convert("RGB")

    with pytest.raises(SanitizerRejected) as raised:
        sanitize_bytes(encoded(noisy, format="PNG"), **{**LIMITS, "max_output_bytes": 1_000})
    assert raised.value.code == "SANITIZED_PAGE_TOO_LARGE"
