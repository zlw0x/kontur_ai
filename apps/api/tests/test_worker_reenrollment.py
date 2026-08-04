"""Re-enrolling a machine that is already known has to work.

A worker that was rebuilt, or whose credential was lost, has to be able to come
back. Before this, a second `enroll` from the same machine hit a unique
constraint on the worker name and surfaced as a bare "enrollment was rejected" —
which sends an operator to look at their token instead of at their worker list.
"""

import pytest

from app.contracts import ErrorCode
from app.database import Base, create_session_factory
from app.workers.protocol import (
    InMemoryWorkerRepository,
    WorkerProtocolError,
    WorkerProtocolService,
)
from app.workers.sql_protocol import SqlWorkerProtocolService

ENROLLMENT = "local-development-enrollment-token-change-me"


def memory():
    return WorkerProtocolService(InMemoryWorkerRepository(), ENROLLMENT)


def sql():
    engine, sessions = create_session_factory("sqlite://")
    Base.metadata.create_all(engine)
    return SqlWorkerProtocolService(sessions, ENROLLMENT)


@pytest.fixture(params=["memory", "sql"])
def service(request):
    return memory() if request.param == "memory" else sql()


def enroll(service, name="DESKTOP-TEST"):
    return service.register(enrollment_token=ENROLLMENT, worker_name=name, app_version="0.4.0")


def test_a_first_enrollment_issues_a_credential(service):
    worker, credential = enroll(service)

    assert service.authenticate(worker.id, credential).name == "DESKTOP-TEST"


def test_re_enrolling_the_same_machine_keeps_its_identity(service):
    """The same machine is the same worker. A new id would leave the old row
    behind, still counted as a worker that never checks in."""
    first, _ = enroll(service)
    second, credential = enroll(service)

    assert second.id == first.id
    assert service.authenticate(second.id, credential).id == first.id


def test_re_enrolling_invalidates_the_previous_credential(service):
    """A rotation that left the old credential valid would be a way to keep a
    stale worker alive unnoticed."""
    worker, old_credential = enroll(service)
    _, new_credential = enroll(service)

    assert service.authenticate(worker.id, new_credential).id == worker.id
    with pytest.raises(WorkerProtocolError) as caught:
        service.authenticate(worker.id, old_credential)
    assert caught.value.code is ErrorCode.WORKER_AUTH_FAILED


def test_a_different_machine_name_is_a_different_worker(service):
    first, _ = enroll(service, "DESKTOP-ONE")
    second, _ = enroll(service, "DESKTOP-TWO")

    assert first.id != second.id


def test_a_wrong_enrollment_token_is_still_refused(service):
    """The rotation grants nothing new: the token is still the thing that
    authorises enrolling at all."""
    with pytest.raises(WorkerProtocolError) as caught:
        service.register(
            enrollment_token="not-the-token", worker_name="DESKTOP-TEST", app_version="0.4.0"
        )
    assert caught.value.code is ErrorCode.ENROLLMENT_REJECTED


def test_re_enrolling_clears_what_the_old_worker_had_published():
    """Capabilities and slots belong to a running worker, not to a name. Keeping
    them would let the API schedule work to a machine that has not checked in
    since it was rebuilt."""
    from app.contracts import WorkerCapability
    from cad_ir.canonical import CAD_IR_VERSION

    service = sql()
    worker, _ = enroll(service)
    service.heartbeat(worker, [WorkerCapability.CAD_BUILD], [CAD_IR_VERSION], 1)

    reborn, _ = enroll(service)

    with service.sessions() as session:
        from app.workers.models import WorkerRow

        row = session.get(WorkerRow, str(reborn.id))
        assert row.available_slots == 0
        assert row.capabilities == []
        assert row.supported_cad_ir == []
        assert row.last_seen_at is None
