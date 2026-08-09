"""Signing up, signing in, and staying signed in.

Everything that *decides* is here; the repository only reads and writes. That is
what makes the rules below testable without a database and impossible to bypass by
reaching for a row directly.

Three of them are worth stating out loud, because each is a thing this service got
wrong or could not do before there were accounts at all:

**A sign-in failure says one thing.** Unknown email, wrong password, disabled
account and missing second factor all come back as the same refusal. Anything else
is a form that tells a stranger which addresses have accounts here — and the
drawings behind those accounts are somebody's commercial secret.

**And it takes the same time.** Saying the same words while returning in a
microsecond for an unknown address and a quarter of a second for a real one is the
same disclosure with extra steps, so an unknown address is verified against a decoy
hash.

**A session is a row that can be taken away.** Revoking has to take effect on the
next request, not at expiry, which rules out a self-contained signed token: nothing
can recall one of those without keeping a list, and once there is a list the token
has bought nothing.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.accounts.passwords import (
    DECOY_HASH,
    WeakPassword,
    hash_password,
    new_totp_secret,
    verify_password,
    verify_totp,
)
from app.accounts.limits import SignInPolicy, locked_out
from app.accounts.principal import MFA_REQUIRED, Principal, Role
from app.accounts.repository import AccountRepository, SessionRecord, UserRecord

#: How long a session lasts without being used again. Fourteen days is the ordinary
#: web answer: long enough that a customer is not signed out between an upload and
#: the model arriving, short enough that a laptop left in a café stops being a way in.
SESSION_LIFETIME = timedelta(days=14)

#: The cookie the browser holds. Named without a leading `__Host-` prefix because
#: that prefix forbids a `Domain` attribute and requires `Secure`, and the local
#: development setup serves the API over plain HTTP on a different port from the
#: web app. `Secure` is set from configuration instead, which is checked by a test.
SESSION_COOKIE = "cad_ai_session"

#: The CSRF token's cookie, deliberately readable by JavaScript — the client has to
#: be able to copy it into a header, which is the entire mechanism.
CSRF_COOKIE = "cad_ai_csrf"
CSRF_HEADER = "x-csrf-token"


class AuthenticationFailed(Exception):
    """One exception for every way signing in can go wrong. See the module docstring."""


class EmailAlreadyRegistered(Exception):
    """Raised by registration only, where saying so is unavoidable.

    A registration form cannot hide that an address is taken and still work. What it
    can do is be the only place that says so, which is why sign-in does not.
    """


@dataclass(frozen=True)
class IssuedSession:
    """A new session and the two secrets that only exist in this one response."""

    session: SessionRecord
    user: UserRecord
    token: str
    csrf_token: str


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def fold_email(email: str) -> str:
    """Case-folded and trimmed, which is what uniqueness is checked on.

    `casefold` rather than `lower`: it is the Unicode operation meant for caseless
    comparison, and the difference shows up on the day somebody registers with a
    Turkish dotless ı or a German ß.
    """
    return email.strip().casefold()


class AccountService:
    def __init__(
        self,
        repository: AccountRepository,
        clock: Callable[[], datetime] | None = None,
        lifetime: timedelta = SESSION_LIFETIME,
        sign_in_policy: SignInPolicy = SignInPolicy(),
    ) -> None:
        self.repository = repository
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.lifetime = lifetime
        self.sign_in_policy = sign_in_policy

    # --- accounts ---------------------------------------------------------------

    def register(
        self, email: str, password: str, role: Role = Role.CUSTOMER
    ) -> tuple[UserRecord, str | None]:
        """A new account, and a TOTP secret when the role needs one.

        The secret is returned exactly once and never again — it is stored to verify
        against, not to show — so the caller either enrols it now or the account has
        to be reset. That is the property an authenticator app depends on.
        """
        folded = fold_email(email)
        if "@" not in folded or folded.startswith("@") or folded.endswith("@"):
            raise WeakPassword("an email address is required")
        secret = new_totp_secret() if role in MFA_REQUIRED else None
        try:
            user = self.repository.create_user(
                email=email.strip(),
                email_folded=folded,
                password_hash=hash_password(password),
                role=role,
                totp_secret=secret,
            )
        except IntegrityError as clash:
            raise EmailAlreadyRegistered(folded) from clash
        return user, secret

    # --- signing in -------------------------------------------------------------

    def sign_in(self, email: str, password: str, totp: str | None = None) -> IssuedSession:
        """One refusal for every way this can go wrong, including too many tries.

        The lockout answers `AuthenticationFailed` like everything else rather than
        a `429`, and that is the point of it being here rather than in a middleware:
        a rate-limit response on a sign-in form announces that the address has an
        account. It is the one endpoint where saying "slow down" is a disclosure,
        and the careful wording of everything else here exists to avoid exactly that.

        The cost is that a locked-out customer is told only that their password is
        wrong. For a pilot that is the right way round — the alternative leaks which
        addresses are worth attacking — and it is why the counter resets on the first
        success rather than on a timer.
        """
        user = self.repository.user_by_email(fold_email(email))
        # The decoy is verified against, not skipped: see the module docstring. It
        # is the same bcrypt cost as a real hash, so the two paths take the same
        # quarter of a second.
        stored = user.password_hash if user is not None else DECOY_HASH
        password_ok = verify_password(password, stored)
        if user is None or not password_ok:
            if user is not None:
                self._count_failure(user)
            raise AuthenticationFailed("email or password is wrong")
        if user.disabled_at is not None:
            raise AuthenticationFailed("email or password is wrong")
        if locked_out(user.locked_until, self._clock()):
            # Checked *after* the password, so a correct password on a locked
            # account still costs the attacker nothing to distinguish — both take
            # one bcrypt verification and both say the same words.
            raise AuthenticationFailed("email or password is wrong")
        if user.role in MFA_REQUIRED:
            # An account that must have a second factor and has none cannot sign in.
            # The alternative — letting it through because the secret is missing —
            # turns the requirement into a suggestion that any failed enrolment
            # silently switches off.
            if not verify_totp(user.totp_secret, totp, self._clock().timestamp()):
                self._count_failure(user)
                raise AuthenticationFailed("email or password is wrong")
        # A run of failures ends at the first success rather than at a deadline, so
        # a customer who mistypes twice and then gets it right starts from zero.
        self.repository.clear_sign_in_failures(user.id)
        return self.issue(user)

    def _count_failure(self, user: UserRecord) -> None:
        """One more wrong answer, and the lock when there have been enough.

        The lock is written by the same call that increments, because a read of the
        count followed by a write of the lock is the interleaving that gives a
        parallel attacker as many tries as they have connections.
        """
        policy = self.sign_in_policy
        now = self._clock()
        # Passed as the value to write *if* this failure is the one that trips it.
        # The repository decides nothing; it increments under a lock and reports.
        failures = self.repository.record_sign_in_failure(user.id, lock_until=None)
        if failures >= policy.max_failures and not locked_out(user.locked_until, now):
            self.repository.record_sign_in_failure(user.id, lock_until=now + policy.lockout)

    def issue(self, user: UserRecord) -> IssuedSession:
        token, csrf_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        session = self.repository.create_session(
            user_id=user.id,
            token_sha256=digest(token),
            csrf_sha256=digest(csrf_token),
            expires_at=self._clock() + self.lifetime,
        )
        return IssuedSession(session=session, user=user, token=token, csrf_token=csrf_token)

    def sign_out(self, session_id: UUID) -> None:
        self.repository.revoke_session(session_id)

    # --- staying signed in ------------------------------------------------------

    def resolve(self, token: str) -> tuple[Principal, SessionRecord] | None:
        """The cookie's value to a principal, or nothing.

        Nothing, rather than an exception, for every reason a session can be no good:
        unknown, revoked, expired, or belonging to an account that has since been
        disabled. The caller's job is to answer 401 once, and giving it four
        distinguishable failures would only invite it to report which one.
        """
        session = self.repository.session_by_token(digest(token))
        if session is None or session.revoked_at is not None:
            return None
        if session.expires_at <= self._clock():
            return None
        user = self.repository.user(session.user_id)
        if user is None or user.disabled_at is not None:
            return None
        return (
            Principal(
                role=user.role,
                user_id=user.id,
                session_id=session.id,
                from_cookie=True,
            ),
            session,
        )

    def csrf_matches(self, session: SessionRecord, supplied: str | None) -> bool:
        """Whether the header carries the token this session was issued.

        Compared against the value stored on the session rather than against a second
        cookie. The cookie-versus-header form of double submit is defeated by anything
        that can write a cookie for a sibling subdomain — an attacker who sets both
        halves passes a check that only compares them to each other. This one requires
        knowing a secret that was sent to the browser once.
        """
        if not supplied:
            return False
        return secrets.compare_digest(digest(supplied), session.csrf_sha256)


__all__ = [
    "CSRF_COOKIE",
    "CSRF_HEADER",
    "SESSION_COOKIE",
    "SESSION_LIFETIME",
    "AccountService",
    "AuthenticationFailed",
    "EmailAlreadyRegistered",
    "IssuedSession",
    "fold_email",
]
