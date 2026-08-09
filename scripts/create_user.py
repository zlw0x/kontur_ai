"""Make an account from the machine the database is on.

There is no public way to create an `admin`, on purpose: a form that can hand out
the role which reads everybody's drawings is not a form, it is a door. So the first
one is made here, by somebody who already has the database credentials, and every
account after that can be made through `POST /api/v1/admin/users`.

    python scripts/create_user.py --email ops@example.com --role admin

The password is read from the `CAD_AI_NEW_PASSWORD` environment variable rather
than from an argument, because an argument is in `ps`, in the shell history, and in
whatever the terminal scrolled back to. It is never printed.

A TOTP secret is printed once for the roles that need one, and only here. Unlike a
password it is stored as itself: verifying a code means recomputing it, so the
server needs the secret and not a hash of it. That is a real difference in what a
stolen database gives an attacker, and it is why this script runs on the machine
rather than over the network.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.accounts import Role, SqlAccountRepository  # noqa: E402
from app.accounts.passwords import WeakPassword  # noqa: E402
from app.accounts.service import AccountService, EmailAlreadyRegistered  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import create_session_factory  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument(
        "--role",
        default=Role.CUSTOMER.value,
        choices=[role.value for role in Role],
    )
    parser.add_argument(
        "--database-url",
        default=settings.database_url,
        help="defaults to the API's own configuration",
    )
    arguments = parser.parse_args(argv)

    password = os.environ.get("CAD_AI_NEW_PASSWORD")
    if not password:
        print(
            "set CAD_AI_NEW_PASSWORD; a password given as an argument is in `ps` "
            "and in the shell history",
            file=sys.stderr,
        )
        return 2

    _, sessions = create_session_factory(arguments.database_url)
    service = AccountService(SqlAccountRepository(sessions))
    try:
        user, secret = service.register(arguments.email, password, Role(arguments.role))
    except EmailAlreadyRegistered:
        print(f"{arguments.email} already has an account", file=sys.stderr)
        return 1
    except WeakPassword as refused:
        print(str(refused), file=sys.stderr)
        return 1

    print(f"created {user.email} as {user.role.value} ({user.id})")
    if secret:
        # Once. It is stored to verify against rather than to display, and printing
        # it on a later run would make that untrue.
        print(f"TOTP secret (enrol it now, it is not shown again): {secret}")
    return 0


if __name__ == "__main__":  # pragma: no cover - the entry point itself
    raise SystemExit(main())
