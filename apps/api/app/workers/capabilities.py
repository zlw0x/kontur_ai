"""The capability registry (POSTMVP-003).

A worker declares what its installed KOMPAS and adapter can actually build.
The API refuses to lease a job whose operations the worker cannot serve, so an
unsupported feature fails at scheduling time with a typed reason instead of
halfway through a CAD session on the user's machine.

Keys are versioned vocabulary, not free text: adding one here is the deliberate
step that makes a new operation schedulable.
"""

from __future__ import annotations

from app.contracts import CapabilityStatus, JobType, WorkerCapabilityManifest

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
    return manifest.supports(required)


def manifest_from_status_map(
    worker_version: str,
    cad_ir_versions: list[str],
    statuses: dict[str, CapabilityStatus],
    kompas_version: str | None = None,
    codex_cli_version: str | None = None,
) -> WorkerCapabilityManifest:
    return WorkerCapabilityManifest(
        worker_version=worker_version,
        kompas_version=kompas_version,
        codex_cli_version=codex_cli_version,
        cad_ir_versions=cad_ir_versions,
        capabilities=statuses,
    )
