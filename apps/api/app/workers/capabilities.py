"""The capability registry (POSTMVP-003) and its diagnostics (POSTMVP-003A).

A worker declares what its installed KOMPAS and adapter can actually build.
The API refuses to lease a job whose operations the worker cannot serve, so an
unsupported feature fails at scheduling time with a typed reason instead of
halfway through a CAD session on the user's machine.

Keys are versioned vocabulary, not free text: adding one here is the deliberate
step that makes a new operation schedulable.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.contracts import (
    CAPABILITY_MATURITY,
    CapabilityDeclaration,
    CapabilityRequirement,
    CapabilityStatus,
    ClaimBlocker,
    ClaimBlockerCode,
    JobType,
    WorkerCapabilityManifest,
    capability_version_tuple,
)

SOLID_RECTANGULAR_PRISM = "solid.rectangular_prism"
FEATURE_HOLE_SIMPLE_THROUGH = "feature.hole.simple_through"
EXPORT_M3D = "export.m3d"
EXPORT_STEP = "export.step"
EXPORT_STL = "export.stl"
VALIDATE_MANIFOLD = "validate.manifold"
VALIDATE_BOUNDING_BOX = "validate.bounding_box"
VALIDATE_HOLE_COUNT = "validate.hole_count"

#: Everything the confirmed MVP pipeline exercises. A worker that cannot serve
#: all of these cannot complete a BUILD_CAD or ANALYZE_DRAWING job at all.
MVP_CAPABILITIES: tuple[str, ...] = (
    SOLID_RECTANGULAR_PRISM,
    FEATURE_HOLE_SIMPLE_THROUGH,
    EXPORT_M3D,
    EXPORT_STEP,
    EXPORT_STL,
    VALIDATE_MANIFOLD,
    VALIDATE_BOUNDING_BOX,
    VALIDATE_HOLE_COUNT,
)

#: What the API demands of each capability. Version and maturity requirements
#: belong to the vocabulary rather than to an individual job: every job using
#: an operation needs the same behaviour from it.
CAPABILITY_REQUIREMENTS: dict[str, CapabilityRequirement] = {
    name: CapabilityRequirement(name=name, stability=CapabilityStatus.BETA, min_version="1.0")
    for name in MVP_CAPABILITIES
}

#: Oldest worker build the API will hand work to.
MINIMUM_WORKER_VERSION = "0.4.0"

#: A worker polls every few seconds; well past this it is not coming back for
#: the current job, and calling it "online" would misexplain a stuck order.
WORKER_ONLINE_WINDOW = timedelta(seconds=90)

_JOB_REQUIREMENTS: dict[JobType, tuple[str, ...]] = {
    JobType.BUILD_CAD: MVP_CAPABILITIES,
    JobType.ANALYZE_DRAWING: MVP_CAPABILITIES,
    JobType.COMPILE_CAD_IR: (),
    JobType.VALIDATE_CAD: (
        VALIDATE_MANIFOLD,
        VALIDATE_BOUNDING_BOX,
        VALIDATE_HOLE_COUNT,
    ),
}


def required_capability_keys(job_type: JobType) -> list[str]:
    return list(_JOB_REQUIREMENTS.get(job_type, ()))


def requirements_for(keys: list[str]) -> list[CapabilityRequirement]:
    """Resolve capability keys to their registered requirements.

    An unregistered key yields no requirement; `unknown_capabilities` reports
    it separately so it surfaces as JOB_REQUIREMENTS_INVALID rather than being
    quietly treated as satisfied.
    """
    return [CAPABILITY_REQUIREMENTS[key] for key in keys if key in CAPABILITY_REQUIREMENTS]


def unknown_capabilities(keys: list[str]) -> list[str]:
    return [key for key in keys if key not in CAPABILITY_REQUIREMENTS]


def unmet_capabilities(
    manifest: WorkerCapabilityManifest | None, required: list[str]
) -> list[str]:
    """Which of `required` the worker cannot serve.

    A worker that has published no manifest can serve nothing new: it is
    either an old build or one that has not completed a heartbeat, and
    guessing on its behalf is how an unsupported job reaches KOMPAS.
    """
    if not required:
        return []
    if manifest is None:
        return list(required)
    unmet = unknown_capabilities(required)
    for requirement in requirements_for(required):
        if not requirement.satisfied_by(manifest.declared(requirement.name)):
            unmet.append(requirement.name)
    return unmet


def worker_version_accepted(worker_version: str) -> bool:
    try:
        return capability_version_tuple(worker_version) >= capability_version_tuple(
            MINIMUM_WORKER_VERSION
        )
    except ValueError:
        # An unparsable version is not evidence of a new enough build.
        return False


def is_online(last_seen_at: datetime | None, now: datetime, window: timedelta) -> bool:
    return last_seen_at is not None and now - last_seen_at <= window


def capability_blockers(
    manifest: WorkerCapabilityManifest,
    required: list[str],
) -> list[ClaimBlocker]:
    """Explain, per capability, why this manifest does not satisfy `required`.

    The distinction between "cannot do it", "only has it as experimental" and
    "has an older version" is the whole point: the three call for completely
    different actions from whoever is looking at a stuck order.
    """
    blockers: list[ClaimBlocker] = []
    for name in unknown_capabilities(required):
        blockers.append(
            ClaimBlocker(
                code=ClaimBlockerCode.JOB_REQUIREMENTS_INVALID,
                capability=name,
                detail="capability is not in the registry vocabulary",
            )
        )
    for requirement in requirements_for(required):
        declared = manifest.declared(requirement.name)
        if requirement.satisfied_by(declared):
            continue
        blockers.append(_capability_blocker(requirement, declared))
    return blockers


def _capability_blocker(
    requirement: CapabilityRequirement, declared: CapabilityDeclaration | None
) -> ClaimBlocker:
    if declared is None or declared.status not in CAPABILITY_MATURITY:
        return ClaimBlocker(
            code=ClaimBlockerCode.CAPABILITY_NOT_SUPPORTED,
            capability=requirement.name,
            detail=(
                "not declared" if declared is None else f"declared as {declared.status}"
            ),
        )
    if CAPABILITY_MATURITY[declared.status] < CAPABILITY_MATURITY[requirement.stability]:
        return ClaimBlocker(
            code=ClaimBlockerCode.CAPABILITY_EXPERIMENTAL_ONLY,
            capability=requirement.name,
            detail=f"declared {declared.status}, requires at least {requirement.stability}",
        )
    return ClaimBlocker(
        code=ClaimBlockerCode.CAPABILITY_VERSION_TOO_OLD,
        capability=requirement.name,
        detail=f"declared {declared.version}, requires at least {requirement.min_version}",
    )
