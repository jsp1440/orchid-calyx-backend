"""Validated ``oc-traitbank-v1`` payloads.

Field names and invariants follow the Brain reference implementation
(Orchid-Continuum-Brain ``traitbank/model.py``) so a Brain-produced record can
be submitted unchanged, except where the backend is stricter:

- ``subject.taxon_id`` must be a canonical taxonomy id (the
  ``public.orchid_taxonomy.id`` / ``taxonomy_id`` used by research traits, the
  governed Matrix sources and the Knowledge Graph taxon nodes), written as
  digits. Namespaced fixture ids such as ``taxon:1002`` are refused.
- ``confidence`` is optional and stays ``None`` when the source reports none.
- Unknown fields are refused (``extra="forbid"``), so coordinates, locality
  text or private fields cannot travel inside an unrecognised key.
"""

from __future__ import annotations

import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .contract import CONTRACT_VERSION, vocabulary

CANONICAL_TAXON_ID_RE = re.compile(r"^[1-9][0-9]{0,18}$")
TRAIT_ID_RE = re.compile(r"^oc:trait:[a-z0-9_]{2,80}$")
STATISTICS = ("single", "mean", "median", "min", "max", "mode", "range")
SOURCE_KINDS = (
    "publication",
    "dataset",
    "herbarium",
    "living_collection",
    "observation_platform",
    "field_observation",
)
REVIEW_STATUSES = ("unreviewed", "accepted", "corrected", "rejected")

Text = str


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


class ProvenanceIn(_Strict):
    source_id: str = Field(min_length=1, max_length=300)
    source_kind: str
    original_record_id: str = Field(min_length=1, max_length=300)
    citation: str = Field(min_length=1, max_length=4000)
    license: str = Field(min_length=1, max_length=300)
    evidence_type: str
    contributor: str | None = Field(default=None, max_length=300)
    source_url: str | None = Field(default=None, max_length=2000)
    locator: str | None = Field(default=None, max_length=300)
    original_text: str | None = Field(default=None, max_length=8000)
    retrieved_at: str | None = Field(default=None, max_length=64)
    extraction_method: str | None = Field(default=None, max_length=64)
    review_status: str = "unreviewed"
    fixture_status: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _check(self) -> ProvenanceIn:
        _require(self.source_kind in SOURCE_KINDS, "UNKNOWN_SOURCE_KIND")
        _require(
            self.evidence_type in vocabulary("evidence_types"), "UNKNOWN_EVIDENCE_TYPE"
        )
        _require(self.review_status in REVIEW_STATUSES, "UNKNOWN_REVIEW_STATUS")
        if self.source_url:
            _require(
                self.source_url.startswith("https://")
                or self.source_url.startswith("http://"),
                "SOURCE_URL_NOT_HTTP",
            )
        return self


class SubjectIn(_Strict):
    taxon_id: str
    verbatim_taxon_name: str = Field(min_length=1, max_length=300)
    specimen_id: str | None = Field(default=None, max_length=200)
    population_id: str | None = Field(default=None, max_length=200)
    observation_id: str | None = Field(default=None, max_length=200)

    @field_validator("taxon_id", mode="before")
    @classmethod
    def _taxon(cls, value: Any) -> str:
        text = str(value).strip() if value is not None else ""
        if not CANONICAL_TAXON_ID_RE.fullmatch(text):
            raise ValueError("TAXON_ID_NOT_CANONICAL")
        return text


class ValueIn(_Strict):
    kind: str
    numeric: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    unit: str | None = Field(default=None, max_length=40)
    state_id: str | None = Field(default=None, max_length=120)
    statistic: str = "single"
    sd: float | None = None
    n: int | None = None
    uncertainty: float | None = None
    missing_reason: str | None = None
    verbatim: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _check(self) -> ValueIn:
        _require(self.kind in vocabulary("value_kinds"), "UNKNOWN_VALUE_KIND")
        _require(self.statistic in STATISTICS, "UNKNOWN_STATISTIC")
        for number in (
            self.numeric,
            self.minimum,
            self.maximum,
            self.sd,
            self.uncertainty,
        ):
            _require(number is None or math.isfinite(number), "NON_FINITE_VALUE")
        _require(self.n is None or self.n >= 0, "NEGATIVE_SAMPLE_SIZE")
        _require(self.sd is None or self.sd >= 0, "NEGATIVE_SD")
        _require(
            self.uncertainty is None or self.uncertainty >= 0, "NEGATIVE_UNCERTAINTY"
        )
        if self.kind == "quantitative":
            _require(
                self.numeric is not None and bool(self.unit),
                "QUANTITATIVE_VALUE_REQUIRES_NUMBER_AND_UNIT",
            )
        elif self.kind == "range":
            _require(
                self.minimum is not None
                and self.maximum is not None
                and bool(self.unit),
                "RANGE_REQUIRES_BOUNDS_AND_UNIT",
            )
            _require(self.minimum <= self.maximum, "RANGE_BOUNDS_INVERTED")  # type: ignore[operator]
        elif self.kind == "categorical":
            _require(bool(self.state_id), "CATEGORICAL_REQUIRES_STATE")
        else:
            _require(
                self.missing_reason in vocabulary("missing_reasons"),
                "MISSING_REQUIRES_REASON",
            )
            _require(
                self.numeric is None
                and self.state_id is None
                and self.minimum is None
                and self.maximum is None,
                "MISSING_VALUE_CARRIES_DATA",
            )
        return self

    def bounds(self) -> tuple[float, float] | None:
        if self.kind == "quantitative":
            err = self.uncertainty or 0.0
            return (self.numeric - err, self.numeric + err)  # type: ignore[operator]
        if self.kind == "range":
            return (self.minimum, self.maximum)  # type: ignore[return-value]
        return None


