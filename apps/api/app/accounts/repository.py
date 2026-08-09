"""Where accounts and sessions are kept, in the two shapes the service runs in.

The same split as orders and the worker protocol, for the same reason: the isolated
API tests need a store with no database behind it, and what actually runs is SQL.
Two implementations of one protocol, and both are exercised — a repository that
works only in memory is a repository nobody has.

Nothing here decides anything. Hashing, expiry, whether a role needs a second
factor: all of that is `service.py`, and this reads and writes rows.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable, Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.accounts.models import SessionRow, UserRow
from app.accounts.principal import Role


@dataclass(frozen=True)
class UserRecord:
    id: UUID
    email: str
    email_folded: str
    password_hash: str
    role: Role
    totp_secret: str | None
    created_at: datetime
    disabled_at: datetime | None = None
    failed_sign_ins: int = 0
    locked_until: datetime | None = None


@dataclass(frozen=True)
class SessionRecord:
    id: UUID
    user_id: UUID
    token_sha256: str
    csrf_sha256: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None


class AccountRepository(Protocol):
    def create_user(
        self,
        *,
        email: str,
        email_folded: str,
        password_hash: str,
        role: Role,
        totp_secret: str | None,
    ) -> UserRecord: ...

    def user(self, user_id: UUID) -> UserRecord | None: ...

    def user_by_email(self, email_folded: str) -> UserRecord | None: ...

    def create_session(
        self,
        *,
        user_id: UUID,
        token_sha256: str,
        csrf_sha256: str,
        expires_at: datetime,
    ) -> SessionRecord: ...

    def session_by_token(self, token_sha256: str) -> SessionRecord | None: ...

    def rotate_csrf(self, session_id: UUID, csrf_sha256: str) -> None: ...

    def revoke_session(self, session_id: UUID) -> None: ...

    def revoke_sessions_of(self, user_id: UUID) -> int: ...

    def record_sign_in_failure(self, user_id: UUID, *, lock_until: datetime | None) -> int: ...

    def clear_sign_in_failures(self, user_id: UUID) -> None: ...


class InMemoryAccountRepository:
    """For the isolated API tests. Holds records, not rows."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._users: dict[UUID, UserRecord] = {}
        self._sessions: dict[UUID, SessionRecord] = {}

    def create_user(
        self,
        *,
        email: str,
        email_folded: str,
        password_hash: str,
        role: Role,
        totp_secret: str | None,
    ) -> UserRecord:
        if any(user.email_folded == email_folded for user in self._users.values()):
            # What the UNIQUE constraint does in SQL, raised the same way, so the two
            # implementations answer a duplicate identically. The in-memory one being
            # the more forgiving of the pair would be exactly backwards: the tests run
            # on this and production runs on the other.
            raise IntegrityError("users", None, Exception(f"{email_folded} already exists"))
        record = UserRecord(
            id=uuid4(),
            email=email,
            email_folded=email_folded,
            password_hash=password_hash,
            role=role,
            totp_secret=totp_secret,
            created_at=self._clock(),
            disabled_at=None,
        )
        self._users[record.id] = record
        return record

    def user(self, user_id: UUID) -> UserRecord | None:
        return self._users.get(user_id)

    def user_by_email(self, email_folded: str) -> UserRecord | None:
        for user in self._users.values():
            if user.email_folded == email_folded:
                return user
        return None

    def create_session(
        self,
        *,
        user_id: UUID,
        token_sha256: str,
        csrf_sha256: str,
        expires_at: datetime,
    ) -> SessionRecord:
        record = SessionRecord(
            id=uuid4(),
            user_id=user_id,
            token_sha256=token_sha256,
            csrf_sha256=csrf_sha256,
            created_at=self._clock(),
            expires_at=expires_at,
            revoked_at=None,
        )
        self._sessions[record.id] = record
        return record

    def session_by_token(self, token_sha256: str) -> SessionRecord | None:
        for session in self._sessions.values():
            if session.token_sha256 == token_sha256:
                return session
        return None

    def rotate_csrf(self, session_id: UUID, csrf_sha256: str) -> None:
        current = self._sessions.get(session_id)
        if current is not None:
            self._sessions[session_id] = replace(current, csrf_sha256=csrf_sha256)

    def revoke_session(self, session_id: UUID) -> None:
        current = self._sessions.get(session_id)
        if current is None or current.revoked_at is not None:
            return
        self._sessions[session_id] = replace(current, revoked_at=self._clock())

    def record_sign_in_failure(self, user_id: UUID, *, lock_until: datetime | None) -> int:
        current = self._users[user_id]
        updated = replace(
            current,
            failed_sign_ins=current.failed_sign_ins + 1,
            locked_until=lock_until if lock_until is not None else current.locked_until,
        )
        self._users[user_id] = updated
        return updated.failed_sign_ins

    def clear_sign_in_failures(self, user_id: UUID) -> None:
        current = self._users.get(user_id)
        if current is not None and (current.failed_sign_ins or current.locked_until):
            self._users[user_id] = replace(current, failed_sign_ins=0, locked_until=None)

    def revoke_sessions_of(self, user_id: UUID) -> int:
        now, revoked = self._clock(), 0
        for key, session in list(self._sessions.items()):
            if session.user_id == user_id and session.revoked_at is None:
                self._sessions[key] = replace(session, revoked_at=now)
                revoked += 1
        return revoked


