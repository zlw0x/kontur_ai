"""A stuck order must be explainable.

Every case here is one a user could actually hit, and the point of each is that
the API says *which* of them it is. "Waiting" with no reason is the failure
this module exists to remove.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts import (
    CapabilityDeclaration,
    CapabilityRequirement,
    CapabilityStatus,
    ClaimBlockerCode,
    ClaimabilityStatus,
    JobType,
    WorkerCapability,
    WorkerCapabilityManifest,
    capability_version_tuple,
)
from app.workers.capabilities import (
    MVP_CAPABILITIES,
    SOLID_RECTANGULAR_PRISM,
    required_capability_keys,
)
from app.workers.diagnostics import SchedulerDiagnostics
from app.workers.protocol import InMemoryWorkerRepository, Job, WorkerProtocolService
from cad_ir.canonical import CAD_IR_VERSION

ENROLLMENT = "local-development-enrollment-token-change-me"
NOW = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def manifest(statuses=None, versions=None) -> WorkerCapabilityManifest:
    versions = versions or {}
    return WorkerCapabilityManifest(
        worker_version="0.4.0",
        cad_ir_versions=[CAD_IR_VERSION],
        capabilities={
            key: {
                "status": (statuses or {}).get(key, CapabilityStatus.STABLE),
                "version": versions.get(key, "1.0"),
            }
            for key in MVP_CAPABILITIES
        },
    )


def build_job() -> Job:
    return Job(
        uuid4(),
        uuid4(),
        JobType.BUILD_CAD,
        f"sha256:{uuid4()}",
        {WorkerCapability.CAD_BUILD},
        CAD_IR_VERSION,
        required_capability_keys(JobType.BUILD_CAD),
    )


def fixture(app_version: str = "0.4.0"):
    clock = Clock()
    protocol = WorkerProtocolService(InMemoryWorkerRepository(), ENROLLMENT, clock)
    worker, _ = protocol.register(
        enrollment_token=ENROLLMENT, worker_name="local-pc", app_version=app_version
    )
    diagnostics = SchedulerDiagnostics(protocol, clock)
    return protocol, worker, diagnostics, clock


def codes(report) -> set[ClaimBlockerCode]:
    return {blocker.code for blocker in report.blockers}


# --- capability versions ---------------------------------------------------


def test_capability_versions_compare_numerically_not_alphabetically():
    assert capability_version_tuple("1.10") > capability_version_tuple("1.9")
    assert capability_version_tuple("2") > capability_version_tuple("1.99.99")
    assert capability_version_tuple("1.0") == capability_version_tuple("1.0.0")


def test_a_bare_status_string_still_declares_a_capability():
    """Manifests written before versions existed must keep working."""
    declaration = CapabilityDeclaration.model_validate("stable")
    assert declaration.status is CapabilityStatus.STABLE
    assert declaration.version == "1.0"


def test_a_requirement_cannot_ask_for_a_non_maturity_status():
    for impossible in (CapabilityStatus.UNSUPPORTED, CapabilityStatus.DISABLED):
        with pytest.raises(ValidationError):
            CapabilityRequirement(name="solid.rectangular_prism", stability=impossible)


def test_requirement_matching_covers_maturity_and_version():
    requirement = CapabilityRequirement(
        name=SOLID_RECTANGULAR_PRISM, stability=CapabilityStatus.BETA, min_version="1.2"
    )
    assert requirement.satisfied_by(CapabilityDeclaration(status="stable", version="1.2"))
    assert requirement.satisfied_by(CapabilityDeclaration(status="beta", version="1.10"))
    assert not requirement.satisfied_by(CapabilityDeclaration(status="beta", version="1.1"))
    assert not requirement.satisfied_by(CapabilityDeclaration(status="experimental", version="9.0"))
    assert not requirement.satisfied_by(CapabilityDeclaration(status="disabled", version="9.0"))
    assert not requirement.satisfied_by(None)


# --- diagnostics -----------------------------------------------------------


def test_no_enrolled_worker_is_reported_as_such():
    clock = Clock()
    protocol = WorkerProtocolService(InMemoryWorkerRepository(), ENROLLMENT, clock)
    job = build_job()
    protocol.enqueue(job)

    report = SchedulerDiagnostics(protocol, clock).report(job)

    assert report.claimability is ClaimabilityStatus.BLOCKED
    assert report.online_workers == 0
    assert codes(report) == {ClaimBlockerCode.NO_ONLINE_WORKERS}


def test_a_worker_that_never_heartbeats_is_not_counted_as_online():
    protocol, worker, diagnostics, _ = fixture()
    job = build_job()
    protocol.enqueue(job)

    report = diagnostics.report(job)

    assert report.online_workers == 0
    assert ClaimBlockerCode.WORKER_HEARTBEAT_STALE in codes(report)


def test_a_worker_that_stopped_heartbeating_goes_stale():
    protocol, worker, diagnostics, clock = fixture()
    protocol.heartbeat(worker, [WorkerCapability.CAD_BUILD], [CAD_IR_VERSION], 1, manifest())
    job = build_job()
    protocol.enqueue(job)
    assert diagnostics.report(job).claimability is ClaimabilityStatus.CLAIMABLE

    clock.now += timedelta(minutes=10)

    report = diagnostics.report(job)
    assert report.claimability is ClaimabilityStatus.BLOCKED
    assert ClaimBlockerCode.WORKER_HEARTBEAT_STALE in codes(report)
    assert "600 seconds ago" in "".join(item.detail or "" for item in report.blockers)


def test_an_old_worker_without_a_manifest_is_named_precisely():
    """The exact case the capability gate created and left invisible."""
    protocol, worker, diagnostics, _ = fixture()
    protocol.heartbeat(worker, [WorkerCapability.CAD_BUILD], [CAD_IR_VERSION], 1)
    job = build_job()
    protocol.enqueue(job)

    report = diagnostics.report(job)

    assert report.claimability is ClaimabilityStatus.BLOCKED
    assert report.online_workers == 1
    assert report.compatible_workers == 0
    blocker = next(item for item in report.blockers)
    assert blocker.code is ClaimBlockerCode.WORKER_MANIFEST_MISSING
    assert blocker.worker_id == worker.id
    assert blocker.worker_name == "local-pc"


def test_an_unsupported_capability_names_the_capability():
    protocol, worker, diagnostics, _ = fixture()
    incomplete = manifest()
    incomplete.capabilities.pop(SOLID_RECTANGULAR_PRISM)
    protocol.heartbeat(worker, [WorkerCapability.CAD_BUILD], [CAD_IR_VERSION], 1, incomplete)
    job = build_job()
    protocol.enqueue(job)

    report = diagnostics.report(job)

    blocker = next(item for item in report.blockers if item.capability == SOLID_RECTANGULAR_PRISM)
    assert blocker.code is ClaimBlockerCode.CAPABILITY_NOT_SUPPORTED


def test_experimental_only_is_distinguished_from_unsupported():
    protocol, worker, diagnostics, _ = fixture()
    protocol.heartbeat(
        worker,
        [WorkerCapability.CAD_BUILD],
        [CAD_IR_VERSION],
        1,
        manifest(statuses={SOLID_RECTANGULAR_PRISM: CapabilityStatus.EXPERIMENTAL}),
    )
    job = build_job()
    protocol.enqueue(job)

    report = diagnostics.report(job)

    assert report.claimability is ClaimabilityStatus.BLOCKED
    blocker = next(item for item in report.blockers if item.capability == SOLID_RECTANGULAR_PRISM)
    # Not the same problem as "cannot do it": the operation exists but is not
    # trusted for an ordinary claim yet.
    assert blocker.code is ClaimBlockerCode.CAPABILITY_EXPERIMENTAL_ONLY


def test_an_outdated_capability_version_is_its_own_reason():
    protocol, worker, diagnostics, _ = fixture()
    requirement = CapabilityRequirement(name=SOLID_RECTANGULAR_PRISM, min_version="2.0")
    protocol.heartbeat(
        worker,
        [WorkerCapability.CAD_BUILD],
        [CAD_IR_VERSION],
        1,
        manifest(versions={SOLID_RECTANGULAR_PRISM: "1.0"}),
    )
    job = build_job()
    protocol.enqueue(job)

    from app.workers import capabilities as registry

    original = registry.CAPABILITY_REQUIREMENTS[SOLID_RECTANGULAR_PRISM]
    registry.CAPABILITY_REQUIREMENTS[SOLID_RECTANGULAR_PRISM] = requirement
    try:
        report = diagnostics.report(job)
    finally:
        registry.CAPABILITY_REQUIREMENTS[SOLID_RECTANGULAR_PRISM] = original

    blocker = next(item for item in report.blockers if item.capability == SOLID_RECTANGULAR_PRISM)
    assert blocker.code is ClaimBlockerCode.CAPABILITY_VERSION_TOO_OLD
    assert "requires at least 2.0" in blocker.detail


def test_an_old_worker_build_is_rejected_before_its_capabilities_are_read():
    protocol, worker, diagnostics, _ = fixture(app_version="0.2.0")
    protocol.heartbeat(worker, [WorkerCapability.CAD_BUILD], [CAD_IR_VERSION], 1, manifest())
    job = build_job()
    protocol.enqueue(job)

    report = diagnostics.report(job)

    assert codes(report) == {ClaimBlockerCode.WORKER_VERSION_INCOMPATIBLE}


def test_a_busy_but_capable_worker_reports_capacity_not_incapability():
    protocol, worker, diagnostics, _ = fixture()
    protocol.heartbeat(worker, [WorkerCapability.CAD_BUILD], [CAD_IR_VERSION], 0, manifest())
    job = build_job()
    protocol.enqueue(job)

    report = diagnostics.report(job)

    assert codes(report) == {ClaimBlockerCode.WORKER_LEASE_CAPACITY_EXHAUSTED}
    assert report.summary == "The order is waiting for the modelling module to finish another job."


def test_a_job_requiring_unknown_vocabulary_blames_the_job_not_the_fleet():
    protocol, worker, diagnostics, _ = fixture()
    protocol.heartbeat(worker, [WorkerCapability.CAD_BUILD], [CAD_IR_VERSION], 1, manifest())
    job = build_job()
    job.required_capability_keys = ["surface.loft"]
    protocol.enqueue(job)

    report = diagnostics.report(job)

    assert codes(report) == {ClaimBlockerCode.JOB_REQUIREMENTS_INVALID}
    assert report.blockers[0].worker_id is None
    assert report.summary == "This order needs an operation the service does not offer yet."


def test_publishing_a_compatible_manifest_unblocks_without_touching_the_job():
    protocol, worker, diagnostics, _ = fixture()
    protocol.heartbeat(worker, [WorkerCapability.CAD_BUILD], [CAD_IR_VERSION], 1)
    job = build_job()
    protocol.enqueue(job)
    before = diagnostics.report(job)
    assert before.claimability is ClaimabilityStatus.BLOCKED

    protocol.heartbeat(worker, [WorkerCapability.CAD_BUILD], [CAD_IR_VERSION], 1, manifest())

    after = diagnostics.report(job)
    assert after.claimability is ClaimabilityStatus.CLAIMABLE
    assert after.compatible_workers == 1
    assert after.blockers == []
    # The job itself was never rewritten; claimability is derived state.
    assert job.status.value == "PENDING"
    assert job.attempt == 0


def test_one_capable_worker_makes_the_job_claimable_despite_an_incapable_peer():
    protocol, capable, diagnostics, _ = fixture()
    incapable, _ = protocol.register(
        enrollment_token=ENROLLMENT, worker_name="old-pc", app_version="0.4.0"
    )
    protocol.heartbeat(capable, [WorkerCapability.CAD_BUILD], [CAD_IR_VERSION], 1, manifest())
    protocol.heartbeat(incapable, [WorkerCapability.CAD_BUILD], [CAD_IR_VERSION], 1)
    job = build_job()
    protocol.enqueue(job)

    report = diagnostics.report(job)

    assert report.claimability is ClaimabilityStatus.CLAIMABLE
    assert report.online_workers == 2
    assert report.compatible_workers == 1
    assert report.blockers == []


def test_a_leased_job_is_in_progress_rather_than_blocked():
    protocol, worker, diagnostics, _ = fixture()
    protocol.heartbeat(worker, [WorkerCapability.CAD_BUILD], [CAD_IR_VERSION], 1, manifest())
    job = build_job()
    protocol.enqueue(job)
    protocol.claim(worker)

    report = diagnostics.report(job)

    assert report.claimability is ClaimabilityStatus.IN_PROGRESS
    assert report.blockers == []
    assert report.summary == "The order is being modelled."


def test_a_completed_job_is_settled():
    protocol, worker, diagnostics, _ = fixture()
    protocol.heartbeat(worker, [WorkerCapability.CAD_BUILD], [CAD_IR_VERSION], 1, manifest())
    job = build_job()
    protocol.enqueue(job)
    protocol.claim(worker)
    protocol.complete(worker, job.id, job.idempotency_key)

    assert diagnostics.report(job).claimability is ClaimabilityStatus.SETTLED


def test_diagnosing_a_job_never_leases_or_mutates_it():
    protocol, worker, diagnostics, _ = fixture()
    protocol.heartbeat(worker, [WorkerCapability.CAD_BUILD], [CAD_IR_VERSION], 1, manifest())
    job = build_job()
    protocol.enqueue(job)

    for _ in range(5):
        diagnostics.report(job)

    assert job.status.value == "PENDING"
    assert job.attempt == 0
    assert job.lease_owner is None
    # The job is still there to be claimed for real.
    assert protocol.claim(worker) is not None
