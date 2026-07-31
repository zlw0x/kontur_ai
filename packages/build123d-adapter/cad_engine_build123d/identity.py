"""What this engine is, and what it promises to produce.

The same shape as `CadEngineDescription` on the .NET side (ENGINE-MIG-002): an
engine declares itself rather than letting the pipeline assume. Two engines
produce a STEP file from the same document during the migration, and when they
disagree the first question is which one wrote the file in front of you.

Unlike KOMPAS, this engine can answer every field. `kernel_version` is read from
the installed OpenCascade binding rather than typed into a constant — an
unverified version string is worse than an absent one, because it reads as
measured and is wrong on the first machine with a different install.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from cad_ir.canonical import CAD_IR_VERSION

from .capabilities import CapabilityGate


@dataclass(frozen=True)
class ArtifactKind:
    """One kind of file this engine promises to write."""

    kind: str
    file_name: str
    required: bool = True


@dataclass(frozen=True)
class EngineDescription:
    engine_id: str
    engine_version: str
    kernel_id: str
    kernel_version: str | None
    cad_ir_version: str
    artifacts: tuple[ArtifactKind, ...] = field(default_factory=tuple)
    #: What this engine builds, by capability key, with the flags of this run
    #: already applied. The worker that launches this process publishes these to
    #: the API, so the statuses the scheduler reads and the gate the build
    #: enforces come from one call rather than from two lists to keep in step.
    capabilities: Mapping[str, Mapping[str, str]] = field(default_factory=dict)

    @property
    def required_artifacts(self) -> tuple[ArtifactKind, ...]:
        return tuple(item for item in self.artifacts if item.required)

    def as_dict(self) -> dict[str, object]:
        return {
            "engine_id": self.engine_id,
            "engine_version": self.engine_version,
            "kernel_id": self.kernel_id,
            "kernel_version": self.kernel_version,
            "cad_ir_version": self.cad_ir_version,
            "artifacts": [
                {"kind": item.kind, "file": item.file_name, "required": item.required}
                for item in self.artifacts
            ],
            "capabilities": {
                key: dict(value) for key, value in sorted(self.capabilities.items())
            },
        }


#: The two user-facing results, and only those (ADR-023). STEP is the exact BREP
#: a customer takes into any CAD system; STL is the mesh for preview and for
#: manufacturing. There is no third format, and in particular no M3D.
ARTIFACTS: tuple[ArtifactKind, ...] = (
    ArtifactKind("STEP", "model.step"),
    ArtifactKind("STL", "model.stl"),
)


def _version_of(module_name: str) -> str | None:
    """The installed version of a package, or nothing.

    Read from the distribution metadata rather than from a `__version__`
    attribute: not every package defines one, and a missing attribute would be
    indistinguishable from a package that is not installed.
    """
    from importlib import metadata

    try:
        return metadata.version(module_name)
    except metadata.PackageNotFoundError:  # pragma: no cover - depends on install
        return None


def describe(gate: CapabilityGate | None = None) -> EngineDescription:
    """This engine, as it is actually installed, under the flags of this run."""
    effective = gate or CapabilityGate.all_enabled()
    return EngineDescription(
        engine_id="build123d",
        engine_version=_version_of("build123d") or "unknown",
        kernel_id="opencascade",
        # OCP is the OpenCascade binding; its version is the kernel's, and it
        # ships under more than one distribution name depending on the wheel.
        kernel_version=_version_of("cadquery-ocp")
        or _version_of("cadquery-ocp-novtk")
        or _version_of("OCP"),
        cad_ir_version=CAD_IR_VERSION,
        artifacts=ARTIFACTS,
        capabilities=effective.declarations(),
    )
