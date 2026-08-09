"""Accounts, sessions and the one rule that says whose order an order is.

Split out of `app.main` from the start rather than after it grew: authentication
is the part of a service that must be readable in one sitting by somebody who did
not write it.
"""

from app.accounts.principal import ANONYMOUS, Principal, Role, may_see_order
from app.accounts.repository import (
    AccountRepository,
    InMemoryAccountRepository,
    SessionRecord,
    SqlAccountRepository,
    UserRecord,
)
from app.accounts.service import (
    CSRF_COOKIE,
    CSRF_HEADER,
    SESSION_COOKIE,
    AccountService,
    AuthenticationFailed,
    EmailAlreadyRegistered,
    IssuedSession,
)

__all__ = [
    "ANONYMOUS",
    "CSRF_COOKIE",
    "CSRF_HEADER",
    "SESSION_COOKIE",
    "AccountRepository",
    "AccountService",
    "AuthenticationFailed",
    "EmailAlreadyRegistered",
    "InMemoryAccountRepository",
    "IssuedSession",
    "Principal",
    "Role",
    "SessionRecord",
    "SqlAccountRepository",
    "UserRecord",
    "may_see_order",
]
