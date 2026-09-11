"""Read-only operator surface for the CALYX-EVOLVE-001 experiment loop.

Mission Control and the Verification Workbench need to inspect campaign status,
baseline-versus-candidate comparisons, candidate lineage, the complete metric
vector, analyzer findings and counterevidence, replay evidence, and promotion
state.  Every route below except one is a plain read.

The single write route creates a **staging** experiment cycle.  It is bounded by
construction: it accepts no strategy configuration from the caller, only which of
the campaign's registered deterministic candidates to run.  Governance state
(``DRAFT``) and execution scope (``STAGING_ONLY``) are set here, not by the
request, so a caller cannot widen them.

There is deliberately no activation, approval or publication route in this
module, and none belongs in this phase.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.calyx_evolve.analysis import ANALYZER_VERSION
from runtime.calyx_evolve.campaign import CampaignRunner
from runtime.calyx_evolve.defaults import (
    DEFAULT_CAMPAIGN_ID,
    default_campaign,
    default_candidates,
    default_cognition,
)
from runtime.calyx_evolve.fixture import locked_fixture
from runtime.calyx_evolve.governance import GOVERNANCE_DRAFT
from runtime.calyx_evolve.memory import (
    ExperimentMemory,
    InMemoryExperimentMemory,
    build_experiment_memory,
    persistence_mode,
)
from runtime.calyx_evolve.metrics import (
    EVALUATOR_VERSION,
    SCORING_VERSION,
    metric_catalogue,
)
from runtime.calyx_evolve.safety import SCOPE_STAGING_ONLY
from runtime.calyx_evolve.selection import SELECTION_POLICIES
from runtime.calyx_evolve.status import (
    campaign_index,
    campaign_status,
    candidate_comparison,
)

router = APIRouter(prefix="/api/calyx-evolve", tags=["CALYX-EVOLVE-001"])

#: Upper bound on candidates one request may run.  The loop is bounded by
#: design; this stops a single call from queueing an unbounded sweep.
MAX_CANDIDATES_PER_REQUEST = 8

#: Process-local memory used only when no DATABASE_URL is configured, so the
#: read surface stays usable in a local or test deployment.
_FALLBACK_MEMORY = InMemoryExperimentMemory()


def get_memory() -> ExperimentMemory:
    """Return durable memory when configured, otherwise process-local memory."""

    if persistence_mode() == "postgres":
        return build_experiment_memory()
    return _FALLBACK_MEMORY


class ExperimentRequest(BaseModel):
    """Bounded staging experiment request.

    No reconciliation configuration is accepted from the caller: candidates are
    the campaign's registered deterministic ladder, referenced by id.
    """

    candidate_ids: list[str] | None = Field(
        default=None,
        description=(
            "Subset of the campaign's registered candidate ids to run. "
            "Omit to run the full deterministic ladder. The baseline is always included."
        ),
    )


def _governance_block() -> dict[str, Any]:
    return {
        "governance_state": GOVERNANCE_DRAFT,
        "execution_scope": SCOPE_STAGING_ONLY,
        "requires_human_scientific_review": True,
        "taxonomy_activation_permitted": False,
        "knowledge_graph_publication_permitted": False,
        "external_publication_permitted": False,
        "production_mutation_permitted": False,
    }


@router.get("/contract")
def evolve_contract(
    auth: dict[str, object] = Depends(verify_owner_or_api_key),
) -> dict[str, Any]:
    """Versions, metric catalogue, fixture descriptor and governance invariants."""

    return {
        "versions": {
            "evaluator_version": EVALUATOR_VERSION,
            "scoring_version": SCORING_VERSION,
            "analyzer_version": ANALYZER_VERSION,
        },
        "fixture": locked_fixture().descriptor(),
        "metric_catalogue": metric_catalogue(),
        "selection_policies": list(SELECTION_POLICIES),
        "governance": _governance_block(),
        "persistence_mode": persistence_mode(),
        "max_candidates_per_request": MAX_CANDIDATES_PER_REQUEST,
    }


@router.get("/campaigns")
def list_campaigns(
    auth: dict[str, object] = Depends(verify_owner_or_api_key),
) -> dict[str, Any]:
    return campaign_index(get_memory())


@router.get("/campaigns/{campaign_id}")
def read_campaign(
    campaign_id: str,
    auth: dict[str, object] = Depends(verify_owner_or_api_key),
) -> dict[str, Any]:
    status = campaign_status(get_memory(), campaign_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"unknown campaign {campaign_id!r}")
    return status


@router.get("/campaigns/{campaign_id}/candidates/{candidate_id}")
def read_candidate_comparison(
    campaign_id: str,
    candidate_id: str,
    auth: dict[str, object] = Depends(verify_owner_or_api_key),
) -> dict[str, Any]:
    comparison = candidate_comparison(get_memory(), campaign_id, candidate_id)
    if comparison is None:
        raise HTTPException(
            status_code=404,
            detail=f"no run for candidate {candidate_id!r} in campaign {campaign_id!r}",
        )
    return comparison


@router.post("/campaigns/{campaign_id}/experiments")
def create_staging_experiment(
    campaign_id: str,
    request: ExperimentRequest,
    auth: dict[str, object] = Depends(verify_owner_or_api_key),
) -> dict[str, Any]:
    """Run one bounded, staging-only cycle of the deterministic candidate ladder.

    Re-running is safe: every experiment is keyed by its replay key, so a repeat
    request reuses the stored records rather than spending or duplicating work.
    """

    if campaign_id != DEFAULT_CAMPAIGN_ID:
        raise HTTPException(
            status_code=404,
            detail=(
                f"campaign {campaign_id!r} is not a registered staging campaign; "
                f"this phase defines only {DEFAULT_CAMPAIGN_ID!r}"
            ),
        )

    campaign = default_campaign()
    ladder = default_candidates(campaign_id)
    by_id = {candidate.candidate_id: candidate for candidate in ladder}

    if request.candidate_ids is None:
        selected = list(ladder)
    else:
        unknown = sorted(set(request.candidate_ids) - set(by_id))
        if unknown:
            raise HTTPException(
                status_code=400, detail=f"unknown candidate ids: {unknown}"
            )
        wanted = set(request.candidate_ids) | {campaign.baseline_candidate_id}
        selected = [c for c in ladder if c.candidate_id in wanted]

    if len(selected) > MAX_CANDIDATES_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=(
                f"request would run {len(selected)} candidates; the bound is "
                f"{MAX_CANDIDATES_PER_REQUEST}"
            ),
        )

    memory = get_memory()
    report = CampaignRunner(memory=memory).cycle(
        campaign, default_cognition(), selected
    )
    return {
        "report": report.to_dict(),
        "governance": _governance_block(),
        "status_url": f"/api/calyx-evolve/campaigns/{campaign_id}",
    }
