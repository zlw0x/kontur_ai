"""Optional capabilities are registered vocabulary, not universal requirements.

An operation added after the MVP has to be nameable, so a worker can declare it
and a feature flag can turn it off. It must *not* become something every job
demands: a part that is a plain rectangle needs no arcs, and requiring them would
mean a worker with arcs turned off could build nothing at all.
"""

from uuid import uuid4

import pytest

from app.contracts import (
    CapabilityDeclaration,
    CapabilityStatus,
    JobType,
    WorkerCapabilityManifest,
)
from app.workers.capabilities import (
    BASELINE_CAPABILITIES,
    CAPABILITY_REQUIREMENTS,
    OPTIONAL_CAPABILITIES,
    SKETCH_ARC,
    required_capability_keys,
    unknown_capabilities,
)
from cad_ir.canonical import CAD_IR_VERSION


def manifest(**overrides) -> WorkerCapabilityManifest:
    capabilities = {
        key: CapabilityDeclaration(status=CapabilityStatus.STABLE, version="1.0")
        for key in BASELINE_CAPABILITIES
    }
    capabilities.update(
        {
            key: CapabilityDeclaration(status=CapabilityStatus.BETA, version="1.0")
            for key in OPTIONAL_CAPABILITIES
        }
    )
    capabilities.update(overrides)
    return WorkerCapabilityManifest(
        worker_version="0.4.0",
        kompas_version="22.0",
        cad_ir_versions=[CAD_IR_VERSION],
        capabilities=capabilities,
    )


def test_every_optional_capability_is_registered_vocabulary():
    """A worker cannot declare something the API has never heard of, and a flag
    cannot turn off something that was never registered."""
    assert unknown_capabilities(list(OPTIONAL_CAPABILITIES)) == []
    for key in OPTIONAL_CAPABILITIES:
        assert key in CAPABILITY_REQUIREMENTS


@pytest.mark.parametrize("job_type", [JobType.BUILD_CAD, JobType.ANALYZE_DRAWING])
def test_no_job_demands_an_optional_capability_of_every_worker(job_type):
    """The one that matters. If an optional operation crept into the per-job
    requirements, turning it off would stop the worker from being offered any
    work at all rather than stopping that operation."""
    required = set(required_capability_keys(job_type))

    assert required == set(BASELINE_CAPABILITIES)
    assert required.isdisjoint(OPTIONAL_CAPABILITIES)


def test_a_worker_with_an_optional_operation_disabled_still_gets_work():
    """A rollback narrows what the worker will build; it does not take the
    worker offline."""
    from app.workers.protocol import InMemoryWorkerRepository, Job, WorkerProtocolService

    enrollment = "local-development-enrollment-token-change-me"
    service = WorkerProtocolService(InMemoryWorkerRepository(), enrollment)
    worker, _ = service.register(
        enrollment_token=enrollment, worker_name="w", app_version="0.4.0"
    )
    disabled = manifest(
        **{SKETCH_ARC: CapabilityDeclaration(status=CapabilityStatus.DISABLED, version="1.0")}
    )
    service.heartbeat(worker, list(BASELINE_CAPABILITIES), [CAD_IR_VERSION], 1, disabled)
    job = Job(
        uuid4(),
        uuid4(),
        JobType.BUILD_CAD,
        f"sha256:{uuid4()}",
        set(),
        CAD_IR_VERSION,
        list(BASELINE_CAPABILITIES),
    )
    service.enqueue(job)

    claimed = service.claim(worker)

    assert claimed is not None and claimed.id == job.id


def test_a_worker_with_a_baseline_operation_disabled_gets_nothing():
    """The other half. `disabled` is not a low rung on the maturity ladder: it
    is "no", so a baseline operation turned off stops the work."""
    from app.workers.capabilities import SOLID_RECTANGULAR_PRISM
    from app.workers.protocol import InMemoryWorkerRepository, Job, WorkerProtocolService

    enrollment = "local-development-enrollment-token-change-me"
    service = WorkerProtocolService(InMemoryWorkerRepository(), enrollment)
    worker, _ = service.register(
        enrollment_token=enrollment, worker_name="w", app_version="0.4.0"
    )
    disabled = manifest(
        **{
            SOLID_RECTANGULAR_PRISM: CapabilityDeclaration(
                status=CapabilityStatus.DISABLED, version="1.0"
            )
        }
    )
    service.heartbeat(worker, list(BASELINE_CAPABILITIES), [CAD_IR_VERSION], 1, disabled)
    service.enqueue(
        Job(
            uuid4(),
            uuid4(),
            JobType.BUILD_CAD,
            f"sha256:{uuid4()}",
            set(),
            CAD_IR_VERSION,
            list(BASELINE_CAPABILITIES),
        )
    )

    assert service.claim(worker) is None


def test_the_old_name_still_points_at_the_baseline():
    """`MVP_CAPABILITIES` is read across the codebase and its tests; renaming it
    outright would be churn for no gain."""
    from app.workers.capabilities import MVP_CAPABILITIES

    assert MVP_CAPABILITIES == BASELINE_CAPABILITIES
