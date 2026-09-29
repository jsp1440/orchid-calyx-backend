"""Versioned API contracts for the field hypothesis loop (journey 6).

Epistemic contract, stated once and enforced everywhere in this package:

- An observation is *evidence with provenance*, not a fact. It enters here as a
  snapshot the caller already holds (the Field Journal / journey-5 record), so
  this module never becomes a second observation store.
- A hypothesis is *something nobody has established*. Every hypothesis carries
  ``epistemic_status = "HYPOTHESIS"`` and there is no state in this vocabulary
  that means "confirmed" or "accepted". Refinement and retirement are human
  decisions recorded with a rationale.
- Supporting, contradicting and unknown evidence are recorded separately and
  never collapsed into a score, probability or verdict.
- Protected locality never enters this contract. Coordinates and locality
  fields are rejected at validation (``extra="forbid"`` plus the shared
  sensitive-locality guard), and only a coarse sensitivity class travels.

Vocabularies reuse Orchid Continuum Brain records where one exists:
KO-0038 (pollination strategy and evidence types) and KO-0024 (review status).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.calyx_flywheel.locality import assert_no_sensitive_locality

CONTRACT_VERSION = "field-hypotheses/v1"

#: The loop is only useful when explanations compete. Fewer than two is a defect.
MINIMUM_COMPETING_HYPOTHESES = 2

#: No path in this package publishes to the Knowledge Graph; this is the
#: constant every response states so no consumer has to infer it.
KNOWLEDGE_GRAPH_PUBLICATION = "blocked_pending_human_scientific_review"


# ---------------------------------------------------------------------------
# Controlled vocabularies
# ---------------------------------------------------------------------------


class ObserverCertainty(str, Enum):
    """Observer-asserted identification certainty (mirrors journey-5 labels).

    Observer-asserted, not a scientific determination; CONFIRMED here does not
    mean verified.
    """

    CONFIRMED = "CONFIRMED"
    PROBABLE = "PROBABLE"
    POSSIBLE = "POSSIBLE"
    UNCERTAIN = "UNCERTAIN"


class LocalitySensitivity(str, Enum):
    """Coarse locality class — the only locality information this loop accepts."""

    PRIVATE = "PRIVATE"
    RESEARCH_RESTRICTED = "RESEARCH_RESTRICTED"
    PUBLIC = "PUBLIC"


class VisitorGroup(str, Enum):
    """Functional visitor groups (KO-0038 §2)."""

    BEE = "bee"
    MALE_BEE = "male_bee"
    EUGLOSSINE_BEE = "euglossine_bee"
    OIL_COLLECTING_BEE = "oil_collecting_bee"
    WASP = "wasp"
    MALE_WASP = "male_wasp"
    FLY = "fly"
    FUNGUS_GNAT = "fungus_gnat"
    MOTH = "moth"
    BUTTERFLY = "butterfly"
    BEETLE = "beetle"
    BIRD = "bird"
    ANT = "ant"
    OTHER = "other"
    UNKNOWN = "unknown"


class VisitorBehavior(str, Enum):
    """What the observer saw the visitor do. Descriptive, not interpretive."""

    PROBING_FOR_NECTAR = "probing_for_nectar"
    PSEUDOCOPULATION_LIKE_CONTACT = "pseudocopulation_like_contact"
    ATTEMPTED_OVIPOSITION = "attempted_oviposition"
    RESTING_OR_SHELTERING = "resting_or_sheltering"
    POLLEN_OR_FRAGRANCE_COLLECTION = "pollen_or_fragrance_collection"
    BRIEF_LANDING_NO_COLUMN_CONTACT = "brief_landing_no_column_contact"
    POLLINARIUM_SEEN_ON_VISITOR = "pollinarium_seen_on_visitor"
    POLLINIA_REMOVED = "pollinia_removed"
    POLLINIA_DEPOSITED = "pollinia_deposited"


class RewardCheck(str, Enum):
    """Result of a *visual* reward check. Dissection is never requested."""

    NECTAR_PRESENT = "nectar_present"
    NECTAR_ABSENT = "nectar_absent"
    NOT_CHECKED = "not_checked"


class FloralSignalCue(str, Enum):
    """Floral signals the observer noted (KO-0038 §5, observer-level)."""

    SCENT_DETECTED = "scent_detected"
    NO_SCENT_DETECTED = "no_scent_detected"
    INSECT_LIKE_LABELLUM = "insect_like_labellum"
    RESEMBLES_REWARDING_FLOWER_NEARBY = "resembles_rewarding_flower_nearby"
    DARK_SPOTS_OR_FUNGAL_RESEMBLANCE = "dark_spots_or_fungal_resemblance"
    CARRION_OR_DUNG_ODOR = "carrion_or_dung_odor"
    MOTILE_PARTS = "motile_parts"
    WARMTH_DETECTED = "warmth_detected"
    OIL_OR_RESIN_SECRETION = "oil_or_resin_secretion"


class ReproductiveOutcomeCue(str, Enum):
    """Reproductive outcome the observer could see (KO-0038 §7)."""

    FRUIT_SET_OBSERVED = "fruit_set_observed"
    NO_FRUIT_SET_OBSERVED = "no_fruit_set_observed"
    UNKNOWN = "unknown"


class HypothesisClass(str, Enum):
    """Explanation classes. KO-0038 strategies plus the two alternatives that
    must always be able to compete: an ineffective visitor and a misidentified
    subject."""

    SEXUAL_DECEPTION = "sexual_deception"
    FOOD_DECEPTION = "food_deception"
    BROOD_SITE_DECEPTION = "brood_site_deception"
    SHELTER_MIMICRY = "shelter_mimicry"
    REWARD_BASED = "reward_based"
    AUTOGAMY = "autogamy"
    UNOBSERVED_POLLINATOR = "unobserved_pollinator"
    NON_POLLINATING_VISIT = "non_pollinating_visit"
    IDENTIFICATION_UNCERTAINTY = "identification_uncertainty"


class EvidenceStance(str, Enum):
    """How one evidence item bears on one hypothesis. Recorded separately."""

    SUPPORTING = "SUPPORTING"
    CONTRADICTING = "CONTRADICTING"
    UNKNOWN = "UNKNOWN"


class PollinationEvidenceType(str, Enum):
    """Evidence types (KO-0038 §3)."""

    DIRECTLY_OBSERVED_VISIT = "directly_observed_visit"
    POLLEN_TRANSFER_OBSERVED = "pollen_transfer_observed"
    POLLINARIUM_ATTACHED_TO_POLLINATOR = "pollinarium_attached_to_pollinator"
    FRUIT_SET_AFTER_VISIT = "fruit_set_after_visit"
    EXPERIMENTAL_EXCLUSION = "experimental_exclusion"
    SCENT_CHEMISTRY_MATCH = "scent_chemistry_match"
    MORPHOLOGY_MATCH = "morphology_match"
    LITERATURE_REPORT = "literature_report"
    INFERRED_SYNDROME = "inferred_syndrome"
    AI_SUGGESTED_HYPOTHESIS = "ai_suggested_hypothesis"
    UNKNOWN = "unknown"


class EvidenceSourceKind(str, Enum):
    FIELD_OBSERVATION = "field_observation"
    MEDIA = "media"
    LITERATURE = "literature"
    ATLAS = "atlas"
    EXPERT_NOTE = "expert_note"
    OTHER = "other"


class HypothesisStatus(str, Enum):
    """Lifecycle. Deliberately has no accepted/confirmed member."""

    PROPOSED = "PROPOSED"
    UNDER_EVALUATION = "UNDER_EVALUATION"
    REFINED = "REFINED"
    RETIRED = "RETIRED"


class ReviewState(str, Enum):
    """Subset of KO-0024 review status vocabulary used by this loop."""

    MACHINE_ASSISTED = "machine_assisted"
    HUMAN_REVIEWED = "human_reviewed"
    EXPERT_REVIEWED = "expert_reviewed"
    NEEDS_FOLLOWUP = "needs_followup"


class EvidenceState(str, Enum):
    """Derived from the evidence balance; describes the record, not the truth."""

    NO_EVIDENCE = "no_evidence"
    SUPPORTING_ONLY = "supporting_only"
    CONTRADICTING_ONLY = "contradicting_only"
    CONFLICTING = "conflicting"
    UNKNOWN_ONLY = "unknown_only"


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


class InteractionContext(BaseModel):
    """Observer-level interaction cues. Every field is optional so a bare
    observation still produces competing hypotheses."""

    model_config = ConfigDict(extra="forbid")

    visitor_observed: bool = False
    visitor_group: VisitorGroup = VisitorGroup.UNKNOWN
    visitor_behaviors: list[VisitorBehavior] = Field(default_factory=list)
    reward_check: RewardCheck = RewardCheck.NOT_CHECKED
    floral_signal_cues: list[FloralSignalCue] = Field(default_factory=list)
    reproductive_outcome: ReproductiveOutcomeCue = ReproductiveOutcomeCue.UNKNOWN
    time_of_day: str | None = Field(default=None, max_length=50)
    weather: str | None = Field(default=None, max_length=200)


class ObservationSnapshot(BaseModel):
    """The journey-5 observation as the caller holds it, minus locality.

    ``extra="forbid"`` rejects latitude/longitude/location fields outright, and
    the shared sensitive-locality guard runs as well so a rename cannot slip a
    coordinate through.
    """

    model_config = ConfigDict(extra="forbid")

    observer_id: str = Field(
        ..., min_length=1, max_length=500, description="Opaque auth subject — never an email."
    )
    observed_at: datetime
    taxon_hint: str | None = Field(
        default=None, max_length=500, description="Observer's proposed taxon — not a determination."
    )
    observation_text: str | None = Field(default=None, max_length=10_000)
    epistemic_certainty: ObserverCertainty = ObserverCertainty.POSSIBLE
    locality_sensitivity: LocalitySensitivity = LocalitySensitivity.PRIVATE
    media_content_hashes: list[str] = Field(
        default_factory=list,
        max_length=50,
        description="SHA-256 hex digests of attached media; opaque provenance references only.",
    )
    interaction: InteractionContext = Field(default_factory=InteractionContext)

    @field_validator("media_content_hashes")
    @classmethod
    def _hex_digests(cls, values: list[str]) -> list[str]:
        for value in values:
            if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value.lower()):
                raise ValueError("media_content_hashes entries must be SHA-256 hex digests")
        return [value.lower() for value in values]

    @model_validator(mode="after")
    def _no_protected_locality(self) -> ObservationSnapshot:
        assert_no_sensitive_locality(self.model_dump(mode="json"))
        return self


class EvidenceRecordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stance: EvidenceStance
    evidence_type: PollinationEvidenceType
    summary: str = Field(..., min_length=1, max_length=2_000)
    source_kind: EvidenceSourceKind
    source_reference: str | None = Field(
        default=None,
        max_length=500,
        description="DOI, observation id, media content hash or similar opaque reference.",
    )
    recorder_subject: str = Field(..., min_length=1, max_length=500, description="Opaque identity.")

    @model_validator(mode="after")
    def _no_protected_locality(self) -> EvidenceRecordIn:
        assert_no_sensitive_locality(self.model_dump(mode="json"))
        return self


class ReviewDecisionIn(BaseModel):
    """A human decision about a hypothesis. Requires an authenticated actor."""

    model_config = ConfigDict(extra="forbid")

    status: HypothesisStatus
    review_state: ReviewState
    rationale: str = Field(..., min_length=1, max_length=4_000)
    refined_statement: str | None = Field(default=None, max_length=2_000)

    @field_validator("status")
    @classmethod
    def _human_decidable_status(cls, value: HypothesisStatus) -> HypothesisStatus:
        if value == HypothesisStatus.PROPOSED:
            raise ValueError("PROPOSED is the machine starting state; a review must decide something")
        return value

    @field_validator("review_state")
    @classmethod
    def _human_review_state(cls, value: ReviewState) -> ReviewState:
        if value == ReviewState.MACHINE_ASSISTED:
            raise ValueError("a human review cannot set review_state to machine_assisted")
        return value

    @model_validator(mode="after")
    def _refinement_needs_statement(self) -> ReviewDecisionIn:
        if self.status == HypothesisStatus.REFINED and not (self.refined_statement or "").strip():
            raise ValueError("refined_statement is required when status is REFINED")
        return self


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------


class EvidenceBalance(BaseModel):
    supporting: int = 0
    contradicting: int = 0
    unknown: int = 0


class EvidenceRecordOut(BaseModel):
    evidence_id: str
    hypothesis_id: str
    stance: EvidenceStance
    evidence_type: PollinationEvidenceType
    summary: str
    source_kind: EvidenceSourceKind
    source_reference: str | None
    recorder_subject: str
    recorded_at: datetime
    created: bool = True


class FollowUpObservation(BaseModel):
    """One field action a researcher can take while still on site."""

    step_id: str
    instruction: str
    purpose: str
    non_destructive: Literal[True] = True
    while_on_site: bool
    discriminates: list[HypothesisClass]


class HumanReview(BaseModel):
    actor: str
    auth_type: str
    rationale: str
    reviewed_at: datetime


class HypothesisOut(BaseModel):
    hypothesis_id: str
    set_id: str
    observation_id: str
    template_id: str
    hypothesis_class: HypothesisClass
    ko_0038_strategy: str
    epistemic_status: Literal["HYPOTHESIS"] = "HYPOTHESIS"
    statement: str
    predictions: list[str]
    would_support: list[str]
    would_contradict: list[str]
    cue_matches: list[str]
    question_family_ids: list[str]
    status: HypothesisStatus
    review_state: ReviewState
    human_review: HumanReview | None = None
    evidence_balance: EvidenceBalance
    evidence_state: EvidenceState
    evidence: list[EvidenceRecordOut]
    knowledge_graph_publication: str = KNOWLEDGE_GRAPH_PUBLICATION


class GenerationProvenance(BaseModel):
    mode: Literal["deterministic_rule_library"] = "deterministic_rule_library"
    library_version: str
    contract_version: str = CONTRACT_VERSION
    provider_called: Literal[False] = False
    basis: str
    cue_tokens: list[str]


class ObservationSummary(BaseModel):
    """Locality-free echo of what the generation saw. ``observation_text`` is
    deliberately not echoed: free text is the one place a locality could hide."""

    observer_id: str
    observed_at: datetime
    taxon_hint: str | None
    epistemic_certainty: ObserverCertainty
    locality_sensitivity: LocalitySensitivity
    media_count: int


class HypothesisSetOut(BaseModel):
    set_id: str
    observation_id: str
    observation_fingerprint: str
    created: bool
    generated_at: datetime
    generation: GenerationProvenance
    observation: ObservationSummary
    minimum_competing_hypotheses: int = MINIMUM_COMPETING_HYPOTHESES
    hypotheses: list[HypothesisOut]
    follow_up_protocol: list[FollowUpObservation]
    protocol_constraints: list[str]
    review_state: ReviewState = ReviewState.MACHINE_ASSISTED
    knowledge_graph_publication: str = KNOWLEDGE_GRAPH_PUBLICATION


class LibraryTemplateOut(BaseModel):
    template_id: str
    hypothesis_class: HypothesisClass
    ko_0038_strategy: str
    statement_template: str
    positive_cues: list[str]
    question_family_ids: list[str]
    always_included_when: list[str]


class LibraryOut(BaseModel):
    library_version: str
    contract_version: str = CONTRACT_VERSION
    basis: str
    minimum_competing_hypotheses: int = MINIMUM_COMPETING_HYPOTHESES
    question_families: list[str]
    templates: list[LibraryTemplateOut]
    protocol_constraints: list[str]
    knowledge_graph_publication: str = KNOWLEDGE_GRAPH_PUBLICATION
