"""Deterministic, read-only Brain capability and dependency registry."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

CapabilityStatus = Literal[
    "OPERATIONAL",
    "IMPLEMENTED_NOT_INTEGRATED",
    "PARTIAL",
    "DOCUMENTED_ONLY",
    "ABSENT",
    "BLOCKED",
]
EXECUTABLE_STATUS = "OPERATIONAL"
LITERATURE_HANDOFF_REPOSITORY = "jsp1440/Orchid-Continuum-Brain"
LITERATURE_HANDOFF_COMMIT = "db27f9283bc1a964a9d40e6ae3cedd34eee7b522"


@dataclass(frozen=True)
class Capability:
    capability_id: str
    canonical_issue: str
    status: CapabilityStatus
    repository_evidence: tuple[str, ...]
    public_entry_point: str | None
    persistence: str | None
    api: str | None
    tests: tuple[str, ...]
    upstream_dependencies: tuple[str, ...]
    downstream_consumers: tuple[str, ...]
    blockers: tuple[str, ...]
    next_executable_slice: str | None
    last_verified_commit: str
    last_verified_date: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class CapabilityRegistry:
    """Expose verified dependency state without granting mutation authority."""

    def __init__(self, capabilities: tuple[Capability, ...]) -> None:
        self._items = {item.capability_id: item for item in capabilities}
        if len(self._items) != len(capabilities):
            raise ValueError("duplicate capability_id")

    def eligibility(self, capability_id: str) -> dict[str, object]:
        return self._eligibility(capability_id, path=())

    def _eligibility(
        self, capability_id: str, *, path: tuple[str, ...]
    ) -> dict[str, object]:
        item = self._items.get(capability_id)
        if item is None:
            return {
                "capability_id": capability_id,
                "eligible": False,
                "reasons": ["capability is absent from the verified registry"],
            }
        if capability_id in path:
            cycle = " -> ".join((*path, capability_id))
            return {
                "capability_id": capability_id,
                "eligible": False,
                "reasons": [f"dependency cycle: {cycle}"],
            }
        reasons: list[str] = []
        if item.status != EXECUTABLE_STATUS:
            reasons.append(f"status is {item.status}, not {EXECUTABLE_STATUS}")
        reasons.extend(f"blocker: {blocker}" for blocker in item.blockers)
        for dependency_id in item.upstream_dependencies:
            dependency = self._items.get(dependency_id)
            if dependency is None:
                reasons.append(f"unknown dependency: {dependency_id}")
                continue
            dependency_result = self._eligibility(
                dependency_id, path=(*path, capability_id)
            )
            if not dependency_result["eligible"]:
                detail = "; ".join(str(reason) for reason in dependency_result["reasons"])
                reasons.append(f"dependency ineligible: {dependency_id} ({detail})")
        return {
            "capability_id": capability_id,
            "eligible": not reasons,
            "reasons": reasons,
        }

    def orchestrator_view(self) -> dict[str, object]:
        capabilities = []
        for capability_id in sorted(self._items):
            item = self._items[capability_id]
            capabilities.append(
                {**item.to_dict(), "eligibility": self.eligibility(capability_id)}
            )
        return {
            "contract": "calyx-brain-capability-registry-v1",
            "read_only": True,
            "publication_authority": False,
            "execution_authority": False,
            "capabilities": capabilities,
        }


def canonical_brain_registry() -> CapabilityRegistry:
    """Return the first evidence-pinned registry seed from issue #1498."""
    return CapabilityRegistry(
        (
            Capability(
                capability_id="literature_candidate_handoff",
                canonical_issue="Orchid-Continuum-Brain#146",
                status="OPERATIONAL",
                repository_evidence=(
                    f"{LITERATURE_HANDOFF_REPOSITORY}@{LITERATURE_HANDOFF_COMMIT}",
                ),
                public_entry_point="Literature Intelligence -> Candidate Knowledge handoff",
                persistence="canonical candidate-knowledge handoff",
                api=None,
                tests=("merged PR #146 validation",),
                upstream_dependencies=(),
                downstream_consumers=("scientific_language_intake",),
                blockers=(),
                next_executable_slice=None,
                last_verified_commit="db27f9283bc1a964a9d40e6ae3cedd34eee7b522",
                last_verified_date="2026-09-19",
            ),
            Capability(
                capability_id="scientific_language_intake",
                canonical_issue="orchid-calyx-backend#710",
                status="OPERATIONAL",
                repository_evidence=(
                    "orchid-calyx-backend#1527 candidate API",
                    "orchid-calyx-backend#1528 canonical projection",
                    "orchid-calyx-backend#1529 figure queue",
                    "migrations/710_scientific_language_persistence.sql",
                ),
                public_entry_point="/api/scientific-interpretation/language",
                persistence=(
                    "restart-safe file repositories; additive PostgreSQL schema "
                    "defined but production application remains owner-gated"
                ),
                api="authenticated candidate intake/read and figure queue; read-only glossary projection",
                tests=(
                    "tests/test_scientific_language_candidate_api.py",
                    "tests/test_scientific_language_glossary_projection.py",
                    "tests/test_scientific_language_figure_queue.py",
                    "tests/test_scientific_language_postgres_migration.py",
                ),
                upstream_dependencies=("literature_candidate_handoff",),
                downstream_consumers=("reasoning_ledger", "data_intelligence"),
                blockers=(),
                next_executable_slice=None,
                last_verified_commit="afefa7eb11081328a2dc1c122e58ec286ae4552b",
                last_verified_date="2026-09-20",
            ),
            Capability(
                capability_id="reasoning_ledger",
                canonical_issue="Orchid-Continuum-Brain#142",
                status="PARTIAL",
                repository_evidence=("canonical owner issue #142",),
                public_entry_point=None,
                persistence=None,
                api=None,
                tests=(),
                upstream_dependencies=("scientific_language_intake",),
                downstream_consumers=("executive_planning",),
                blockers=(),
                next_executable_slice="verify ledger against governed evidence and concepts",
                last_verified_commit="unverified",
                last_verified_date="2026-09-19",
            ),
            Capability(
                capability_id="executive_planning",
                canonical_issue="orchid-calyx-backend#1024",
                status="IMPLEMENTED_NOT_INTEGRATED",
                repository_evidence=("existing autonomous orchestrator #1024",),
                public_entry_point="existing Calyx orchestration",
                persistence="existing orchestrator persistence",
                api=None,
                tests=(),
                upstream_dependencies=("reasoning_ledger",),
                downstream_consumers=(),
                blockers=("verified Brain dependency state is incomplete",),
                next_executable_slice="consume this read-only eligibility view",
                last_verified_commit="unverified",
                last_verified_date="2026-09-19",
            ),
        )
    )