class LinkIn(_Strict):
    domain: str
    target_id: str = Field(min_length=1, max_length=300)
    target_label: str = Field(min_length=1, max_length=300)
    relation: str = Field(min_length=1, max_length=120)
    source_id: str = Field(min_length=1, max_length=300)
    note: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def _check(self) -> LinkIn:
        _require(self.domain in vocabulary("link_domains"), "UNKNOWN_LINK_DOMAIN")
        return self


class AssertionIn(_Strict):
    assertion_id: str = Field(min_length=1, max_length=300)
    trait_id: str
    level: str
    subject: SubjectIn
    value: ValueIn
    provenance: ProvenanceIn
    evidence_state: str = "PROVISIONAL"
    scope_basis: str = "direct"
    scope_justification: str | None = Field(default=None, max_length=2000)
    derived_from: tuple[str, ...] = ()
    method_id: str | None = Field(default=None, max_length=120)
    confidence: float | None = None
    life_stage: str | None = Field(default=None, max_length=120)
    habitats: tuple[str, ...] = ()
    links: tuple[LinkIn, ...] = ()
    notes: str = Field(default="", max_length=2000)
    contract_version: Literal["oc-traitbank-v1"] = CONTRACT_VERSION

    @model_validator(mode="after")
    def _check(self) -> AssertionIn:
        _require(bool(TRAIT_ID_RE.fullmatch(self.trait_id)), "TRAIT_ID_FORMAT")
        _require(
            self.level in vocabulary("assertion_levels"), "UNKNOWN_ASSERTION_LEVEL"
        )
        _require(
            self.evidence_state in vocabulary("evidence_states"),
            "UNKNOWN_EVIDENCE_STATE",
        )
        _require(self.scope_basis in vocabulary("scope_bases"), "UNKNOWN_SCOPE_BASIS")
        _require(
            self.confidence is None
            or (math.isfinite(self.confidence) and 0 <= self.confidence <= 1),
            "CONFIDENCE_OUT_OF_RANGE",
        )
        s = self.subject
        if self.level == "specimen":
            _require(bool(s.specimen_id), "SPECIMEN_ASSERTION_REQUIRES_SPECIMEN_ID")
        elif self.level == "population":
            _require(
                bool(s.population_id), "POPULATION_ASSERTION_REQUIRES_POPULATION_ID"
            )
        elif self.level == "observation":
            _require(
                bool(s.observation_id), "OBSERVATION_ASSERTION_REQUIRES_OBSERVATION_ID"
            )
        else:
            _require(self.scope_basis != "direct", "TAXON_ASSERTION_CANNOT_BE_DIRECT")
            if self.scope_basis == "aggregated_with_justification":
                _require(
                    bool(self.scope_justification),
                    "TAXON_GENERALIZATION_REQUIRES_JUSTIFICATION",
                )
                _require(bool(self.derived_from), "AGGREGATE_REQUIRES_DERIVED_FROM")
        if self.value.kind == "missing":
            _require(
                self.evidence_state in ("UNKNOWN", "UNAVAILABLE", "WITHHELD", "ABSENT"),
                "MISSING_VALUE_REQUIRES_NON_VALUE_STATE",
            )
        return self


