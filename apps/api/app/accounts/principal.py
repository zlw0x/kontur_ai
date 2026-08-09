"""Who is asking, and the one place that decides what they may see.

Until this existed the answer was `authenticated_manual_api`: one static token,
shared by everyone who had it, and an `orders` table with no column saying whose
an order was. Anybody holding the token could read and cancel anybody's order.
That is the single thing that blocked letting strangers in, and it is not fixed by
adding a check to each endpoint — thirty checks are thirty chances to forget one.

So there is exactly one function that answers "may this principal see this order",
and every path goes through it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class Role(StrEnum):
    """Three, and no more until something needs a fourth.

    `customer` sees their own orders. `operator` sees every order, because the
    moderation queue is their job and an order they cannot open is one they cannot
    approve. `admin` additionally creates accounts.
    """

    CUSTOMER = "customer"
    OPERATOR = "operator"
    ADMIN = "admin"


#: The roles that must present a second factor.
#:
#: Only the two that can read other people's drawings. A customer's account gets
#: one customer's orders; an operator's account gets everybody's, and a stolen
#: password on one of those is a different size of accident.
MFA_REQUIRED: frozenset[Role] = frozenset({Role.OPERATOR, Role.ADMIN})

#: The roles that may see an order nobody owns, and everybody else's.
STAFF: frozenset[Role] = frozenset({Role.OPERATOR, Role.ADMIN})


@dataclass(frozen=True)
class Principal:
    """The identity behind one request.

    `user_id` is None for the manual operator key, which is not a person: it is
    `MANUAL_API_TOKEN`, and this service's standing rule is that it is a
    **diagnostic operator key and never a client authorization**. Giving it the
    operator role rather than a customer's is what keeps that true — it can look at
    everything, the way an operator can, and it owns nothing, so nothing it creates
    becomes some phantom user's order.
    """

    role: Role
    user_id: UUID | None = None
    session_id: UUID | None = None
    #: Whether the credential travelled in a cookie, which is the only kind a
    #: browser attaches to a request the user did not make. CSRF is checked for
    #: those and not for a header token, which no cross-origin page can set.
    from_cookie: bool = False

    @property
    def is_staff(self) -> bool:
        return self.role in STAFF


def may_see_order(principal: Principal, owner_id: UUID | None) -> bool:
    """The whole ownership rule, in one place so there is one thing to get right.

    Two decisions are inside it and both are deliberate.

    **An order with no owner is staff-only.** Every order created before this
    migration has `owner_id IS NULL` and there is nothing to fill it with — the
    service did not record who uploaded them because it had no idea. Guessing would
    be worse than admitting it, and handing them to whoever asks first is not a
    guess but a giveaway. So they are visible to an operator, who can already see
    everything, and to nobody else.

    **A customer's own order is the only thing they see.** Not "orders they created
    plus anything unclaimed": an order without an owner is not an invitation.
    """
    if principal.is_staff:
        return True
    if owner_id is None or principal.user_id is None:
        return False
    return owner_id == principal.user_id


#: The principal a request has when it presented nothing at all.
#:
#: Not a role — an absence. Kept as a value rather than as `None` so a caller that
#: forgets to check gets an authenticated-as-nobody that fails every ownership test,
#: instead of an `AttributeError` on `None.role` that a handler might catch.
ANONYMOUS = Principal(role=Role.CUSTOMER, user_id=None, session_id=None)


__all__ = ["ANONYMOUS", "MFA_REQUIRED", "STAFF", "Principal", "Role", "may_see_order"]
