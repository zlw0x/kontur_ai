"""Who somebody is, and the fact that they are still signed in.

Two tables, and the split between them is the whole design. A `users` row is a
long-lived fact — an email, a password hash, a role — and a `sessions` row is a
short-lived one that can be taken away without touching it. Revoking a session
must be a single write that takes effect on the next request, which is why the
session is a row rather than a signed token the server cannot recall.

Neither table ever holds a secret in the form it was given. The password is a
bcrypt hash and the session token is a SHA-256 of the bytes the browser holds, so
a copy of this database is not a set of working credentials. That is also why the
token column is what is indexed: the lookup is by hash, and the raw token exists
only in the cookie and in the one response that issued it.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    #: What the customer typed, kept as typed so a greeting can use it.
    email: Mapped[str] = mapped_column(String(320))
    #: The same address, case-folded, and the column the UNIQUE constraint is on.
    #: `Ivan@example.com` and `ivan@example.com` are one account everywhere it
    #: matters, and letting them be two would make "an account already exists" a
    #: thing a user could get around by holding shift.
    email_folded: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="customer", index=True)
    #: The shared secret behind a TOTP code, base32 as RFC 4648 writes it.
    #:
    #: Only `operator` and `admin` have one. A customer with second-factor
    #: authentication is a customer who cannot get to their own drawing when their
    #: phone is flat, and for this pilot that trade is not worth making — the
    #: accounts that can see *everybody's* drawings are a different matter.
    totp_secret: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    #: Set rather than deleted. An order points at its owner, and a deleted user
    #: would either take the order with it or leave a dangling reference; a disabled
    #: one keeps the history readable and stops being able to sign in.
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # How many wrong passwords in a row, and until when the account is shut.
    #
    # On the row rather than in a table of rate events, because the question is
    # "how many in a row for *this account*" and the answer is one number. Durable
    # rather than in-process for the reason everything else here is: an attacker
    # who can wait for a deploy has waited out an in-memory counter.
    failed_sign_ins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SessionRow(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    #: SHA-256 of the cookie's value. Unique so two sessions cannot collide, and
    #: indexed because every authenticated request is one lookup on it.
    #:
    #: A plain hash rather than bcrypt, deliberately and for a reason that does not
    #: apply to the password: this is 32 bytes from `secrets.token_urlsafe`, so
    #: there is no dictionary to run against it and no work factor worth paying on
    #: every request.
    token_sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    #: SHA-256 of the CSRF token issued with this session.
    #:
    #: Bound to the session rather than compared cookie-against-header, which is the
    #: naive form of double submit and loses to anything that can set a cookie on a
    #: sibling subdomain: an attacker who writes both halves passes a check that only
    #: compares them to each other. Checking the header against a value stored here
    #: means the attacker would have to know a secret they were never sent.
    csrf_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    #: When somebody signed out, or an operator ended it. Checked on every read, so
    #: a revoked session stops working on the next request rather than at expiry.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


__all__ = ["SessionRow", "UserRow"]
