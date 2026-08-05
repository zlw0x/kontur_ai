"""A drawing that is actually an image, for the tests that upload one.

Every test here used to post `b"\\x89PNG\\r\\n\\x1a\\n" + b"fixture"` — eight correct
magic bytes and then nonsense — because the endpoint checked the signature and
stored what it was given. It does not any more: the upload is decoded and rebuilt
by a separate program, and eight bytes of header followed by the word "fixture" is
not an image and is refused, correctly.

So the fixture is a real PNG: 8 x 6 pixels, near-white, 78 bytes, held as base64
rather than generated. Generating it would put an image encoder in the API's test
dependencies, and the whole point of `packages/image-sanitizer` is that this side
does not have one.
"""

from __future__ import annotations

import base64

#: 8 x 6 RGB, near-white. Small enough to inline, real enough to decode.
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAGCAIAAABxZ0isAAAAFUlEQVR42mP89esXAzbAxIAD0EMCALXB"
    "AvoGRmCsAAAAAElFTkSuQmCC"
)

__all__ = ["TINY_PNG"]
