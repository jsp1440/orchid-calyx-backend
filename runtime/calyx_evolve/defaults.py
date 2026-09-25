"""The default staging campaign: cognition inputs and deterministic candidates.

Phase 1 does not need a model to generate candidates.  A small, hand-written,
deterministic ladder is enough to prove the loop, and it keeps the first PR
free of provider dependencies and provider transcripts.  Each candidate names a
parent so lineage is exercised, and one of them is deliberately wrong in the way
that matters most — it removes the ambiguity guard and produces a false merge
while its aggregate score improves.
"""

from __future__ import annotations

from typing import Any

from runtime.calyx_evolve.campaign import EvolveCampaign
from runtime.calyx_evolve.candidates import (
    BASELINE_CONFIG,
    GENERATOR_FIXTURE,
    GENERATOR_MUTATION,
    Candidate,
)
from runtime.calyx_evolve.cognition import (
    KIND_EVALUATOR_VERSION,
    KIND_EXPERT_RULE,
    KIND_SOURCE_RELEASE,
    CognitionItem,
)
from runtime.calyx_evolve.fixture import TaxonomyFixture, locked_fixture
from runtime.calyx_evolve.metrics import EVALUATOR_VERSION, SCORING_VERSION
from runtime.calyx_evolve.selection import POLICY_BEST_ELIGIBLE

DEFAULT_CAMPAIGN_ID = "calyx-evolve-001-taxonomy-reconciliation"
DEFAULT_CAMPAIGN_TITLE = "Taxonomy reconciliation strategy search (staging fixture)"

CANDIDATE_BASELINE = "baseline-exact-normalised"
CANDIDATE_FUZZY_GUARDED = "fuzzy-d1-ambiguity-guarded"
CANDIDATE_FUZZY_UNGUARDED = "fuzzy-d1-ambiguity-unguarded"
CANDIDATE_AUTHORSHIP_BLIND = "authorship-blind"

RECORDED_AT = "2026-08-26T00:00:00+00:00"


def default_campaign(**overrides: Any) -> EvolveCampaign:
    settings: dict[str, Any] = {
        "campaign_id": DEFAULT_CAMPAIGN_ID,
        "title": DEFAULT_CAMPAIGN_TITLE,
        "baseline_candidate_id": CANDIDATE_BASELINE,
        "selection_policy": POLICY_BEST_ELIGIBLE,
    }
    settings.update(overrides)
    return EvolveCampaign(**settings)


def default_cognition(fixture: TaxonomyFixture | None = None) -> tuple[CognitionItem, ...]:
    """The versioned inputs the loop is permitted to learn from."""

    fixture = fixture or locked_fixture()
    return (
        CognitionItem(
            item_id="locked-reconciliation-release",
            kind=KIND_SOURCE_RELEASE,
            version=fixture.version,
            summary=(
                "Locked synthetic reconciliation release used for staging experiments. "
                "Not production taxonomy and not the Hassler acceptance corpus."
            ),
            provenance={
                "origin": "LOCKED_FIXTURE_RELEASE",
                "reference": fixture.release_id,
                "recorded_at": RECORDED_AT,
                "release_checksum": fixture.release_checksum,
            },
            payload={
                "fixture_id": fixture.fixture_id,
                "fixture_hash": fixture.fixture_hash,
                "reference_taxa": len(fixture.reference_taxa),
                "records": len(fixture.records),
            },
        ),
        CognitionItem(
            item_id="evaluator-contract",
            kind=KIND_EVALUATOR_VERSION,
            version=EVALUATOR_VERSION,
            summary=(
                "Deterministic taxonomy evaluator reporting accuracy, false merges, "
                "abstentions, provenance completeness, replay determinism, runtime and cost."
            ),
            provenance={
                "origin": "CALYX_EVALUATOR_REGISTRY",
                "reference": EVALUATOR_VERSION,
                "recorded_at": RECORDED_AT,
                "scoring_version": SCORING_VERSION,
            },
            payload={"scoring_version": SCORING_VERSION},
        ),
        CognitionItem(
            item_id="expert-rule-abstain-on-ambiguity",
            kind=KIND_EXPERT_RULE,
            version="1.0.0",
            summary=(
                "Documented curator rule: when an observed name is equidistant from two "
                "accepted taxa, abstain. A wrong merge is more damaging than an unresolved "
                "record because it silently destroys a distinction."
            ),
            provenance={
                "origin": "REVIEWED_CURATION_RULE",
                "reference": "orchid-continuum/taxonomy-curation-rules#abstain-on-ambiguity",
                "recorded_at": RECORDED_AT,
            },
            payload={},
        ),
        CognitionItem(
            item_id="expert-rule-authorship-is-not-identity",
            kind=KIND_EXPERT_RULE,
            version="1.0.0",
            summary=(
                "Documented curator rule: authorship is metadata attached to a name, not "
                "part of the name string, so it must be stripped before matching."
            ),
            provenance={
                "origin": "REVIEWED_CURATION_RULE",
                "reference": "orchid-continuum/taxonomy-curation-rules#authorship-is-not-identity",
                "recorded_at": RECORDED_AT,
            },
            payload={},
        ),
    )


def default_candidates(campaign_id: str = DEFAULT_CAMPAIGN_ID) -> tuple[Candidate, ...]:
    """The deterministic candidate ladder for phase 1."""

    return (
        Candidate(
            candidate_id=CANDIDATE_BASELINE,
            campaign_id=campaign_id,
            label="Exact match after normalisation",
            hypothesis=(
                "Normalising whitespace, case and authorship and then matching exactly is "
                "the safest reconciliation: it never merges two distinct taxa."
            ),
            config=BASELINE_CONFIG,
            generator=GENERATOR_FIXTURE,
            is_baseline=True,
        ),
        Candidate(
            candidate_id=CANDIDATE_FUZZY_GUARDED,
            campaign_id=campaign_id,
            label="Distance-1 fuzzy with ambiguity guard",
            hypothesis=(
                "Allowing a single-character edit resolves transcription typos, and "
                "abstaining on ties keeps the false-merge count at zero."
            ),
            config=BASELINE_CONFIG.mutate(fuzzy_max_distance=1, ambiguity_guard=True),
            generator=GENERATOR_MUTATION,
            parent_ids=(CANDIDATE_BASELINE,),
        ),
        Candidate(
            candidate_id=CANDIDATE_FUZZY_UNGUARDED,
            campaign_id=campaign_id,
            label="Distance-1 fuzzy without ambiguity guard",
            hypothesis=(
                "Always taking the nearest neighbour resolves more records than abstaining "
                "on ties. This is expected to trade a false merge for coverage."
            ),
            config=BASELINE_CONFIG.mutate(fuzzy_max_distance=1, ambiguity_guard=False),
            generator=GENERATOR_MUTATION,
            parent_ids=(CANDIDATE_FUZZY_GUARDED,),
        ),
        Candidate(
            candidate_id=CANDIDATE_AUTHORSHIP_BLIND,
            campaign_id=campaign_id,
            label="Match without stripping authorship",
            hypothesis=(
                "Treating the full label including authorship as the match key preserves "
                "more of the source string. This is expected to regress against the baseline."
            ),
            config=BASELINE_CONFIG.mutate(strip_authorship=False),
            generator=GENERATOR_MUTATION,
            parent_ids=(CANDIDATE_BASELINE,),
        ),
    )
