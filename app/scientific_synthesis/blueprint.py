"""Research blueprint decomposition: GovernanceDecision → bounded TaskLeaf set.

This module is the next executable link in the autonomous research loop after
the governance/admission gate (app/scientific_synthesis/governance.py):

    GovernanceDecision(admitted=True)
    → decompose_governed_action()        # this module — deterministic, provider-free
    → ResearchBlueprint                   # bounded, validated, fingerprinted
    → validate_blueprint()                # cycle-free, depth-bounded, count-bounded
    → enqueue_blueprint(reservoir)        # register into DeepOrchestrate — idempotent
    → canonical queue
    → worker execution

All decomposition is deterministic and provider-free. No model inference, no
network calls, no database. The same GovernanceDecision + manifest always produces
the same Blueprint and the same TaskLeaf keys, making enqueue_blueprint() idempotent.

Hard limits (enforced by validate_blueprint):
    MAX_TASK_COUNT      = 8   — blueprint may not exceed this many task leaves
    MAX_DEPENDENCY_DEPTH = 4  — longest chain of dependencies (edges, not nodes)

Governance flag propagation:
    human_review_required          → submit-for-human-review leaf added (P0, parallel to verify)
    automatic_publication_allowed  → carried in blueprint for downstream provenance
    canonical_mutation_allowed     → carried in blueprint for downstream provenance
    canonical_activation_requires_human_authority → carried in blueprint

Authority class assignment:
    AUTH_READ_ONLY   → retrieve-evidence (reads only, no mutation)
    AUTH_WORKSPACE   → normalize, assess, produce, verify, submit (bounded workspace)
    AUTH_PRODUCTION  → canonical_mutation / canonical_activation tasks (owner-gated)
    AUTH_SCIENCE_PUB → automatic_scientific_publication tasks (owner-gated)
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.calyx_orchestrator.deep_orchestrate import (
    AUTH_PRODUCTION,
    AUTH_READ_ONLY,
    AUTH_SCIENCE_PUB,
    AUTH_WORKSPACE,
    DeepOrchestrate,
    Priority,
    TaskLeaf,
)

from .governance import GovernanceDecision, GovernanceOutcome

BLUEPRINT_VERSION = "oc-research-blueprint-v1"
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")

MAX_TASK_COUNT = 8
MAX_DEPENDENCY_DEPTH = 4


class BlueprintValidationError(ValueError):
    """Raised when governance is not admitted or a blueprint fails validation."""


# ---------------------------------------------------------------------------
# Blueprint dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResearchBlueprint:
    """Bounded, validated, fingerprinted research plan ready for queue admission.

    All governance flags from the source manifest are carried forward so workers
    and downstream steps can verify provenance without re-fetching the manifest.
    """

    blueprint_id: str           # 64-char SHA-256 (deterministic fingerprint)
    run_fingerprint: str        # from source RunEvidenceManifest
    proposed_action: str        # the governed action that was admitted
    governance_outcome: str     # "admitted"
    task_leaves: tuple[TaskLeaf, ...]  # topologically ordered
    max_dependency_depth: int   # actual depth of the dependency graph (edges)
    human_review_required: bool
    automatic_publication_allowed: bool
    canonical_mutation_allowed: bool
    canonical_activation_requires_human_authority: bool
    run_id: str
    taxon_id: str
    research_question: str
    created_at_utc: str
    version: str = field(default=BLUEPRINT_VERSION)

    def summary(self) -> dict[str, Any]:
        """Serializable summary for routes and logging."""
        return {
            "version": self.version,
            "blueprint_id": self.blueprint_id,
            "run_fingerprint": self.run_fingerprint,
            "proposed_action": self.proposed_action,
            "governance_outcome": self.governance_outcome,
            "task_count": len(self.task_leaves),
            "max_dependency_depth": self.max_dependency_depth,
            "human_review_required": self.human_review_required,
            "automatic_publication_allowed": self.automatic_publication_allowed,
            "canonical_mutation_allowed": self.canonical_mutation_allowed,
            "canonical_activation_requires_human_authority": (
                self.canonical_activation_requires_human_authority
            ),
            "run_id": self.run_id,
            "taxon_id": self.taxon_id,
            "research_question": self.research_question,
            "created_at_utc": self.created_at_utc,
            "tasks": [
                {
                    "key": leaf.key,
                    "title": leaf.title,
                    "authority_class": leaf.authority_class,
                    "priority": leaf.priority,
                    "dependencies": leaf.dependencies,
                    "requires_owner_gate": leaf.requires_owner_gate,
                    "acceptance_criteria": leaf.acceptance_criteria,
                }
                for leaf in self.task_leaves
            ],
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _blueprint_fingerprint(
    run_fingerprint: str,
    proposed_action: str,
    governance_outcome: str,
) -> str:
    payload = json.dumps(
        {
            "version": BLUEPRINT_VERSION,
            "run_fingerprint": run_fingerprint,
            "proposed_action": proposed_action,
            "governance_outcome": governance_outcome,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _task_key(blueprint_id_short: str, step: str) -> str:
    return f"research:{blueprint_id_short}:{step}"


def _compute_max_depth(leaves: tuple[TaskLeaf, ...]) -> int:
    """Compute the longest dependency chain (edges) in the task graph."""
    if not leaves:
        return 0
    key_to_leaf = {leaf.key: leaf for leaf in leaves}
    valid_keys = set(key_to_leaf)
    memo: dict[str, int] = {}

    def depth(key: str) -> int:
        if key in memo:
            return memo[key]
        leaf = key_to_leaf.get(key)
        if leaf is None:
            return 0
        internal_deps = [d for d in leaf.dependencies if d in valid_keys]
        result = (1 + max(depth(d) for d in internal_deps)) if internal_deps else 0
        memo[key] = result
        return result

    return max(depth(leaf.key) for leaf in leaves)


def _detect_cycles(leaves: tuple[TaskLeaf, ...]) -> bool:
    """Return True if the dependency graph contains a cycle (Kahn's algorithm)."""
    valid_keys = {leaf.key for leaf in leaves}
    # adjacency: dep_key → list of leaves that depend on it
    adjacency: dict[str, list[str]] = {}
    in_degree: dict[str, int] = {}

    for leaf in leaves:
        internal_deps = [d for d in leaf.dependencies if d in valid_keys]
        in_degree[leaf.key] = len(internal_deps)
        for dep in internal_deps:
            adjacency.setdefault(dep, []).append(leaf.key)

    queue = [k for k, d in in_degree.items() if d == 0]
    processed = 0
    while queue:
        node = queue.pop(0)
        processed += 1
        for dependent in adjacency.get(node, []):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    return processed != len(leaves)


# ---------------------------------------------------------------------------
# Task leaf builders per governed action
# ---------------------------------------------------------------------------


def _leaves_build_synthesis(
    prefix: str,
    run_id: str,
    taxon_id: str,
    research_question: str,
    human_review_required: bool,
) -> list[TaskLeaf]:
    """Canonical 5- or 6-leaf decomposition for build_synthesis.

    Dependency chain (max depth 4 edges):
        retrieve → normalize → assess → produce → verify
                                                 → submit (parallel, if human_review)
    """
    q_short = research_question[:80]

    retrieve_key = _task_key(prefix, "retrieve-evidence")
    normalize_key = _task_key(prefix, "normalize-evidence")
    assess_key = _task_key(prefix, "assess-contradictions")
    produce_key = _task_key(prefix, "produce-synthesis-artifact")
    verify_key = _task_key(prefix, "run-verification")

    leaves: list[TaskLeaf] = [
        TaskLeaf(
            key=retrieve_key,
            title=f"Retrieve evidence for: {q_short}",
            repo="orchid-calyx-backend",
            module="app/scientific_synthesis",
            priority=Priority.P1,
            authority_class=AUTH_READ_ONLY,
            consequence_risk="low",
            dependencies=[],
            acceptance_criteria=[
                "All available evidence retrieved for taxon",
                "Missing evidence documented as unavailable — not fabricated",
                "No fabrication of unavailable sources",
            ],
            evidence={"run_id": run_id, "taxon_id": taxon_id},
        ),
        TaskLeaf(
            key=normalize_key,
            title=f"Normalize evidence for synthesis: {taxon_id}",
            repo="orchid-calyx-backend",
            module="app/scientific_synthesis",
            priority=Priority.P2,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
            dependencies=[retrieve_key],
            acceptance_criteria=[
                "Evidence normalized to canonical EvidenceMatrixRow schema",
                "Uncertainty, limitations, and confidence preserved",
            ],
            evidence={"run_id": run_id},
        ),
        TaskLeaf(
            key=assess_key,
            title=f"Assess contradictions and knowledge gaps: {taxon_id}",
            repo="orchid-calyx-backend",
            module="app/scientific_synthesis",
            priority=Priority.P2,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
            dependencies=[normalize_key],
            acceptance_criteria=[
                "Contradictions enumerated and carried forward",
                "Knowledge gaps documented — not suppressed",
            ],
            evidence={"run_id": run_id},
        ),
        TaskLeaf(
            key=produce_key,
            title=f"Produce synthesis artifact: {taxon_id}",
            repo="orchid-calyx-backend",
            module="app/scientific_synthesis",
            priority=Priority.P1,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
            dependencies=[assess_key],
            acceptance_criteria=[
                "Synthesis article draft produced",
                "All claims grounded in retrieved evidence",
                "Contradictions preserved in output",
                "No automatic publication or KG mutation",
            ],
            evidence={"run_id": run_id},
        ),
        TaskLeaf(
            key=verify_key,
            title=f"Run verification and evaluation: {taxon_id}",
            repo="orchid-calyx-backend",
            module="app/scientific_synthesis",
            priority=Priority.P1,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
            dependencies=[produce_key],
            acceptance_criteria=[
                "Verification result attached as evidence",
                "Defects recorded — not suppressed",
                "No automatic publication triggered",
            ],
            evidence={"run_id": run_id},
        ),
    ]

    if human_review_required:
        # Parallel to verify: both depend on produce (not on each other).
        submit_key = _task_key(prefix, "submit-for-human-review")
        leaves.append(
            TaskLeaf(
                key=submit_key,
                title=f"Submit synthesis for human review: {taxon_id}",
                repo="orchid-calyx-backend",
                module="app/scientific_synthesis",
                priority=Priority.P0,
                authority_class=AUTH_WORKSPACE,
                consequence_risk="low",
                dependencies=[produce_key],
                acceptance_criteria=[
                    "Synthesis submitted to human review queue",
                    "No publication without explicit human approval",
                    "Review decision recorded before any canonical action",
                ],
                evidence={"run_id": run_id, "human_review_required": True},
            )
        )

    return leaves


def _leaves_read_evidence(prefix: str, run_id: str, taxon_id: str) -> list[TaskLeaf]:
    return [
        TaskLeaf(
            key=_task_key(prefix, "retrieve-evidence"),
            title=f"Retrieve evidence: {taxon_id}",
            repo="orchid-calyx-backend",
            module="app/scientific_synthesis",
            priority=Priority.P1,
            authority_class=AUTH_READ_ONLY,
            consequence_risk="low",
            dependencies=[],
            acceptance_criteria=["Evidence retrieved; missing documented as unavailable"],
            evidence={"run_id": run_id},
        )
    ]


def _leaves_human_review_submission(
    prefix: str, run_id: str, taxon_id: str
) -> list[TaskLeaf]:
    return [
        TaskLeaf(
            key=_task_key(prefix, "submit-human-review-record"),
            title=f"Submit human review record: {taxon_id}",
            repo="orchid-calyx-backend",
            module="app/scientific_synthesis",
            priority=Priority.P0,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
            dependencies=[],
            acceptance_criteria=["Review decision recorded; no automatic downstream action"],
            evidence={"run_id": run_id},
        )
    ]


def _leaves_build_manifest(prefix: str, run_id: str, taxon_id: str) -> list[TaskLeaf]:
    return [
        TaskLeaf(
            key=_task_key(prefix, "build-run-manifest"),
            title=f"Build run evidence manifest: {taxon_id}",
            repo="orchid-calyx-backend",
            module="app/scientific_synthesis",
            priority=Priority.P1,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
            dependencies=[],
            acceptance_criteria=[
                "oc-run-evidence-manifest-v1 produced and fingerprinted",
                "Immutable and human-review gated",
            ],
            evidence={"run_id": run_id},
        )
    ]


def _leaves_canonical_knowledge_mutation(
    prefix: str, run_id: str, taxon_id: str
) -> list[TaskLeaf]:
    # AUTH_PRODUCTION → auto owner-gated; never auto-dispatched.
    return [
        TaskLeaf(
            key=_task_key(prefix, "canonical-knowledge-mutation"),
            title=f"Canonical knowledge mutation (owner-gated): {taxon_id}",
            repo="orchid-calyx-backend",
            module="app/scientific_synthesis",
            priority=Priority.P0,
            authority_class=AUTH_PRODUCTION,
            consequence_risk="high",
            dependencies=[],
            acceptance_criteria=[
                "Explicit owner authorization obtained",
                "Exact evidence provenance preserved",
                "No mutation without human approval",
            ],
            evidence={"run_id": run_id},
        )
    ]


def _leaves_automatic_scientific_publication(
    prefix: str, run_id: str, taxon_id: str
) -> list[TaskLeaf]:
    # AUTH_SCIENCE_PUB → auto owner-gated; never auto-dispatched.
    return [
        TaskLeaf(
            key=_task_key(prefix, "scientific-publication"),
            title=f"Scientific publication (owner-gated): {taxon_id}",
            repo="orchid-calyx-backend",
            module="app/scientific_synthesis",
            priority=Priority.P0,
            authority_class=AUTH_SCIENCE_PUB,
            consequence_risk="high",
            dependencies=[],
            acceptance_criteria=[
                "Explicit owner authorization obtained",
                "Peer review or equivalent completed",
                "No automatic publication without human approval",
            ],
            evidence={"run_id": run_id},
        )
    ]


def _leaves_canonical_activation(
    prefix: str, run_id: str, taxon_id: str
) -> list[TaskLeaf]:
    # AUTH_PRODUCTION → auto owner-gated; never auto-dispatched.
    return [
        TaskLeaf(
            key=_task_key(prefix, "canonical-activation"),
            title=f"Canonical activation (owner-gated): {taxon_id}",
            repo="orchid-calyx-backend",
            module="app/scientific_synthesis",
            priority=Priority.P0,
            authority_class=AUTH_PRODUCTION,
            consequence_risk="high",
            dependencies=[],
            acceptance_criteria=[
                "Explicit owner authorization obtained",
                "Activation plan reviewed",
                "Rollback plan prepared",
            ],
            evidence={"run_id": run_id},
        )
    ]


_LEAF_BUILDERS = {
    "build_synthesis": _leaves_build_synthesis,
    "read_evidence": _leaves_read_evidence,
    "human_review_submission": _leaves_human_review_submission,
    "build_manifest": _leaves_build_manifest,
    "canonical_knowledge_mutation": _leaves_canonical_knowledge_mutation,
    "automatic_scientific_publication": _leaves_automatic_scientific_publication,
    "canonical_activation": _leaves_canonical_activation,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def decompose_governed_action(
    governance_decision: GovernanceDecision,
    manifest: dict[str, Any],
    proposed_action: str,
    *,
    run_id: str,
    taxon_id: str,
    research_question: str,
) -> ResearchBlueprint:
    """Decompose an admitted GovernanceDecision into a bounded ResearchBlueprint.

    FAILS CLOSED if any of the following:
    - governance_decision is not a GovernanceDecision instance
    - governance_decision.admitted is False
    - governance_decision.outcome is not ADMITTED
    - governance_decision.blocking_flags is non-empty
    - manifest run_fingerprint is missing or malformed
    - proposed_action is not in the governed action set

    Parameters
    ----------
    governance_decision:
        A GovernanceDecision returned by check_manifest_governance() with
        admitted=True and no blocking_flags.
    manifest:
        The oc-run-evidence-manifest-v1 dict that was passed to governance check.
    proposed_action:
        The exact action string that was admitted (one of the 7 governed actions).
    run_id, taxon_id, research_question:
        Context from the original research run, used for task titles and evidence.

    Returns
    -------
    ResearchBlueprint
        Validated, fingerprinted blueprint ready for enqueue_blueprint().

    Raises
    ------
    BlueprintValidationError
        GOVERNANCE_DECISION_REQUIRED — argument is not a GovernanceDecision.
        GOVERNANCE_NOT_ADMITTED — outcome is not ADMITTED.
        GOVERNANCE_ADMITTED_FALSE — admitted field is False.
        GOVERNANCE_HAS_BLOCKING_FLAGS — blocking_flags is non-empty.
        MANIFEST_FINGERPRINT_REQUIRED — run_fingerprint absent or malformed.
        BLUEPRINT_UNKNOWN_ACTION — proposed_action not in governed action set.
        BLUEPRINT_TASK_COUNT_EXCEEDED — task count > MAX_TASK_COUNT.
        BLUEPRINT_DEPENDENCY_DEPTH_EXCEEDED — depth > MAX_DEPENDENCY_DEPTH.
        BLUEPRINT_CYCLE_DETECTED — dependency graph has a cycle.
        BLUEPRINT_DUPLICATE_TASK_KEYS — two tasks share the same key.
    """
    # ── Fail-closed governance checks ────────────────────────────────────────
    if not isinstance(governance_decision, GovernanceDecision):
        raise BlueprintValidationError("GOVERNANCE_DECISION_REQUIRED")
    if governance_decision.outcome is not GovernanceOutcome.ADMITTED:
        raise BlueprintValidationError(
            f"GOVERNANCE_NOT_ADMITTED:{governance_decision.outcome.value}"
        )
    if not governance_decision.admitted:
        raise BlueprintValidationError("GOVERNANCE_ADMITTED_FALSE")
    if governance_decision.blocking_flags:
        raise BlueprintValidationError(
            f"GOVERNANCE_HAS_BLOCKING_FLAGS:{governance_decision.blocking_flags!r}"
        )

    # ── Manifest provenance validation ───────────────────────────────────────
    run_fingerprint = str(manifest.get("run_fingerprint", ""))
    if not _FINGERPRINT_RE.match(run_fingerprint):
        raise BlueprintValidationError("MANIFEST_FINGERPRINT_REQUIRED")

    # ── Action validation ─────────────────────────────────────────────────────
    if proposed_action not in _LEAF_BUILDERS:
        raise BlueprintValidationError(f"BLUEPRINT_UNKNOWN_ACTION:{proposed_action}")

    # ── Deterministic blueprint fingerprint ──────────────────────────────────
    blueprint_id = _blueprint_fingerprint(
        run_fingerprint, proposed_action, governance_decision.outcome.value
    )
    prefix = blueprint_id[:16]

    # ── Decomposition ────────────────────────────────────────────────────────
    builder = _LEAF_BUILDERS[proposed_action]
    human_review_required = bool(manifest.get("human_review_required", True))
    automatic_publication_allowed = bool(
        manifest.get("automatic_scientific_publication_allowed", False)
    )
    canonical_mutation_allowed = bool(
        manifest.get("canonical_knowledge_mutation_allowed", False)
    )
    canonical_activation_requires_human_authority = bool(
        manifest.get("canonical_activation_requires_human_authority", True)
    )

    if proposed_action == "build_synthesis":
        raw_leaves = builder(
            prefix, run_id, taxon_id, research_question, human_review_required
        )
    else:
        raw_leaves = builder(prefix, run_id, taxon_id)

    leaves = tuple(raw_leaves)

    # ── Build and validate ───────────────────────────────────────────────────
    depth = _compute_max_depth(leaves)
    blueprint = ResearchBlueprint(
        blueprint_id=blueprint_id,
        run_fingerprint=run_fingerprint,
        proposed_action=proposed_action,
        governance_outcome=governance_decision.outcome.value,
        task_leaves=leaves,
        max_dependency_depth=depth,
        human_review_required=human_review_required,
        automatic_publication_allowed=automatic_publication_allowed,
        canonical_mutation_allowed=canonical_mutation_allowed,
        canonical_activation_requires_human_authority=canonical_activation_requires_human_authority,
        run_id=run_id,
        taxon_id=taxon_id,
        research_question=research_question,
        created_at_utc=datetime.now(timezone.utc).isoformat(),
    )
    validate_blueprint(blueprint)
    return blueprint


def validate_blueprint(blueprint: ResearchBlueprint) -> None:
    """Validate a ResearchBlueprint against hard structural limits.

    Raises BlueprintValidationError for any violation.
    """
    leaves = blueprint.task_leaves

    # Fingerprint integrity
    if not _FINGERPRINT_RE.match(blueprint.blueprint_id):
        raise BlueprintValidationError("BLUEPRINT_ID_MALFORMED")
    if not _FINGERPRINT_RE.match(blueprint.run_fingerprint):
        raise BlueprintValidationError("MANIFEST_FINGERPRINT_REQUIRED")

    # Task count limit
    if len(leaves) > MAX_TASK_COUNT:
        raise BlueprintValidationError(
            f"BLUEPRINT_TASK_COUNT_EXCEEDED:{len(leaves)}>{MAX_TASK_COUNT}"
        )

    # Duplicate keys
    keys = [leaf.key for leaf in leaves]
    if len(keys) != len(set(keys)):
        raise BlueprintValidationError("BLUEPRINT_DUPLICATE_TASK_KEYS")

    # Cycle detection
    if _detect_cycles(leaves):
        raise BlueprintValidationError("BLUEPRINT_CYCLE_DETECTED")

    # Dependency depth
    depth = _compute_max_depth(leaves)
    if depth > MAX_DEPENDENCY_DEPTH:
        raise BlueprintValidationError(
            f"BLUEPRINT_DEPENDENCY_DEPTH_EXCEEDED:{depth}>{MAX_DEPENDENCY_DEPTH}"
        )


def enqueue_blueprint(
    blueprint: ResearchBlueprint,
    reservoir: DeepOrchestrate,
) -> int:
    """Register all task leaves from a validated blueprint into the reservoir.

    Idempotent: if a task key already exists in the reservoir, register() returns
    False and the leaf is skipped. Re-running with the same blueprint_id (same
    run_fingerprint + proposed_action) produces 0 newly registered tasks.

    Parameters
    ----------
    blueprint:
        A ResearchBlueprint that has passed validate_blueprint().
    reservoir:
        The canonical DeepOrchestrate instance for this execution context.

    Returns
    -------
    int
        Count of newly registered leaves (0 if all already present — idempotent).
    """
    return reservoir.register_many(list(blueprint.task_leaves))
