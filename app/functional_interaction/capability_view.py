"""FIL-001B canonical capability view.

The audit found five capability vocabularies that never reference each other.
This module does not add a sixth. It names one of them canonical --
``app.provider_reservoir.capabilities.CAPABILITIES``, the list routing already
enforces -- and joins the others to it through explicit crosswalks:

* executor role keys (``AuthoritativeExecutorRegistry``),
* executor protocol capabilities (``ExecutorCapability``),
* Brain capability-registry ids (``runtime.brain_capability_registry``),
* FIL descriptors (each already keyed to a canonical name).

Every member of every live vocabulary must appear in its crosswalk, mapped to
canonical names or explicitly unmapped with a reason. A new executor role or
Brain capability without a crosswalk entry, a crosswalk entry for something
that no longer exists, a mapping to a name routing does not know, or a FIL
descriptor whose Brain link disagrees with the crosswalk all raise. Drift
becomes a failing test instead of a surprise.

The view is read-only and grants nothing.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.calyx_orchestrator.executor import ExecutorCapability
from app.calyx_orchestrator.executor_registry import AuthoritativeExecutorRegistry
from app.provider_reservoir.capabilities import CAPABILITIES, CapabilityUnknown
from runtime.brain_capability_registry import canonical_brain_registry

from .contracts import CapabilityDescriptor

CANONICAL_SOURCE = "app.provider_reservoir.capabilities.CAPABILITIES"
VIEW_CONTRACT = "oc.fil.canonical-capability-view.v1"


class CrosswalkError(ValueError):
    """A vocabulary and its crosswalk to the canonical registry disagree."""


@dataclass(frozen=True)
class Crosswalk:
    canonical: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise CrosswalkError("CROSSWALK_REASON_REQUIRED")


_ENGINEERING = (
    "engineering executor role; the Continuum has no scientific capability name for it"
)

EXECUTOR_ROLE_CROSSWALK: dict[str, Crosswalk] = {
    "autonomy_probe": Crosswalk((), f"liveness probe; {_ENGINEERING}"),
    "repository_evidence_reader": Crosswalk(
        (), f"reads repository files as engineering evidence; {_ENGINEERING}"
    ),
    "isolated_workspace_patcher": Crosswalk(
        (), f"applies a bounded code patch; {_ENGINEERING}"
    ),
    "isolated_workspace_static_validator": Crosswalk(
        (), f"AST syntax check of an isolated patch; {_ENGINEERING}"
    ),
}

EXECUTOR_CAPABILITY_CROSSWALK: dict[str, Crosswalk] = {
    item.value: Crosswalk(
        (), "executor protocol behaviour every executor offers, not a capability"
    )
    for item in ExecutorCapability
}

BRAIN_CAPABILITY_CROSSWALK: dict[str, Crosswalk] = {
    "literature_candidate_handoff": Crosswalk(
        (
            "contradiction-detection",
            "literature-evidence-lookup",
            "provenance-assembly",
        ),
        "Literature -> Candidate Knowledge handoff: stored literature with provenance, conflicts marked",
    ),
    "reasoning_ledger": Crosswalk(
        ("contradiction-detection", "reasoning-map-assembly"),
        "append-only reasoning with support, counterevidence and conflict entries",
    ),
    "scientific_language_intake": Crosswalk(
        (), "lexicon/language intake; no canonical capability name exists yet"
    ),
    "epistemic_memory": Crosswalk(
        (),
        "read-only projection of ledger memory; no canonical capability name exists yet",
    ),
    "data_intelligence": Crosswalk(
        (), "tabular ingest/profile/export; no canonical capability name exists yet"
    ),
    "executive_planning": Crosswalk(
        (),
        "reserve planning for the queue director; no canonical capability name exists yet",
    ),
}

#: Facts recorded by AUDIT-0003 about mirrors of the canonical list that live in
#: other repositories (they cannot be read from here). Each name must still be
#: canonical; when it is not, this record is stale and must be revisited.
KNOWN_MIRROR_DRIFT: dict[str, str] = {
    "firecrawl-acquisition": (
        "present in this registry on oc-autonomous-integration; absent from Brain "
        "contracts/cognitive_integration_capabilities_v1.json and frontend "
        "contracts/oc-shared-capabilities.v1.json at the audited commits"
    ),
}


def _live_vocabularies() -> dict[str, tuple[str, ...]]:
    return {
        "executor_roles": tuple(
            sorted(AuthoritativeExecutorRegistry().eligible_role_keys)
        ),
        "executor_capabilities": tuple(
            sorted(item.value for item in ExecutorCapability)
        ),
        "brain_capabilities": tuple(
            sorted(
                item["capability_id"]
                for item in canonical_brain_registry().orchestrator_view()[
                    "capabilities"
                ]
            )
        ),
    }


_CROSSWALKS = {
    "executor_roles": EXECUTOR_ROLE_CROSSWALK,
    "executor_capabilities": EXECUTOR_CAPABILITY_CROSSWALK,
    "brain_capabilities": BRAIN_CAPABILITY_CROSSWALK,
}


def _check(
    live: dict[str, tuple[str, ...]],
    crosswalks: dict[str, dict[str, Crosswalk]],
    descriptors: Iterable[CapabilityDescriptor],
) -> None:
    problems: list[str] = []
    for vocabulary, members in live.items():
        crosswalk = crosswalks[vocabulary]
        problems += [
            f"UNMAPPED:{vocabulary}:{m}" for m in members if m not in crosswalk
        ]
        problems += [
            f"STALE_CROSSWALK_ENTRY:{vocabulary}:{k}"
            for k in sorted(crosswalk)
            if k not in members
        ]
        for member, entry in sorted(crosswalk.items()):
            problems += [
                f"UNKNOWN_CANONICAL:{vocabulary}:{member}:{n}"
                for n in entry.canonical
                if n not in CAPABILITIES
            ]
    for descriptor in descriptors:
        if (
            descriptor.registry_capability not in CAPABILITIES
        ):  # pragma: no cover - the descriptor refuses first
            problems.append(f"UNKNOWN_CANONICAL:fil:{descriptor.capability_id}")
        brain_id = descriptor.brain_capability_id
        if brain_id is None:
            continue
        entry = crosswalks["brain_capabilities"].get(brain_id)
        if entry is None or descriptor.registry_capability not in entry.canonical:
            problems.append(
                f"FIL_BRAIN_LINK_DISAGREES:{descriptor.capability_id}:{brain_id}:{descriptor.registry_capability}"
            )
    problems += [
        f"STALE_MIRROR_DRIFT_RECORD:{name}"
        for name in sorted(KNOWN_MIRROR_DRIFT)
        if name not in CAPABILITIES
    ]
    if problems:
        raise CrosswalkError(";".join(problems))


def canonical_capability_view(
    descriptors: Iterable[CapabilityDescriptor] = (),
    *,
    live: dict[str, tuple[str, ...]] | None = None,
    crosswalks: dict[str, dict[str, Crosswalk]] | None = None,
) -> dict[str, Any]:
    """One read-only view of what the Continuum can do, keyed by canonical name.

    ``live`` and ``crosswalks`` are injectable only so tests can show that drift
    is refused; callers use the defaults.
    """

    descriptors = tuple(descriptors)
    live = live if live is not None else _live_vocabularies()
    crosswalks = crosswalks if crosswalks is not None else _CROSSWALKS
    _check(live, crosswalks, descriptors)

    rows: dict[str, dict[str, Any]] = {
        name: {
            "name": name,
            "provider_required": capability.provider_required,
            "summary": capability.summary,
            "fil_descriptors": [],
            "brain_capabilities": [],
            "executor_roles": [],
            "mirror_drift": KNOWN_MIRROR_DRIFT.get(name),
        }
        for name, capability in sorted(CAPABILITIES.items())
    }
    for descriptor in sorted(descriptors, key=lambda d: d.capability_id):
        rows[descriptor.registry_capability]["fil_descriptors"].append(
            f"{descriptor.capability_id}@{descriptor.version}"
        )
    column = {
        "brain_capabilities": "brain_capabilities",
        "executor_roles": "executor_roles",
    }
    unmapped: dict[str, list[dict[str, str]]] = {}
    coverage: dict[str, dict[str, int]] = {}
    for vocabulary, members in live.items():
        crosswalk = crosswalks[vocabulary]
        mapped = 0
        for member in members:
            entry = crosswalk[member]
            if entry.canonical:
                mapped += 1
                for name in entry.canonical:
                    if vocabulary in column:
                        rows[name][column[vocabulary]].append(member)
            else:
                unmapped.setdefault(vocabulary, []).append(
                    {"member": member, "reason": entry.reason}
                )
        coverage[vocabulary] = {"members": len(members), "mapped": mapped}
    described = {d.registry_capability for d in descriptors}
    coverage["canonical_with_fil_descriptor"] = {
        "members": len(rows),
        "mapped": len(described),
    }
    return {
        "contract": VIEW_CONTRACT,
        "canonical_source": CANONICAL_SOURCE,
        "read_only": True,
        "execution_authority": False,
        "capabilities": list(rows.values()),
        "unmapped": unmapped,
        "coverage": coverage,
    }


def require_canonical(name: str) -> str:
    """The canonical name, or the routing registry's own refusal."""
    if name not in CAPABILITIES:
        raise CapabilityUnknown(f"capability {name!r} is not in {CANONICAL_SOURCE}")
    return name