class EnvironmentRelationIn(_Strict):
    relation_id: str = Field(min_length=1, max_length=300)
    trait_id: str
    environment_variable: str = Field(min_length=1, max_length=300)
    claim_kind: str
    statement: str = Field(min_length=1, max_length=4000)
    provenance: ProvenanceIn
    taxon_scope: tuple[str, ...] = ()
    direction: str | None = Field(default=None, max_length=40)
    effect_size: str | None = Field(default=None, max_length=200)
    n: int | None = None
    hypothesis_scope: str | None = None
    test_design: str | None = Field(default=None, max_length=2000)
    test_outcome: str | None = None

    @model_validator(mode="after")
    def _check(self) -> EnvironmentRelationIn:
        _require(bool(TRAIT_ID_RE.fullmatch(self.trait_id)), "TRAIT_ID_FORMAT")
        _require(
            self.claim_kind in vocabulary("environment_claim_kinds"),
            "UNKNOWN_CLAIM_KIND",
        )
        for taxon_id in self.taxon_scope:
            _require(
                bool(CANONICAL_TAXON_ID_RE.fullmatch(taxon_id)),
                "TAXON_ID_NOT_CANONICAL",
            )
        if self.claim_kind == "observed_correlation":
            _require(
                self.hypothesis_scope is None and self.test_outcome is None,
                "CORRELATION_CANNOT_CARRY_HYPOTHESIS_OUTCOME",
            )
        else:
            _require(
                self.hypothesis_scope in ("adaptive", "evolutionary", "physiological"),
                "HYPOTHESIS_REQUIRES_SCOPE",
            )
        if self.claim_kind == "tested_hypothesis":
            _require(bool(self.test_design), "TESTED_HYPOTHESIS_REQUIRES_DESIGN")
            _require(
                self.test_outcome in ("supported", "not_supported", "inconclusive"),
                "TESTED_HYPOTHESIS_REQUIRES_OUTCOME",
            )
        if self.claim_kind == "proposed_hypothesis":
            _require(
                self.test_outcome is None, "UNTESTED_HYPOTHESIS_CANNOT_HAVE_OUTCOME"
            )
        return self

    def describe(self) -> str:
        if self.claim_kind == "observed_correlation":
            return f"Observed correlation (not a causal or adaptive explanation): {self.statement}"
        if self.claim_kind == "proposed_hypothesis":
            return f"Untested {self.hypothesis_scope} hypothesis: {self.statement}"
        return (
            f"Tested {self.hypothesis_scope} hypothesis ({self.test_design}); "
            f"outcome: {self.test_outcome}. {self.statement}"
        )


class TraitStateIn(_Strict):
    state_id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=200)
    oao_id: str | None = None


class MethodIn(_Strict):
    method_id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class TraitDefinitionIn(_Strict):
    trait_id: str
    label: str = Field(min_length=1, max_length=200)
    domain: str
    structure: str = Field(min_length=1, max_length=200)
    property: str = Field(min_length=1, max_length=200)
    value_kind: Literal["quantitative", "categorical"]
    unit: str | None = Field(default=None, max_length=40)
    states: tuple[TraitStateIn, ...] = ()
    methods: tuple[MethodIn, ...] = ()
    oao_character_id: str | None = None
    structure_ontology_ids: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    description: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def _check(self) -> TraitDefinitionIn:
        _require(bool(TRAIT_ID_RE.fullmatch(self.trait_id)), "TRAIT_ID_FORMAT")
        if self.value_kind == "quantitative":
            _require(bool(self.unit), "QUANTITATIVE_TRAIT_REQUIRES_UNIT")
        else:
            _require(bool(self.states), "CATEGORICAL_TRAIT_REQUIRES_STATES")
        return self

    def state(self, state_id: str) -> TraitStateIn | None:
        return next((s for s in self.states if s.state_id == state_id), None)


class TraitBankBatch(_Strict):
    """One controlled ingestion unit. ``batch_key`` is the caller's idempotency key."""

    contract_version: Literal["oc-traitbank-v1"]
    batch_key: str = Field(min_length=8, max_length=200)
    producer: Literal["literature_extraction", "eol_traitbank", "curated"]
    assertions: tuple[AssertionIn, ...] = Field(default=(), max_length=5000)
    environment_relations: tuple[EnvironmentRelationIn, ...] = Field(
        default=(), max_length=1000
    )

    @model_validator(mode="after")
    def _unique(self) -> TraitBankBatch:
        ids = [a.assertion_id for a in self.assertions]
        _require(len(ids) == len(set(ids)), "DUPLICATE_ASSERTION_ID_IN_BATCH")
        keys = [
            (a.provenance.source_id, a.provenance.original_record_id, a.trait_id)
            for a in self.assertions
        ]
        _require(len(keys) == len(set(keys)), "DUPLICATE_SOURCE_RECORD_IN_BATCH")
        rel_ids = [r.relation_id for r in self.environment_relations]
        _require(len(rel_ids) == len(set(rel_ids)), "DUPLICATE_RELATION_ID_IN_BATCH")
        return self
