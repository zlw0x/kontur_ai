"""Turning a password into something a stolen database does not contain.

One rule, and it is the only one that matters: **never a bare hash**. SHA-256 of a
password is a lookup, not a defence — a commodity GPU tries billions of candidates
a second against it, and every user who chose a word from a dictionary is already
compromised the moment the table leaks.

What is here is bcrypt with a work factor, which makes each guess cost real time.
Argon2id would be the better answer — it is memory-hard, so an attacker cannot buy
their way out with parallelism the way they can against bcrypt — and it is not what
this uses, for a reason worth writing down rather than hiding: `argon2-cffi` is not
in this service's dependency tree, and `bcrypt` already is. Adding a compiled
dependency to the API image is a change with its own build and its own failure
modes, and it is not the change that makes the difference here. The difference is
between "a hash" and "a hash that costs something", and this side of that line is
where the whole risk lives.

`verify` returns a boolean and never raises on a wrong password, so a caller cannot
accidentally turn "wrong password" into a 500 that tells an attacker they found a
real account.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time

import bcrypt

#: bcrypt's cost, as a power of two. 12 is roughly a quarter of a second on the
#: hardware this runs on — slow enough to make offline guessing expensive, fast
#: enough that a sign-in does not feel broken. It is stored inside the hash, so
#: raising it later leaves existing hashes verifiable.
BCRYPT_ROUNDS = 12

#: The shortest password this service will accept.
#:
#: A length floor rather than a character-class rule: "at least one digit and one
#: symbol" reliably produces `Password1!`, which is in every list. Length is the
#: property that actually costs an attacker something.
MIN_PASSWORD_LENGTH = 12

#: And a ceiling, because a password is an unauthenticated input and hashing is
#: deliberately slow. Without one, a 10 MB "password" is a free way to make the
#: server work; the pre-hash below would flatten it anyway, and this refuses it
#: before that.
MAX_PASSWORD_LENGTH = 1024


class WeakPassword(ValueError):
    """A password the service will not store. About the password, not the user."""


def _prepared(password: str) -> bytes:
    """bcrypt reads 72 bytes, so hand it 44 that depend on all of them.

    This is not optional and not a nicety. bcrypt truncates at 72 bytes — silently
    in older releases, with an exception in 5.0 — so without it a passphrase longer
    than that is either quietly weakened to its first 72 bytes or rejected as a
    server error. SHA-256 first, then base64 so no NUL byte can appear and truncate
    the string a C implementation reads.
    """
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


def hash_password(password: str) -> str:
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise WeakPassword(
            f"a password is between {MIN_PASSWORD_LENGTH} and "
            f"{MAX_PASSWORD_LENGTH} characters"
        )
    return bcrypt.hashpw(_prepared(password), bcrypt.gensalt(BCRYPT_ROUNDS)).decode("ascii")


def verify_password(password: str, stored: str) -> bool:
    try:
        return bcrypt.checkpw(_prepared(password), stored.encode("ascii"))
    except (ValueError, TypeError):
        # A malformed hash in the row. False rather than an exception: a broken
        # stored value must not become a 500 that distinguishes this account from
        # every other wrong answer.
        return False


#: A hash of nothing in particular, verified against when no such user exists.
#:
#: Otherwise the two answers take visibly different times — a real account pays for
#: bcrypt and an unknown one returns at once — and that difference is a working
#: account-enumeration oracle against a login form that is careful to say the same
#: words in both cases.
DECOY_HASH = hash_password("a password no account has, used only to spend the time")


# --- second factor -------------------------------------------------------------
#
# RFC 6238, from the standard library. `pyotp` is thirty lines of this and one more
# dependency in an image that has to be reviewed; the algorithm is a counter, an
# HMAC and a truncation, and it is specified precisely enough that writing it here
# is not the kind of cryptography one should avoid writing.


#: How many 30-second steps either side of now are accepted.
#:
#: One, which is the RFC's own advice: phones drift and people type slowly, and a
#: window of zero produces a second factor that fails for reasons the user cannot
#: see or fix. Wider than one starts to matter, because every extra step is another
#: valid code at any instant.
TOTP_WINDOW = 1
TOTP_STEP_SECONDS = 30
TOTP_DIGITS = 6


def new_totp_secret() -> str:
    """20 random bytes, base32, which is what an authenticator app expects."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def totp_code(secret: str, at: float | None = None, offset: int = 0) -> str:
    padding = "=" * (-len(secret) % 8)
    key = base64.b32decode(secret + padding, casefold=True)
    counter = int((at if at is not None else time.time()) // TOTP_STEP_SECONDS) + offset
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    start = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[start:start + 4])[0] & 0x7FFFFFFF
    return str(truncated % (10 ** TOTP_DIGITS)).zfill(TOTP_DIGITS)


def verify_totp(secret: str | None, supplied: str | None, at: float | None = None) -> bool:
    """False when either side is missing, so a caller cannot forget to require it."""
    if not secret or not supplied:
        return False
    candidate = supplied.strip().replace(" ", "")
    return any(
        # Constant-time even though a TOTP code is short-lived: the comparison is
        # against a value an attacker is actively guessing, and `==` on strings
        # returns as soon as two characters differ.
        hmac.compare_digest(candidate, totp_code(secret, at, offset))
        for offset in range(-TOTP_WINDOW, TOTP_WINDOW + 1)
    )


__all__ = [
    "DECOY_HASH",
    "MAX_PASSWORD_LENGTH",
    "MIN_PASSWORD_LENGTH",
    "WeakPassword",
    "hash_password",
    "new_totp_secret",
    "totp_code",
    "verify_password",
    "verify_totp",
]
