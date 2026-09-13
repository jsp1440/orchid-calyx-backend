"""Tests for OC-COMPLETE-007 CONVERGE child tasks.

Covers:
- OC-COMPLETE-007-glossary-intake-wire: GlossaryExtractor → Lexicon intake staging
- OC-COMPLETE-007-matrix-vision-canonical-path: Vision → Matrix canonical path
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.multimodal_intelligence.contracts import (
    CharacterObservation,
    ImageAnalysisResult,
    ModelProvenance,
    PlantPartDetection,
)
from app.scientific_adapter_lab.glossary_intake_bridge import (
    BRIDGE_SCHEMA_VERSION,
    GlossaryIntakeStagingRecord,
    stage_glossary_terms_for_intake,
)
from app.scientific_adapter_lab.matrix_vision_canonical_path import (
    CANONICAL_PATH_DESCRIPTION,
    PATH_SCHEMA_VERSION,
    batch_path,
    describe_canonical_path,
    guard_vision_analysis_entry,
)

# ---------------------------------------------------------------------------
# Fixtures — minimal GlossaryTerm stubs (matches literature_extraction shape)
# ---------------------------------------------------------------------------


@dataclass
class _Provenance:
    method: str = "rule_extracted"
    confidence: float = 0.85
    extractor: str = "glossary"
    extractor_version: str = "0.1.0"


@dataclass
class _SourceSpan:
    char_start: int = 0
    char_end: int = 10
    section_id: str = "abstract"


@dataclass
class _GlossaryTerm:
    term_id: str
    term: str
    normalized_term: str
    status: str = "candidate"
    mentions: list[Any] = field(default_factory=list)
    provenance: _Provenance = field(default_factory=_Provenance)


_SOURCE_HASH = "a" * 64


def _make_terms() -> list[_GlossaryTerm]:
    span = _SourceSpan()
    return [
        _GlossaryTerm(
            term_id="glossary-abc01",
            term="velamen",
            normalized_term="velamen",
            mentions=[span, span],
            provenance=_Provenance(confidence=1.0),
        ),
        _GlossaryTerm(
            term_id="glossary-def02",
            term="pollinium",
            normalized_term="pollinium",
            mentions=[span],
            provenance=_Provenance(confidence=0.9),
        ),
        _GlossaryTerm(
            term_id="glossary-ghi03",
            term="labellum",
            normalized_term="labellum",
            mentions=[],
            provenance=_Provenance(confidence=0.7),
        ),
    ]


# ---------------------------------------------------------------------------
# Minimal ImageAnalysisResult fixture
# ---------------------------------------------------------------------------


_MODEL_PROV = ModelProvenance(
    provider="anthropic",
    model_name="claude-fixture",
    model_version="v1",
    inference_id="inf-fixture-00001",
)

_VALID_IMAGE = ImageAnalysisResult(
    image_id="idigbio:uuid:fixture-001",
    content_hash="b" * 64,
    license_code="CC-BY-4.0",
    attribution="Field Museum — CC-BY-4.0",
    model=_MODEL_PROV,
    detected_parts=(
        PlantPartDetection(part="labellum", confidence=0.85),
    ),
    character_observations=(
        CharacterObservation(
            character_id="chr:labellum_color",
            state="pink",
            confidence=0.80,
            provenance=("vision-fixture",),
        ),
    ),
)


# ===========================================================================
# OC-COMPLETE-007-glossary-intake-wire
# ===========================================================================


class TestGlossaryIntakeBridgeRecordInvariants:
    def test_status_is_always_candidate(self):
        batch = stage_glossary_terms_for_intake(_make_terms(), source_hash=_SOURCE_HASH)
        for rec in batch.records:
            assert rec.status == "candidate"

    def test_concept_intake_state_is_pending_review(self):
        batch = stage_glossary_terms_for_intake(_make_terms(), source_hash=_SOURCE_HASH)
        for rec in batch.records:
            assert rec.concept_intake_state == "PENDING_REVIEW"

    def test_review_required_always_true(self):
        batch = stage_glossary_terms_for_intake(_make_terms(), source_hash=_SOURCE_HASH)
        for rec in batch.records:
            assert rec.review_required is True

    def test_auto_promotion_blocked_always_true(self):
        batch = stage_glossary_terms_for_intake(_make_terms(), source_hash=_SOURCE_HASH)
        for rec in batch.records:
            assert rec.auto_promotion_blocked is True

    def test_no_graph_mutation(self):
        batch = stage_glossary_terms_for_intake(_make_terms(), source_hash=_SOURCE_HASH)
        assert batch.graph_mutation is False

    def test_all_records_valid(self):
        batch = stage_glossary_terms_for_intake(_make_terms(), source_hash=_SOURCE_HASH)
        errors = batch.validate_all()
        assert errors == [], f"Validation errors: {errors}"


class TestGlossaryIntakeBridgeDeduplication:
    def test_terms_deduplicated_by_normalized_term(self):
        dup_terms = _make_terms() + [
            _GlossaryTerm(
                term_id="glossary-dup",
                term="velamen",
                normalized_term="velamen",
                mentions=[_SourceSpan()],
                provenance=_Provenance(confidence=0.5),
            )
        ]
        batch = stage_glossary_terms_for_intake(dup_terms, source_hash=_SOURCE_HASH)
        terms = [r.normalized_term for r in batch.records]
        assert len(terms) == len(set(terms)), "Duplicate normalized terms found"

    def test_highest_confidence_wins_on_dedup(self):
        terms = [
            _GlossaryTerm(
                term_id="glossary-low",
                term="sepal",
                normalized_term="sepal",
                mentions=[],
                provenance=_Provenance(confidence=0.5),
            ),
            _GlossaryTerm(
                term_id="glossary-high",
                term="sepal",
                normalized_term="sepal",
                mentions=[_SourceSpan()],
                provenance=_Provenance(confidence=0.9),
            ),
        ]
        batch = stage_glossary_terms_for_intake(terms, source_hash=_SOURCE_HASH)
        sepal_rec = next(r for r in batch.records if r.normalized_term == "sepal")
        assert sepal_rec.confidence == 0.9

    def test_mention_count_merged_on_dedup(self):
        terms = [
            _GlossaryTerm(
                term_id="g1",
                term="sepal",
                normalized_term="sepal",
                mentions=[_SourceSpan(), _SourceSpan()],
                provenance=_Provenance(confidence=0.8),
            ),
            _GlossaryTerm(
                term_id="g2",
                term="sepal",
                normalized_term="sepal",
                mentions=[_SourceSpan()],
                provenance=_Provenance(confidence=0.6),
            ),
        ]
        batch = stage_glossary_terms_for_intake(terms, source_hash=_SOURCE_HASH)
        sepal = next(r for r in batch.records if r.normalized_term == "sepal")
        assert sepal.mention_count == 3


class TestGlossaryIntakeBridgeProvenance:
    def test_source_hash_in_provenance_chain(self):
        batch = stage_glossary_terms_for_intake(_make_terms(), source_hash=_SOURCE_HASH)
        for rec in batch.records:
            chain_str = " ".join(rec.provenance_chain)
            assert _SOURCE_HASH[:16] in chain_str

    def test_extractor_in_provenance_chain(self):
        batch = stage_glossary_terms_for_intake(_make_terms(), source_hash=_SOURCE_HASH)
        for rec in batch.records:
            chain_str = " ".join(rec.provenance_chain)
            assert "glossary" in chain_str

    def test_batch_schema_version(self):
        batch = stage_glossary_terms_for_intake(_make_terms(), source_hash=_SOURCE_HASH)
        assert batch.schema_version == BRIDGE_SCHEMA_VERSION

    def test_batch_serializable_as_json(self):
        batch = stage_glossary_terms_for_intake(_make_terms(), source_hash=_SOURCE_HASH)
        output = batch.serialize_as_json()
        parsed = json.loads(output)
        assert parsed["schema_version"] == BRIDGE_SCHEMA_VERSION
        assert parsed["graph_mutation"] is False
        assert parsed["record_count"] == len(batch.records)


class TestGlossaryIntakeBridgeValidation:
    def test_invalid_status_raises(self):
        rec = GlossaryIntakeStagingRecord(
            term_id="t1", term="velamen", normalized_term="velamen",
            status="approved",  # wrong
            confidence=0.8, source_hash=_SOURCE_HASH, extractor="glossary",
            extractor_version="0.1.0", mention_count=1,
            concept_intake_state="PENDING_REVIEW", review_required=True,
            auto_promotion_blocked=True, provenance_chain=(),
        )
        with pytest.raises(ValueError, match="CANDIDATE"):
            rec.validate()

    def test_invalid_concept_intake_state_raises(self):
        rec = GlossaryIntakeStagingRecord(
            term_id="t1", term="velamen", normalized_term="velamen",
            status="candidate", confidence=0.8, source_hash=_SOURCE_HASH,
            extractor="glossary", extractor_version="0.1.0", mention_count=1,
            concept_intake_state="APPROVED",  # wrong
            review_required=True, auto_promotion_blocked=True, provenance_chain=(),
        )
        with pytest.raises(ValueError, match="PENDING_REVIEW"):
            rec.validate()

    def test_auto_promotion_false_raises(self):
        rec = GlossaryIntakeStagingRecord(
            term_id="t1", term="velamen", normalized_term="velamen",
            status="candidate", confidence=0.8, source_hash=_SOURCE_HASH,
            extractor="glossary", extractor_version="0.1.0", mention_count=1,
            concept_intake_state="PENDING_REVIEW", review_required=True,
            auto_promotion_blocked=False,  # wrong
            provenance_chain=(),
        )
        with pytest.raises(ValueError, match="AUTO_PROMOTION"):
            rec.validate()

    def test_empty_input_gives_empty_batch(self):
        batch = stage_glossary_terms_for_intake([], source_hash=_SOURCE_HASH)
        assert batch.records == []
        assert batch.validate_all() == []

    def test_term_without_normalized_term_skipped(self):
        terms = [
            _GlossaryTerm(
                term_id="skip", term="", normalized_term="",
                mentions=[], provenance=_Provenance(confidence=0.5),
            )
        ]
        batch = stage_glossary_terms_for_intake(terms, source_hash=_SOURCE_HASH)
        assert batch.records == []


# ===========================================================================
# OC-COMPLETE-007-matrix-vision-canonical-path
# ===========================================================================


class TestMatrixVisionEntryGuard:
    def test_valid_image_passes_guard(self):
        guard_vision_analysis_entry(_VALID_IMAGE)  # must not raise

    def test_missing_license_code_raises(self):
        import dataclasses
        bad = dataclasses.replace(_VALID_IMAGE, license_code="")
        # validate() raises PermissionError("LICENSE_AND_ATTRIBUTION_REQUIRED")
        with pytest.raises(PermissionError, match="LICENSE"):
            guard_vision_analysis_entry(bad)

    def test_missing_attribution_raises(self):
        import dataclasses
        bad = dataclasses.replace(_VALID_IMAGE, attribution="")
        # validate() raises PermissionError("LICENSE_AND_ATTRIBUTION_REQUIRED")
        with pytest.raises(PermissionError, match="ATTRIBUTION"):
            guard_vision_analysis_entry(bad)

    def test_over_confident_observation_raises(self):
        import dataclasses
        bad_obs = CharacterObservation(
            character_id="chr:labellum_color",
            state="pink",
            confidence=0.99,  # > 0.98 hard cap
            provenance=("fixture",),
        )
        bad_image = dataclasses.replace(_VALID_IMAGE, character_observations=(bad_obs,))
        # validate() raises ValueError("UNSUPPORTED_VISION_CONFIDENCE")
        with pytest.raises(ValueError, match="VISION_CONFIDENCE"):
            guard_vision_analysis_entry(bad_image)


class TestBatchPath:
    def test_batch_path_returns_character_observations(self):
        observations = batch_path(_VALID_IMAGE)
        assert isinstance(observations, tuple)
        assert len(observations) > 0

    def test_batch_path_observation_has_provenance_chain(self):
        observations = batch_path(_VALID_IMAGE)
        for obs in observations:
            provenance_str = " ".join(obs.provenance)
            assert "image:" in provenance_str
            assert "model:" in provenance_str
            assert "inference:" in provenance_str

    def test_batch_path_confidence_capped_at_0_95(self):
        observations = batch_path(_VALID_IMAGE)
        for obs in observations:
            assert obs.confidence <= 0.95

    def test_batch_path_observation_character_ids_preserved(self):
        observations = batch_path(_VALID_IMAGE)
        char_ids = {obs.character_id for obs in observations}
        assert "chr:labellum_color" in char_ids

    def test_batch_path_machine_generated_no_auto_promotion(self):
        """Observations carry provenance chain but no 'approved' marker."""
        observations = batch_path(_VALID_IMAGE)
        for obs in observations:
            chain_str = " ".join(obs.provenance)
            assert "approved" not in chain_str.lower()
            assert "auto_promoted" not in chain_str.lower()


class TestCanonicalPathDescription:
    def test_schema_version(self):
        desc = describe_canonical_path()
        assert desc["schema_version"] == PATH_SCHEMA_VERSION

    def test_both_modes_documented(self):
        desc = describe_canonical_path()
        assert "interactive" in desc["modes"]
        assert "batch" in desc["modes"]

    def test_interactive_mode_is_review_gated(self):
        desc = describe_canonical_path()
        assert desc["modes"]["interactive"]["review_gated"] is True
        assert desc["modes"]["interactive"]["machine_generated_until_review"] is True

    def test_batch_mode_entry_is_documented(self):
        desc = describe_canonical_path()
        batch_mode = desc["modes"]["batch"]
        assert "matrix_observations_from_vision" in batch_mode["entry"]

    def test_invariants_all_present(self):
        desc = describe_canonical_path()
        inv = desc["invariants"]
        assert inv["auto_promotion"] is False
        assert inv["cannot_determine_preserved"] is True
        assert inv["license_required"] is True
        assert inv["attribution_required"] is True
        assert inv["confidence_cap"] == 0.95

    def test_description_serializable_as_json(self):
        desc = describe_canonical_path()
        output = json.dumps(desc)
        parsed = json.loads(output)
        assert parsed["schema_version"] == PATH_SCHEMA_VERSION

    def test_canonical_path_description_constant_consistent(self):
        """describe_canonical_path() must return CANONICAL_PATH_DESCRIPTION."""
        assert describe_canonical_path() is CANONICAL_PATH_DESCRIPTION