class SqlAccountRepository:
    """What runs. One transaction per call."""

    def __init__(self, session_factory, clock: Callable[[], datetime] | None = None) -> None:
        self.sessions = session_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def create_user(
        self,
        *,
        email: str,
        email_folded: str,
        password_hash: str,
        role: Role,
        totp_secret: str | None,
    ) -> UserRecord:
        with self.sessions.begin() as session:
            row = UserRow(
                id=str(uuid4()),
                email=email,
                email_folded=email_folded,
                password_hash=password_hash,
                role=role.value,
                totp_secret=totp_secret,
                created_at=self._clock(),
                disabled_at=None,
                failed_sign_ins=0,
                locked_until=None,
            )
            session.add(row)
            session.flush()
            return _user(row)

    def user(self, user_id: UUID) -> UserRecord | None:
        with self.sessions.begin() as session:
            row = session.get(UserRow, str(user_id))
            return _user(row) if row is not None else None

    def user_by_email(self, email_folded: str) -> UserRecord | None:
        with self.sessions.begin() as session:
            row = session.scalar(select(UserRow).where(UserRow.email_folded == email_folded))
            return _user(row) if row is not None else None

    def create_session(
        self,
        *,
        user_id: UUID,
        token_sha256: str,
        csrf_sha256: str,
        expires_at: datetime,
    ) -> SessionRecord:
        with self.sessions.begin() as session:
            row = SessionRow(
                id=str(uuid4()),
                user_id=str(user_id),
                token_sha256=token_sha256,
                csrf_sha256=csrf_sha256,
                created_at=self._clock(),
                expires_at=expires_at,
                revoked_at=None,
            )
            session.add(row)
            session.flush()
            return _session(row)

    def session_by_token(self, token_sha256: str) -> SessionRecord | None:
        with self.sessions.begin() as session:
            row = session.scalar(
                select(SessionRow).where(SessionRow.token_sha256 == token_sha256)
            )
            return _session(row) if row is not None else None

    def rotate_csrf(self, session_id: UUID, csrf_sha256: str) -> None:
        with self.sessions.begin() as session:
            row = session.get(SessionRow, str(session_id))
            if row is not None:
                row.csrf_sha256 = csrf_sha256

    def revoke_session(self, session_id: UUID) -> None:
        with self.sessions.begin() as session:
            row = session.get(SessionRow, str(session_id))
            if row is not None and row.revoked_at is None:
                row.revoked_at = self._clock()

    def record_sign_in_failure(self, user_id: UUID, *, lock_until: datetime | None) -> int:
        with self.sessions.begin() as session:
            # Locked for the increment, so two wrong passwords arriving together
            # count as two. Without it the read-modify-write is the interleaving
            # that lets a parallel attacker have as many tries as they have
            # connections — which is the whole thing being prevented.
            row = session.get(UserRow, str(user_id), with_for_update=True)
            if row is None:
                return 0
            row.failed_sign_ins = (row.failed_sign_ins or 0) + 1
            if lock_until is not None:
                row.locked_until = lock_until
            return row.failed_sign_ins

    def clear_sign_in_failures(self, user_id: UUID) -> None:
        with self.sessions.begin() as session:
            row = session.get(UserRow, str(user_id), with_for_update=True)
            if row is not None and (row.failed_sign_ins or row.locked_until):
                row.failed_sign_ins, row.locked_until = 0, None

    def revoke_sessions_of(self, user_id: UUID) -> int:
        with self.sessions.begin() as session:
            rows = session.scalars(
                select(SessionRow).where(
                    SessionRow.user_id == str(user_id), SessionRow.revoked_at.is_(None)
                )
            ).all()
            now = self._clock()
            for row in rows:
                row.revoked_at = now
            return len(rows)


def _user(row: UserRow) -> UserRecord:
    return UserRecord(
        id=UUID(row.id),
        email=row.email,
        email_folded=row.email_folded,
        password_hash=row.password_hash,
        role=Role(row.role),
        totp_secret=row.totp_secret,
        created_at=_aware(row.created_at),
        disabled_at=_aware(row.disabled_at),
        failed_sign_ins=row.failed_sign_ins or 0,
        locked_until=_aware(row.locked_until),
    )


def _session(row: SessionRow) -> SessionRecord:
    return SessionRecord(
        id=UUID(row.id),
        user_id=UUID(row.user_id),
        token_sha256=row.token_sha256,
        csrf_sha256=row.csrf_sha256,
        created_at=_aware(row.created_at),
        expires_at=_aware(row.expires_at),
        revoked_at=_aware(row.revoked_at),
    )


def _aware(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; PostgreSQL does not.

    Comparing a naive expiry against an aware `now` raises `TypeError`, which would
    be a 500 on every authenticated request under the in-memory configuration and
    nothing at all under the real one — the worst possible split, since the tests
    run on the former. UTC is the right assumption because it is the only thing
    written into these columns.
    """
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


__all__ = [
    "AccountRepository",
    "InMemoryAccountRepository",
    "SessionRecord",
    "SqlAccountRepository",
    "UserRecord",
]
