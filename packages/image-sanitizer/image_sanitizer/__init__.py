"""Turn an untrusted raster upload into a canonical PNG, and nothing else.

Its own package for one reason, and it is the whole design: **the API must not
contain an image decoder.** A decoder is the largest attack surface in this
service — tens of thousands of lines of C reached by bytes a stranger chose — and
the process it runs in should own nothing worth taking. This package has no
database, no credentials, no network client and no knowledge of the rest of the
service; it reads one file and writes one file.

`docs/SECURE-INPUT-ADDENDUM.md` §2.1 is the specification. The steps are not
interchangeable, and each is there for something a check earlier in the list
cannot cover:

    full decode         `Image.verify()` parses a header and returns. Only `load()`
                        drives the decoder over every byte, which is the only way
                        to find out whether the bytes decode at all.
    a new image         The result is built from pixels, not saved from the object
                        that was parsed. Anything the decoder attached — metadata,
                        colour profiles, ancillary chunks, a second frame — does
                        not travel, because it is never held.
    EXIF orientation    Applied and then dropped. A drawing rotated by a tag the
                        worker's reader ignores is a drawing analysed sideways.
    alpha onto white    Composited rather than discarded. Dropping the channel
                        keeps the RGB *under* transparent pixels, which is data the
                        uploader believed was invisible.
    re-encode as PNG    Lossless, because the product is thin lines and small
                        dimension text, and JPEG on a drawing eats exactly those.
"""

from .sanitize import SanitizedPage, SanitizerRejected, sanitize_bytes, sanitize_file

__all__ = ["SanitizedPage", "SanitizerRejected", "sanitize_bytes", "sanitize_file"]
