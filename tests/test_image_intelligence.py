"""Scientific validation tests for IMAGE-INTEL-001 image intelligence.

Covers taxonomic identifier consistency, duplicate detection, metadata and
license preservation, character provenance, specimen-level split
separation, identification uncertainty, conflicting character evidence,
unknown / out-of-distribution taxa, and cross-module API compatibility.
All fixtures are synthetic; no network or database is used.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.image_intelligence import router
from runtime.image_characters import (
    DescriptionCharacterState,
    ImageCharacterObservation,
    compare_observation,
    consolidate_description_states,
    observations_from_vision_bundle,
)
from runtime.image_evidence_graph import (
    character_links,
    depicts_links,
    hypothesis_links,
)
from runtime.image_inventory import (
    AcceptedTaxon,
    ImageInventoryRepository,
    compute_coverage,
)
from runtime.image_training_partitions import (
    build_dataset_manifest,
    evaluate_predictions,
    verify_no_leakage,
)
from runtime.reference_identification import (
    CalibrationTable,
    QueryImage,
    identify,
)
from runtime.reference_images import (
    ReferenceImageRecord,
    TaxonConcept,
    TaxonomicRevision,
    VerificationEvent,
    apply_taxonomic_revision,
    apply_verification,
    group_duplicates,
    normalize_image_url,
    record_from_source_row,
)

TAXV = "wcvp-2026.1"
LIC = "cc-by"

TAXA = {
    "t1": AcceptedTaxon("t1", "Epidendrum radicans", "Epidendrum"),
    "t2": AcceptedTaxon("t2", "Epidendrum ibaguense", "Epidendrum"),
    "t3": AcceptedTaxon("t3", "Masdevallia veitchiana", "Masdevallia"),
    "t4": AcceptedTaxon("t4", "Dracula vampira", "Dracula"),
}


def ref(
    image_id: str,
    taxon: str,
    *,
    status: str = "expert_verified",
    specimen: str | None = None,
    **kw,
) -> ReferenceImageRecord:
    base = {
        "image_id": image_id,
        "source": "gbif",
        "source_record_id": f"occ-{image_id}",
        "verbatim_name": TAXA[taxon].scientific_name if taxon in TAXA else taxon,
        "original_identification": TAXA[taxon].scientific_name
        if taxon in TAXA
        else taxon,
        "accepted_taxon_id": taxon,
        "accepted_name": TAXA[taxon].scientific_name if taxon in TAXA else taxon,
        "taxonomic_authority": "WCVP",
        "taxonomy_version": TAXV,
        "specimen_id": specimen or f"spec-{image_id}",
        "verification_status": status,
        "verifier": "Dr. Expert" if status == "expert_verified" else None,
        "image_url": f"https://img.example.org/{image_id}/original.jpg",
        "license": LIC,
        "organ": "whole_flower",
        "viewpoint": "frontal",
        "quality": "high",
    }
    base.update(kw)
    return ReferenceImageRecord(**base)


def desc(
    taxon: str,
    character: str,
    states=(),
    rng=None,
    *,
    cite="Dressler 1993",
    certainty="certain",
    kind="monograph",
):
    return DescriptionCharacterState(
        taxon_id=taxon,
        character_id=character,
        states=tuple(states),
        numeric_range=rng,
        source_kind=kind,
        citation=cite,
        verbatim_text=f"{character}: {states or rng}",
        certainty=certainty,
    )


DESCRIPTIONS = consolidate_description_states(
    [
        desc("t1", "flower_color", ["orange", "red"]),
        desc("t1", "labellum_shape", ["trilobed"]),
        desc("t1", "labellum_margin", ["fimbriate"]),
        desc("t2", "flower_color", ["orange", "red", "yellow"]),
        desc("t2", "labellum_shape", ["trilobed"]),
        desc("t2", "labellum_margin", ["entire"]),
        desc("t3", "flower_color", ["orange"]),
        desc("t3", "labellum_shape", ["entire"]),
        desc("t3", "sepal_tails", ["present"]),
        desc("t4", "flower_color", ["purple", "white"]),
        desc("t4", "labellum_shape", ["saccate"]),
    ]
)


def obs(
    character: str, state, *, mode="observed", conf=0.9, image="q1"
) -> ImageCharacterObservation:
    return ImageCharacterObservation(
        observation_id=f"{image}:{character}",
        image_id=image,
        character_id=character,
        evidence_mode=mode,
        state=state if mode in {"observed", "inferred"} else None,
        measurement_basis="categorical" if mode in {"observed", "inferred"} else "none",
        confidence=conf,
        method="vision_ai.heuristic",
        model_version="vision-ai-0.1",
    )


# -- taxonomic identifier consistency & verification ------------------------


def test_source_identification_is_not_ground_truth() -> None:
    lookup = {"2849": TaxonConcept("t1", "Epidendrum radicans", "WCVP", TAXV)}
    gbif = record_from_source_row(
        {
            "gbifID": "99",
            "taxonKey": "2849",
            "scientificName": "Epidendrum radicans Pav. ex Lindl.",
            "identifier": "https://x.org/a.jpg",
            "license": LIC,
            "basisOfRecord": "HUMAN_OBSERVATION",
        },
        source="gbif",
        taxon_lookup=lookup,
    )
    inat = record_from_source_row(
        {
            "id": "5",
            "scientific_name": "Epidendrum radicans",
            "url": "https://y.org/b.jpg",
            "license": LIC,
            "quality_grade": "research",
        },
        source="inaturalist",
        taxon_lookup={"Epidendrum radicans": lookup["2849"]},
    )
    assert gbif.accepted_taxon_id == "t1" and gbif.taxonomy_version == TAXV
    assert gbif.verification_status == "unverified_source_identification"
    assert inat.verification_status == "community_consensus"
    assert gbif.verbatim_name == "Epidendrum radicans Pav. ex Lindl."
    for rec in (gbif, inat):
        eligible, reasons = rec.training_label_eligibility()
        assert not eligible and "identification_not_expert_verified" in reasons


def test_unresolved_name_is_not_fuzzy_matched() -> None:
    lookup = {
        "Epidendrum radicans": TaxonConcept("t1", "Epidendrum radicans", "WCVP", TAXV)
    }
    rec = record_from_source_row(
        {"id": "1", "scientificName": "Epidendrum radican", "url": "https://z/1.jpg"},
        source="gbif",
        taxon_lookup=lookup,
    )
    assert rec.accepted_taxon_id is None
    assert rec.provenance["taxon_resolution"] == "unresolved"


def test_expert_verification_and_revision_preserve_original_identification() -> None:
    rec = ref("a", "t1", status="unverified_source_identification")
    revised = apply_verification(
        rec,
        VerificationEvent(
            "revise",
            "Dr. Hágsater",
            "2026-09-01",
            revised_taxon_id="t2",
            revised_name="Epidendrum ibaguense",
        ),
    )
    assert revised.verification_status == "expert_verified"
    assert revised.accepted_taxon_id == "t2"
    assert revised.verbatim_name == rec.verbatim_name
    assert revised.original_identification == rec.original_identification
    assert len(revised.verification_history) == 1
    community = apply_verification(
        rec, VerificationEvent("confirm", "inat-user", expert=False)
    )
    assert community.verification_status == "community_consensus"
    with pytest.raises(ValueError):
        apply_verification(rec, VerificationEvent("revise", "Dr. X"))


def test_taxonomic_split_requires_reverification_but_synonymy_does_not() -> None:
    recs = [ref("a", "t1"), ref("b", "t2")]
    syn = apply_taxonomic_revision(
        recs,
        TaxonomicRevision(
            "t1", ("t9",), ("Epidendrum novum",), "wcvp-2027.1", "synonymy"
        ),
    )
    assert (
        syn[0].accepted_taxon_id == "t9"
        and syn[0].verification_status == "expert_verified"
    )
    assert syn[0].provenance["taxonomic_revisions"][0]["from_version"] == TAXV
    assert syn[1] == recs[1]
    split = apply_taxonomic_revision(
        recs, TaxonomicRevision("t1", ("t9", "t10"), (), "wcvp-2027.1", "split")
    )
    assert split[0].accepted_taxon_id is None
    assert split[0].verification_status == "needs_reverification"
    assert split[0].verbatim_name == recs[0].verbatim_name


def test_validation_flags_inconsistent_identifiers() -> None:
    bad = replace(
        ref("a", "t1"), taxonomic_authority=None, verifier=None, has_scale=True
    )
    issues = bad.validate()
    assert "accepted_taxon_without_authority_version" in issues
    assert "expert_verification_without_verifier" in issues
    assert "scale_claimed_without_basis" in issues


# -- duplicates and license preservation -------------------------------------


def test_duplicate_detection_by_url_variant_hash_and_phash() -> None:
    a = ref("a", "t1", image_url="https://static.inat.org/photos/1/original.jpg")
    b = ref("b", "t1", image_url="http://STATIC.inat.org/photos/1/medium.jpg?x=1")
    c = ref("c", "t1", image_url="https://other.org/c.jpg", content_sha256="ABC")
    d = ref("d", "t1", image_url="https://other.org/d.jpg", content_sha256="abc")
    e = ref(
        "e", "t1", image_url="https://p.org/e.jpg", perceptual_hash="ffffffffffffffff"
    )
    f = ref(
        "f", "t1", image_url="https://p.org/f.jpg", perceptual_hash="fffffffffffffff0"
    )
    g = ref(
        "g", "t1", image_url="https://p.org/g.jpg", perceptual_hash="0000000000000000"
    )
    out = {r.image_id: r for r in group_duplicates([a, b, c, d, e, f, g])}
    assert normalize_image_url(a.image_url) == normalize_image_url(b.image_url)
    assert out["a"].duplicate_group_id == out["b"].duplicate_group_id is not None
    assert out["c"].duplicate_group_id == out["d"].duplicate_group_id is not None
    assert out["e"].duplicate_group_id == out["f"].duplicate_group_id is not None
    assert out["g"].duplicate_group_id is None
    assert out["a"].related_image_ids == ("b",)


def test_license_and_attribution_preserved_and_enforced() -> None:
    rec = ref(
        "a",
        "t1",
        license="cc-by-nc",
        rights_holder="Jane Doe",
        attribution="(c) Jane Doe",
    )
    payload = rec.as_dict()
    assert payload["license"] == "cc-by-nc" and payload["rights_holder"] == "Jane Doe"
    assert payload["training_label_eligible"]
    restricted = replace(rec, license="all rights reserved")
    ok, reasons = restricted.training_label_eligibility()
    assert not ok and "license_not_allowed" in reasons
    manifest = build_dataset_manifest(
        [
            rec,
            replace(
                restricted, image_id="r", image_url="https://r/1.jpg", specimen_id="s9"
            ),
        ],
        taxonomy_version=TAXV,
    )
    assert {e["image_id"] for e in manifest["entries"]} == {"a"}
    assert manifest["entries"][0]["license"] == "cc-by-nc"
    assert manifest["excluded"]["license_not_allowed"] == 1


# -- character provenance and conflicting evidence --------------------------


def test_vision_bundle_adapter_withholds_uncalibrated_measurements() -> None:
    bundle = {
        "analysis_id": "an-1",
        "image_asset": {"image_id": "q1"},
        "calibration": {"state": "UNCALIBRATED"},
        "provenance": {"engine_version": "vision-ai-0.1"},
        "character_observations": [
            {
                "observation_id": "o1",
                "character_id": "labellum_length_mm",
                "numeric_value": 12.0,
                "unit": "mm",
                "measurement_basis": "PIXEL",
                "evidence_kind": "MEASURED",
                "confidence": 0.8,
                "method": "morphometrics",
                "limitations": [],
            },
            {
                "observation_id": "o2",
                "character_id": "flower_symmetry_pattern",
                "character_state_id": "zygomorphic",
                "measurement_basis": "CATEGORICAL",
                "evidence_kind": "OBSERVED",
                "confidence": 0.7,
                "method": "segmentation",
                "limitations": [],
            },
            {
                "observation_id": "o3",
                "character_id": "column_wings",
                "measurement_basis": "CANNOT_DETERMINE",
                "evidence_kind": "OBSERVED",
                "confidence": 0.0,
                "method": "segmentation",
                "limitations": ["OCCLUDED"],
            },
            {
                "observation_id": "o4",
                "character_id": "mystery_metric",
                "relative_value": 0.4,
                "measurement_basis": "RELATIVE",
            },
        ],
    }
    lexicon = {
        "labellum length mm": "labellum_length",
        "flower symmetry pattern": "floral_symmetry",
        "column wings": "column_wings",
    }
    observations, unmapped = observations_from_vision_bundle(bundle, lexicon=lexicon)
    by = {o.character_id: o for o in observations}
    assert by["labellum_length"].evidence_mode == "cannot_determine"
    assert by["labellum_length"].state is None
    assert (
        "UNCALIBRATED_ABSOLUTE_MEASUREMENT_WITHHELD"
        in by["labellum_length"].limitations
    )
    assert (
        by["floral_symmetry"].state == "zygomorphic"
        and by["floral_symmetry"].evidence_mode == "observed"
    )
    assert by["floral_symmetry"].model_version == "vision-ai-0.1"
    assert by["floral_symmetry"].provenance["analysis_id"] == "an-1"
    assert by["column_wings"].evidence_mode == "cannot_determine"
    assert unmapped == [
        {
            "vision_character": "mystery_metric",
            "observation_id": "o4",
            "reason": "no_lexicon_mapping",
        }
    ]
    calibrated, _ = observations_from_vision_bundle(
        {**bundle, "calibration": {"state": "CALIBRATED"}}, lexicon=lexicon
    )
    assert (
        next(o for o in calibrated if o.character_id == "labellum_length").state == 12.0
    )
    for o in observations:
        assert o.validate() == []


def test_not_visible_never_contradicts_and_conflicts_are_preserved() -> None:
    hidden = obs("labellum_margin", None, mode="not_visible")
    result = compare_observation(hidden, DESCRIPTIONS["t1"]["labellum_margin"])
    assert result["outcome"] == "not_comparable"
    silent = compare_observation(
        obs("sepal_tails", "present"), DESCRIPTIONS["t1"].get("sepal_tails")
    )
    assert silent["reason"] == "description_silent"

    conflicting = consolidate_description_states(
        [
            desc("t5", "labellum_color", ["white"], cite="Garay 1958"),
            desc("t5", "labellum_color", ["yellow"], cite="Dodson 2004"),
            desc("t5", "petal_length", rng=(10, 12), cite="Garay 1958"),
            desc("t5", "petal_length", rng=(14, 16), cite="Dodson 2004"),
        ]
    )["t5"]
    assert conflicting["labellum_color"]["conflict"] is True
    assert conflicting["labellum_color"]["states"] == ["white", "yellow"]
    assert {s["citation"] for s in conflicting["labellum_color"]["sources"]} == {
        "Garay 1958",
        "Dodson 2004",
    }
    assert conflicting["labellum_color"]["certainty"] == "uncertain"
    assert (
        conflicting["petal_length"]["numeric_range"] == [10, 16]
        and conflicting["petal_length"]["conflict"]
    )
    agree = compare_observation(
        obs("labellum_color", "yellow"), conflicting["labellum_color"]
    )
    assert agree["outcome"] == "agree" and agree["description_conflict"] is True


# -- identification workflow -------------------------------------------------


REFS = [
    ref("r1", "t1", specimen="s1"),
    ref("r2", "t1", specimen="s1"),
    ref("r3", "t2", specimen="s2"),
    ref("r4", "t3", specimen="s3"),
    ref("r5", "t4", specimen="s4", status="unverified_source_identification"),
]
EMB = {
    "r1": [1.0, 0.1, 0.0],
    "r2": [0.95, 0.15, 0.0],
    "r3": [0.8, 0.3, 0.1],
    "r4": [0.1, 1.0, 0.0],
    "r5": [0.0, 0.0, 1.0],
}


def test_species_hypothesis_is_evidence_linked_and_provisional() -> None:
    query = QueryImage(
        "q1",
        observations=[
            obs("flower_color", "orange"),
            obs("labellum_shape", "trilobed"),
            obs("labellum_margin", "fimbriate"),
        ],
        embedding=[1.0, 0.12, 0.0],
        organ="whole_flower",
        viewpoint="frontal",
    )
    result = identify(
        query,
        taxa=TAXA,
        descriptions=DESCRIPTIONS,
        references=REFS,
        reference_embeddings=EMB,
        candidate_taxon_ids=["t1", "t2", "t3"],
    )
    top = result["hypotheses"][0]
    assert top["taxon_id"] == "t1"
    assert result["decision"] == "species_hypothesis"
    assert {a["character_id"] for a in top["agreements"]} == {
        "flower_color",
        "labellum_shape",
        "labellum_margin",
    }
    assert all(a["citations"] == ["Dressler 1993"] for a in top["agreements"])
    assert [r["image_id"] for r in top["reference_images"]] == [
        "r1"
    ]  # one hit per specimen
    t2 = next(h for h in result["hypotheses"] if h["taxon_id"] == "t2")
    assert [c["character_id"] for c in t2["contradictions"]] == ["labellum_margin"]
    assert result["genus_hypotheses"][0]["genus"] == "Epidendrum"
    assert result["governance"] == {
        "provisional": True,
        "authoritative": False,
        "training_label_eligible": False,
        "requires_expert_review": True,
        "canonical_taxonomy_mutation": False,
        "knowledge_graph_mutation": False,
    }
    assert (
        result["confidence"]["calibrated"] is False
        and result["confidence"]["top_species_probability"] is None
    )


def test_unverified_reference_images_are_excluded_from_retrieval() -> None:
    query = QueryImage("q2", embedding=[0.0, 0.0, 1.0])
    result = identify(
        query,
        taxa=TAXA,
        descriptions=DESCRIPTIONS,
        references=REFS,
        reference_embeddings=EMB,
    )
    assert all(
        h["taxon_id"] != "t4" or not h["reference_images"] for h in result["hypotheses"]
    )


def test_visual_similarity_alone_is_not_an_identification() -> None:
    query = QueryImage("q3", embedding=[1.0, 0.1, 0.0])
    result = identify(
        query,
        taxa=TAXA,
        descriptions=DESCRIPTIONS,
        references=REFS,
        reference_embeddings=EMB,
    )
    assert result["decision"] in {"abstain", "possible_unrepresented_taxon"}
    assert result["hypotheses"][0]["evidence_basis"] == "visual_similarity_only"
    assert result["hypotheses"][0]["evidence_score"] <= 0.35
    assert any(
        r["reason"] == "no_diagnostic_floral_view"
        for r in result["additional_evidence_requests"]
    )


def test_ambiguous_evidence_yields_genus_and_requests_discriminating_photo() -> None:
    # Color and lip shape fit both Epidendrum species; the margin separating
    # them was not visible, so the workflow must not pick a species.
    query = QueryImage(
        "q4",
        observations=[
            obs("flower_color", "orange"),
            obs("labellum_shape", "trilobed"),
            obs("labellum_margin", None, mode="not_visible"),
        ],
        organ="whole_flower",
        viewpoint="frontal",
    )
    result = identify(
        query,
        taxa=TAXA,
        descriptions=DESCRIPTIONS,
        candidate_taxon_ids=["t1", "t2", "t3"],
    )
    assert result["decision"] == "genus_hypothesis"
    assert result["genus_hypotheses"][0]["genus"] == "Epidendrum"
    requested = {r["character_id"]: r for r in result["additional_evidence_requests"]}
    assert requested["labellum_margin"]["reason"] == "separates_leading_candidates"
    assert "labellum" in requested["labellum_margin"]["request"].lower()


def test_out_of_distribution_taxon_is_flagged() -> None:
    query = QueryImage(
        "q5",
        observations=[obs("flower_color", "green"), obs("labellum_shape", "spurred")],
        embedding=[0.0, 0.05, 0.02],
        organ="whole_flower",
        viewpoint="frontal",
    )
    emb = {**EMB, "r5": [0.3, 0.3, 0.3]}
    result = identify(
        query,
        taxa=TAXA,
        descriptions=DESCRIPTIONS,
        references=REFS,
        reference_embeddings=emb,
        candidate_taxon_ids=["t1", "t2", "t3", "t4"],
    )
    assert result["decision"] == "possible_unrepresented_taxon"
    assert result["decision_level"] is None


def test_calibration_table_is_applied_only_when_supplied() -> None:
    query = QueryImage(
        "q6",
        observations=[
            obs("flower_color", "orange"),
            obs("labellum_shape", "trilobed"),
            obs("labellum_margin", "fimbriate"),
        ],
        organ="whole_flower",
        viewpoint="frontal",
    )
    table = CalibrationTable(bins=((0.5, 0.3), (1.0, 0.6)), evaluation_id="eval-1")
    result = identify(
        query,
        taxa=TAXA,
        descriptions=DESCRIPTIONS,
        candidate_taxon_ids=["t1", "t2"],
        calibration=table,
    )
    assert result["confidence"]["calibrated"] is True
    assert result["confidence"]["top_species_probability"] in {0.3, 0.6}


def test_graph_links_respect_verification_state() -> None:
    links = {
        l.source_record_id: l
        for l in depicts_links(
            [
                ref("v", "t1"),
                ref("u", "t2", status="unverified_source_identification"),
                ref("x", "t3", status="expert_rejected"),
            ]
        )
    }
    assert links["v"].validation_status == "verified"
    assert links["u"].validation_status == "provisional"
    assert links["x"].validation_status == "rejected"
    chars = character_links(
        [
            obs("flower_color", "orange"),
            obs("labellum_margin", None, mode="not_visible"),
        ]
    )
    assert [c.target_record_id for c in chars] == ["flower_color"] and chars[
        0
    ].validation_status == "provisional"
    query = QueryImage(
        "q7",
        observations=[obs("flower_color", "orange")],
        organ="whole_flower",
        viewpoint="frontal",
    )
    hyp = hypothesis_links(
        identify(
            query,
            taxa=TAXA,
            descriptions=DESCRIPTIONS,
            candidate_taxon_ids=["t1", "t3"],
        )
    )
    assert hyp and all(
        h.validation_status == "provisional"
        and h.provenance["training_label_eligible"] is False
        for h in hyp
    )


# -- training partitions and evaluation --------------------------------------


def _dataset() -> list[ReferenceImageRecord]:
    recs = []
    for taxon in ("t1", "t2", "t3"):
        for s in range(6):
            for k in range(2):  # two images per specimen
                recs.append(ref(f"{taxon}-{s}-{k}", taxon, specimen=f"{taxon}-spec{s}"))
    # Same photo reposted under a different occurrence of another specimen.
    recs.append(
        ref(
            "t1-dup",
            "t1",
            specimen="t1-specX",
            image_url="https://img.example.org/t1-0-0/medium.jpg",
        )
    )
    recs.append(ref("t4-0", "t4", specimen="t4-spec0"))
    recs.append(ref("t4-1", "t4", specimen="t4-spec1"))
    recs.append(ref("unv", "t1", status="community_consensus", specimen="u1"))
    recs.append(ref("oldtax", "t2", taxonomy_version="wcvp-2024.1", specimen="o1"))
    return recs


def test_manifest_keeps_specimens_and_duplicates_together() -> None:
    manifest = build_dataset_manifest(
        _dataset(), taxonomy_version=TAXV, open_set_taxon_ids=["t4"], seed="s1"
    )
    assert manifest["leakage_check"]["passed"], manifest["leakage_check"]
    split_of: dict[str, set[str]] = {}
    for e in manifest["entries"]:
        split_of.setdefault(e["group_key"], set()).add(e["split"])
    assert all(len(s) == 1 for s in split_of.values())
    ids = {e["image_id"]: e for e in manifest["entries"]}
    assert ids["t1-dup"]["split"] == ids["t1-0-0"]["split"] == ids["t1-0-1"]["split"]
    assert "unv" not in ids and "oldtax" not in ids
    assert manifest["excluded"]["identification_not_expert_verified"] == 1
    assert manifest["excluded"]["taxonomy_version_mismatch"] == 1
    assert {ids["t4-0"]["split"], ids["t4-1"]["split"]} == {"open_set_test"}
    assert manifest["taxa_per_split"]["test"] == 3
    assert manifest["trained_model"] is None


def test_manifest_is_deterministic_and_versioned() -> None:
    a = build_dataset_manifest(_dataset(), taxonomy_version=TAXV, seed="s1")
    b = build_dataset_manifest(
        list(reversed(_dataset())), taxonomy_version=TAXV, seed="s1"
    )
    c = build_dataset_manifest(_dataset()[:-3], taxonomy_version=TAXV, seed="s1")
    assert a["dataset_version"] == b["dataset_version"]
    assert a["dataset_version"] != c["dataset_version"]


def test_leakage_verifier_detects_tampering() -> None:
    manifest = build_dataset_manifest(_dataset(), taxonomy_version=TAXV, seed="s1")
    tampered = {**manifest, "entries": [dict(e) for e in manifest["entries"]]}
    first = tampered["entries"][0]
    sibling = next(
        e for e in tampered["entries"][1:] if e["group_key"] == first["group_key"]
    )
    sibling["split"] = "train" if first["split"] != "train" else "test"
    report = verify_no_leakage(tampered)
    assert not report["passed"]
    with pytest.raises(ValueError):
        evaluate_predictions(tampered, {}, genus_of={})


def test_reference_retrieval_baseline_evaluated_separately_by_genus_and_species() -> (
    None
):
    manifest = build_dataset_manifest(
        _dataset(), taxonomy_version=TAXV, seed="s1", open_set_taxon_ids=["t4"]
    )
    genus_of = {t: TAXA[t].genus for t in TAXA}
    centers = {
        "t1": [1.0, 0.0, 0.0],
        "t2": [0.9, 0.2, 0.0],
        "t3": [0.0, 1.0, 0.0],
        "t4": [0.0, 0.0, 1.0],
    }
    train = [e for e in manifest["entries"] if e["split"] == "train"]
    train_refs = [
        ref(e["image_id"], e["accepted_taxon_id"], specimen=e["group_key"])
        for e in train
    ]
    train_emb = {e["image_id"]: centers[e["accepted_taxon_id"]] for e in train}
    predictions = {}
    for e in manifest["entries"]:
        if e["split"] not in {"test", "open_set_test"}:
            continue
        result = identify(
            QueryImage(e["image_id"], embedding=centers[e["accepted_taxon_id"]]),
            taxa={k: v for k, v in TAXA.items() if k != "t4"},
            descriptions={},
            references=train_refs,
            reference_embeddings=train_emb,
        )
        predictions[e["image_id"]] = {
            "ranked_taxon_ids": [h["taxon_id"] for h in result["hypotheses"]],
            "confidence": result["confidence"]["top_species_probability_uncalibrated"],
            "abstained": result["decision"]
            in {"abstain", "possible_unrepresented_taxon"},
            "unrepresented_taxon": result["decision"] == "possible_unrepresented_taxon",
        }
    report = evaluate_predictions(manifest, predictions, genus_of=genus_of)
    assert report["species"]["evaluated"] == report["genus"]["evaluated"] > 0
    # Visual-only retrieval must abstain rather than claim identifications.
    assert report["species"]["abstention_rate"] == 1.0
    assert report["open_set"]["rate"] == 1.0
    assert "no model was trained" in report["notes"][0]

    # Forced (non-abstaining) predictions are scored per level.
    forced = {k: {**v, "abstained": False} for k, v in predictions.items()}
    forced_report = evaluate_predictions(manifest, forced, genus_of=genus_of)
    assert forced_report["species"]["top1_accuracy_answered"] == 1.0
    assert forced_report["genus"]["top1_accuracy_answered"] == 1.0
    assert forced_report["species"]["expected_calibration_error"] is not None


# -- coverage and inventory --------------------------------------------------


def test_coverage_and_gap_analysis() -> None:
    recs = [
        ref("a", "t1"),
        ref("b", "t1", organ="leaf", viewpoint="habit"),
        ref("c", "t2", status="unverified_source_identification"),
        ref(
            "d",
            "t3",
            record_kind="preserved_specimen",
            organ="herbarium_sheet",
            viewpoint="habit",
        ),
        ref("e", "t9"),
        replace(ref("f", "t1"), accepted_taxon_id=None),
    ]
    report = compute_coverage(
        recs,
        TAXA.values(),
        described_taxon_ids=["t1", "t2"],
        keyed_taxon_ids=["t1"],
        taxonomy_version=TAXV,
    )
    species = {s["taxon_id"]: s for s in report["species"]}
    assert (
        species["t1"]["verified_reference_images"] and species["t1"]["vegetative_views"]
    )
    assert (
        species["t1"]["multiple_images"] and not species["t1"]["insufficient_evidence"]
    )
    assert (
        not species["t2"]["verified_reference_images"]
        and species["t2"]["insufficient_evidence"]
    )
    assert (
        species["t3"]["herbarium_images"]
        and not species["t3"]["diagnostic_floral_views"]
    )
    assert species["t4"]["image_count"] == 0
    assert report["image_records"] == {
        "matched": 4,
        "unresolved_taxon": 1,
        "unmatched_taxon": 1,
        "taxonomy_version_mismatch": 0,
    }
    assert report["totals"]["insufficient_evidence"] == 3
    assert report["priority_gaps"][0]["taxon_id"] == "t4"
    genera = {g["genus"]: g for g in report["genera"]}
    assert (
        genera["Epidendrum"]["species_count"] == 2
        and genera["Epidendrum"]["verified_reference_images"] == 1
    )


def test_coverage_scales_to_full_orchid_family() -> None:
    taxa = [
        AcceptedTaxon(f"s{i}", f"Genus{i % 900} sp{i}", f"Genus{i % 900}")
        for i in range(30000)
    ]
    recs = [ref(f"i{i}", "t1", accepted_taxon_id=f"s{i}") for i in range(0, 30000, 3)]
    report = compute_coverage(recs, taxa, gap_limit=10)
    assert report["accepted_species"] == 30000
    assert report["totals"]["accessible_images"] == 10000
    assert len(report["genera"]) == 900 and len(report["priority_gaps"]) == 10


def test_inventory_repository_is_read_only_and_reports_unavailable() -> None:
    statements: list[str] = []
    columns = {
        ("public", "orchid_images"): [
            "id",
            "taxonomy_id",
            "image_url",
            "image_license",
            "gbif_occurrence_key",
            "image_source",
            "is_duplicate",
        ],
    }

    def execute(sql: str, params):
        statements.append(sql)
        if "information_schema" in sql:
            return [
                {"column_name": c}
                for c in columns.get((params["schema"], params["name"]), [])
            ]
        if "GROUP BY 1 ORDER BY 2" in sql:
            return [{"source": "gbif", "images": 7}]
        if "GROUP BY 1 ORDER BY 1" in sql:
            return [{"taxon_id": "1", "images": 3, "occurrences": 2, "licensed": 3}]
        return [
            {
                "total": 10,
                "with_url": 9,
                "with_taxon": 8,
                "with_license": 7,
                "with_occurrence": 6,
                "distinct_taxa": 4,
            }
        ]

    repo = ImageInventoryRepository(execute)
    report = repo.inventory()
    tables = {t["table"]: t for t in report["tables"]}
    assert tables["public.orchid_images"]["state"] == "available"
    assert tables["public.orchid_images"]["counts"]["distinct_taxa"] == 4
    assert tables["public.images"]["state"] == "unavailable"
    assert report["downloads_performed"] == 0
    assert repo.species_image_counts()["rows"][0]["occurrences"] == 2
    assert all(s.lstrip().upper().startswith("SELECT") for s in statements)


# -- API compatibility -------------------------------------------------------


@pytest.fixture()
def client(monkeypatch) -> TestClient:
    monkeypatch.setenv("CALYX_API_KEY", "test-key")
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, headers={"X-API-Key": "test-key"})


def _ref_payload(image_id: str, taxon: str, **kw):
    r = ref(image_id, taxon, **kw).as_dict()
    keep = {
        "image_id",
        "source",
        "source_record_id",
        "verbatim_name",
        "original_identification",
        "accepted_taxon_id",
        "accepted_name",
        "taxonomic_authority",
        "taxonomy_version",
        "record_kind",
        "specimen_id",
        "occurrence_id",
        "verification_status",
        "verifier",
        "verified_on",
        "image_url",
        "storage_ref",
        "license",
        "organ",
        "viewpoint",
        "quality",
    }
    return {k: v for k, v in r.items() if k in keep}


def test_api_requires_auth(monkeypatch) -> None:
    monkeypatch.setenv("CALYX_API_KEY", "test-key")
    app = FastAPI()
    app.include_router(router)
    assert TestClient(app).get("/api/image-intelligence/contract").status_code in {
        401,
        403,
    }


def test_api_contract_and_end_to_end(client: TestClient) -> None:
    contract = client.get("/api/image-intelligence/contract").json()
    assert contract["contract_version"] == "oc-image-intelligence-v1"
    assert contract["governance"]["knowledge_graph_mutation"] is False

    taxa = [
        {"taxon_id": k, "scientific_name": v.scientific_name, "genus": v.genus}
        for k, v in TAXA.items()
    ]
    validated = client.post(
        "/api/image-intelligence/references/validate",
        json={
            "records": [
                _ref_payload("a", "t1"),
                _ref_payload("b", "t2", status="unverified_source_identification"),
            ]
        },
    ).json()
    assert validated["training_label_eligible"] == 1
    assert {l["validation_status"] for l in validated["graph_links"]} == {
        "verified",
        "provisional",
    }

    verified = client.post(
        "/api/image-intelligence/references/verify",
        json={
            "record": _ref_payload(
                "b", "t2", status="unverified_source_identification"
            ),
            "event": {"decision": "confirm", "verifier": "Dr. X"},
        },
    ).json()
    assert (
        verified["record"]["verification_status"] == "expert_verified"
        and verified["persisted"] is False
    )

    cov = client.post(
        "/api/image-intelligence/coverage",
        json={"records": [_ref_payload("a", "t1")], "taxa": taxa},
    ).json()
    assert cov["accepted_species"] == 4 and "species" not in cov

    ident = client.post(
        "/api/image-intelligence/identify",
        json={
            "query_image_id": "q1",
            "observations": [
                {
                    "observation_id": "o1",
                    "image_id": "q1",
                    "character_id": "flower_color",
                    "evidence_mode": "observed",
                    "state": "orange",
                    "confidence": 0.9,
                    "method": "vision",
                },
                {
                    "observation_id": "o2",
                    "image_id": "q1",
                    "character_id": "labellum_margin",
                    "evidence_mode": "observed",
                    "state": "fimbriate",
                    "confidence": 0.9,
                    "method": "vision",
                },
            ],
            "query_organ": "whole_flower",
            "query_viewpoint": "frontal",
            "taxa": taxa,
            "description_states": [
                {
                    "taxon_id": "t1",
                    "character_id": "flower_color",
                    "states": ["orange"],
                    "citation": "Dressler 1993",
                },
                {
                    "taxon_id": "t1",
                    "character_id": "labellum_margin",
                    "states": ["fimbriate"],
                    "citation": "Dressler 1993",
                },
                {
                    "taxon_id": "t2",
                    "character_id": "labellum_margin",
                    "states": ["entire"],
                    "citation": "Hágsater 2001",
                },
            ],
            "candidate_taxon_ids": ["t1", "t2"],
            "include_graph_links": True,
        },
    ).json()
    assert ident["hypotheses"][0]["taxon_id"] == "t1"
    assert ident["governance"]["authoritative"] is False
    assert all(l["validation_status"] == "provisional" for l in ident["graph_links"])

    records = [
        _ref_payload(f"{t}-{s}", t, specimen=f"{t}-s{s}")
        for t in ("t1", "t2")
        for s in range(4)
    ]
    manifest = client.post(
        "/api/image-intelligence/datasets/manifest",
        json={"records": records, "taxonomy_version": TAXV},
    ).json()
    assert manifest["leakage_check"]["passed"]
    preds = {
        e["image_id"]: {"ranked_taxon_ids": [e["accepted_taxon_id"]], "confidence": 0.9}
        for e in manifest["entries"]
    }
    ev = client.post(
        "/api/image-intelligence/datasets/evaluate",
        json={
            "manifest": manifest,
            "predictions": preds,
            "genus_of": {"t1": "Epidendrum", "t2": "Epidendrum"},
        },
    ).json()
    assert (
        ev["species"]["top1_accuracy_answered"] == 1.0
        and ev["genus"]["top1_accuracy_answered"] == 1.0
    )


def test_router_is_mounted_in_application() -> None:
    from app.main import app

    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert "/api/image-intelligence/contract" in paths
    assert "/api/image-intelligence/identify" in paths
