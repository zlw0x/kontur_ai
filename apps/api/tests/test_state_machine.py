from datetime import datetime, timezone
from itertools import product
from uuid import uuid4

import pytest

from app.contracts import OrderStatus
from app.orders.state_machine import (
    ALLOWED_TRANSITIONS,
    InvalidStateTransition,
    OrderRecord,
    OrderStateService,
    OrderVersionConflict,
)


def order(status: OrderStatus, version: int = 7) -> OrderRecord:
    return OrderRecord(uuid4(), status, version, datetime(2026, 7, 27, tzinfo=timezone.utc))


def test_every_documented_transition_is_accepted_and_audited():
    service = OrderStateService(clock=lambda: datetime(2026, 7, 28, tzinfo=timezone.utc))
    for source, targets in ALLOWED_TRANSITIONS.items():
        for target in targets:
            updated, event = service.transition(order(source), target=target, expected_version=7, reason="test")
            assert (updated.status, updated.version) == (target, 8)
            assert (event.previous_status, event.current_status, event.previous_version, event.current_version) == (source, target, 7, 8)


def test_every_undocumented_transition_is_rejected():
    service = OrderStateService()
    for source, target in product(OrderStatus, repeat=2):
        if target in ALLOWED_TRANSITIONS[source]:
            continue
        with pytest.raises(InvalidStateTransition):
            service.transition(order(source), target=target, expected_version=7)


def test_stale_version_is_rejected_before_transition_validation():
    with pytest.raises(OrderVersionConflict):
        OrderStateService().transition(order(OrderStatus.DRAFT), target=OrderStatus.UPLOADED, expected_version=6)


@pytest.mark.parametrize("terminal", [OrderStatus.READY, OrderStatus.FAILED, OrderStatus.CANCELLED, OrderStatus.EXPIRED])
def test_terminal_states_have_no_outgoing_transition(terminal: OrderStatus):
    assert ALLOWED_TRANSITIONS[terminal] == frozenset()
