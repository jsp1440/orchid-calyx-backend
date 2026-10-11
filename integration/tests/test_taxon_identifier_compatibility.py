"""Priority 4: cross-surface taxon/media identifier compatibility.

Verifies, provider-free and with no database, that Matrix, Image Intelligence
(#1801), Atlas (#1802), Featured Genus (#1803) and the Brain OAO bridge (#233)
use compatible taxon identifiers and evidence references:

  1. Every identifier shape each surface actually emits classifies under
     exactly one declared scheme (`integration/taxon_identifiers.py`).
  2. Atlas and Featured Genus share the `public.orchid_taxonomy.id` backbone
     keyspace in string form — checked against the byte-verified Atlas
     `oc.atlas-module-capabilities.v1` identifier_systems declaration.
  3. The real Image Intelligence `record_from_source_row` (#1801 head
     938cc47f) preserves a caller-supplied `oc-image:*` media id verbatim,
     mints deterministic `img_<sha256[:20]>` ids otherwise, binds accepted
     taxa only through exact lookup (authority + version required), and
     leaves unmapped names unresolved.
  4. The real Matrix resolver emits `world-plants:*` canonical ids.
  5. The real Brain bridge fixtures use `gbif:genus:*` / `gbif:species:*`.
  6. Cross-namespace correlation is bound by accepted name with provenance;
     identifiers are never rewritten and malformed bindings are refused.

Upstream trees are byte-verified checkouts; tests skip when a root is absent.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
CALYX_ROOT = Path(os.environ.get("OC_CALYX_ROOT", HERE.parents[2]))
BRAIN_ROOT = Path(os.environ.get("OC_BRAIN_ROOT", CALYX_ROOT.parent / "brain"))
II_ROOT = Path(os.environ.get("OC_IMAGE_INTEL_ROOT", CALYX_ROOT.parent / "calyx-1801"))

# Byte-verified copy of the Atlas #1802 `oc.atlas-module-capabilities.v1`
# contract (upstream blob cc5dbffd15c4efe5b6e9ef3efb0803a4512b77fa, head
# 0b2a3b47), vendored so this suite is self-contained in the convergence PR.
UPSTREAM_ROOT = Path(
    os.environ.get("OC_UPSTREAM_ROOT", HERE.parents[1] / "contracts")
)

for path in (str(CALYX_ROOT), str(BRAIN_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from integration.taxon_identifiers import (  # noqa: E402
    GENUS_NAME_MAX_LENGTH,
    build_correlation,
    classify_identifier,
    correlation_lookup_key,
    is_valid_genus_name,
)

ii_missing = pytest.mark.skipif(
    not (II_ROOT / "runtime" / "reference_images.py").is_file(),
    reason="Calyx #1801 tree not available (set OC_IMAGE_INTEL_ROOT)",
)
brain_missing = pytest.mark.skipif(
    not (BRAIN_ROOT / "fixtures" / "oao_bridge" / "representative_orchid_evidence.json").is_file(),
    reason="Brain bridge fixtures not available (set OC_BRAIN_ROOT)",
)
atlas_contract_missing = pytest.mark.skipif(
    not (UPSTREAM_ROOT / "atlas_module_capabilities_v1.json").is_file(),
    reason="Atlas capabilities contract not available",
)


def _extend_runtime_path() -> None:
    """Make `runtime.reference_images` / `runtime.image_staging` resolvable
    from the #1801 tree when `runtime` already came from the Matrix chain
    tree. Standard pkgutil-style __path__ extension; the trees contribute
    disjoint submodules, so no module identity is shadowed."""
    if not (II_ROOT / "runtime" / "reference_images.py").is_file():
        return
    try:
        import runtime
    except ImportError:
        return
    ii_runtime = str(II_ROOT / "runtime")
    if ii_runtime not in list(runtime.__path__):
        runtime.__path__.append(ii_runtime)


_extend_runtime_path()


# -- 1. scheme classification ---------------------------------------------------


class TestSchemeClassification:
    def test_world_plants_taxon_ids(self):
        cls = classify_identifier("world-plants:cattleya-labiata")
        assert cls is not None
        assert cls.scheme == "world-plants"
        assert cls.kind == "taxon"
        assert cls.owning_surfaces == ("matrix",)

    def test_gbif_fixture_taxon_ids(self):
        genus = classify_identifier("gbif:genus:Cattleya")
        species = classify_identifier("gbif:species:Angraecum-sesquipedale")
        assert genus is not None and genus.scheme == "gbif" and genus.kind == "taxon"
        assert species is not None and species.scheme == "gbif" and species.kind == "taxon"

    def test_backbone_numeric_taxon_ids_shared_by_atlas_and_featured_genus(self):
        cls = classify_identifier("12345")
        assert cls is not None
        assert cls.scheme == "orchid-backbone"
        assert cls.kind == "taxon"
        assert set(cls.owning_surfaces) == {"atlas", "featured-genus"}

    def test_featured_genus_media_ids(self):
        cls = classify_identifier("oc-image:6789")
        assert cls is not None
        assert cls.scheme == "oc-image"
        assert cls.kind == "media"

    def test_image_intelligence_minted_ids(self):
        img = classify_identifier("img_" + "a" * 20)
        dup = classify_identifier("dupgrp_" + "b" * 16)
        assert img is not None and img.scheme == "image-intelligence" and img.kind == "media"
        assert dup is not None and dup.kind == "duplicate-group"

    def test_unclassifiable_shapes_stay_unclassifiable(self):
        for value in ("", None, 42, "Cattleya labiata", "world-plants:", "img_abc",
                      "oc-image:", "gbif:species:", "https://example.org/x"):
            assert classify_identifier(value) is None


# -- 2. Atlas x Featured Genus backbone agreement --------------------------------


@atlas_contract_missing
class TestAtlasFeaturedGenusBackbone:
    def _contract(self) -> dict:
        with (UPSTREAM_ROOT / "atlas_module_capabilities_v1.json").open(encoding="utf-8") as fh:
            return json.load(fh)

    def test_atlas_declares_backbone_taxon_id_in_string_form(self):
        contract = self._contract()
        declaration = contract["identifier_systems"]["taxon_id"]
        assert "public.orchid_taxonomy.id" in declaration
        assert "string form" in declaration

    def test_featured_genus_taxon_id_satisfies_atlas_declaration(self):
        # Featured Genus emits taxon_id = str(public.orchid_images.taxonomy_id),
        # which FK-resolves to public.orchid_taxonomy.id — the same backbone.
        contract = self._contract()
        assert "public.orchid_taxonomy.id" in contract["identifier_systems"]["taxon_id"]
        for backbone_id in (1, 42, 109195):
            emitted = str(backbone_id)  # featured-genus media item taxon_id form
            cls = classify_identifier(emitted)
            assert cls is not None and cls.scheme == "orchid-backbone"
            assert "atlas" in cls.owning_surfaces and "featured-genus" in cls.owning_surfaces

    def test_atlas_genus_rule_matches_shared_boundary(self):
        contract = self._contract()
        assert contract["identifier_systems"]["genus"] == (
            "Accepted Latin genus name, capitalised, single word."
        )
        for genus in ("Cattleya", "Paphiopedilum", "Dracula"):
            assert is_valid_genus_name(genus)
        for bad in ("cattleya", "Cattleya labiata", "", "X", "C" * (GENUS_NAME_MAX_LENGTH + 1)):
            assert not is_valid_genus_name(bad)


# -- 3. real Image Intelligence identifier behavior ------------------------------


@ii_missing
class TestImageIntelligenceIdentifiers:
    def _module(self):
        import runtime.reference_images as reference_images

        return reference_images

    def test_caller_supplied_oc_image_id_passes_through_verbatim(self):
        reference_images = self._module()
        record = reference_images.record_from_source_row(
            {
                "image_id": "oc-image:42",
                "source_record_id": "gbif-occ-1",
                "identifier": "https://example.org/img/42.jpg",
                "scientificName": "Cattleya labiata",
                "license": "CC-BY",
            },
            source="gbif",
        )
        assert record.image_id == "oc-image:42"
        cls = classify_identifier(record.image_id)
        assert cls is not None and cls.scheme == "oc-image"

    def test_minted_image_id_is_deterministic_img_sha20(self):
        reference_images = self._module()
        row = {
            "source_record_id": "gbif-occ-9",
            "identifier": "https://example.org/img/9.jpg",
            "scientificName": "Cattleya labiata",
            "license": "CC-BY",
        }
        first = reference_images.record_from_source_row(row, source="gbif")
        second = reference_images.record_from_source_row(dict(row), source="gbif")
        assert first.image_id == second.image_id
        cls = classify_identifier(first.image_id)
        assert cls is not None and cls.scheme == "image-intelligence" and cls.kind == "media"

    def test_accepted_taxon_binds_world_plants_ids_by_exact_lookup_only(self):
        reference_images = self._module()
        lookup = {
            "Cattleya labiata": reference_images.TaxonConcept(
                accepted_taxon_id="world-plants:cattleya-labiata",
                accepted_name="Cattleya labiata",
                authority="World Plants (Hassler)",
                source_version="2026-09",
            )
        }
        row = {
            "source_record_id": "gbif-occ-7",
            "identifier": "https://example.org/img/7.jpg",
            "scientificName": "Cattleya labiata",
            "license": "CC-BY",
        }
        bound = reference_images.record_from_source_row(row, source="gbif", taxon_lookup=lookup)
        assert bound.accepted_taxon_id == "world-plants:cattleya-labiata"
        cls = classify_identifier(bound.accepted_taxon_id)
        assert cls is not None and cls.scheme == "world-plants"
        assert bound.taxonomic_authority and bound.taxonomy_version

        # No fuzzy matching: a name variant that is not an exact key stays unresolved.
        variant = reference_images.record_from_source_row(
            {**row, "scientificName": "Cattleya  labiata "},
            source="gbif",
            taxon_lookup=lookup,
        )
        assert variant.accepted_taxon_id is None
        assert variant.provenance["taxon_resolution"] == "unresolved"

    def test_source_identification_never_becomes_ground_truth(self):
        reference_images = self._module()
        record = reference_images.record_from_source_row(
            {
                "source_record_id": "gbif-occ-11",
                "identifier": "https://example.org/img/11.jpg",
                "scientificName": "Cattleya labiata",
                "license": "CC-BY",
            },
            source="gbif",
        )
        assert record.verification_status == "unverified_source_identification"
        assert not record.expert_confirmed
        eligible, reasons = record.training_label_eligibility()
        assert not eligible
        assert "identification_not_expert_verified" in reasons


# -- 4. real Matrix resolver ids ---------------------------------------------------


class TestMatrixResolverIds:
    def test_matrix_resolver_emits_world_plants_scheme_ids(self):
        from runtime.matrix_taxon_resolution import StaticTaxonResolver, TaxonEntry

        resolver = StaticTaxonResolver(
            [
                TaxonEntry(
                    canonical_taxon_id="world-plants:cattleya-labiata",
                    accepted_name="Cattleya labiata",
                    synonyms=("Cattleya labiata var. autumnalis",),
                )
            ]
        )
        for query in ("Cattleya labiata", "Cattleya labiata var. autumnalis"):
            resolution = resolver.resolve(query)
            cls = classify_identifier(resolution.canonical_taxon_id)
            assert cls is not None and cls.scheme == "world-plants"

    def test_unresolved_names_yield_no_identifier(self):
        from runtime.matrix_taxon_resolution import StaticTaxonResolver

        resolver = StaticTaxonResolver([])
        resolution = resolver.resolve("Notarealgenus fakensis")
        assert resolution.resolution_state == "unresolved"
        assert resolution.canonical_taxon_id is None


# -- 5. Brain bridge fixture ids ---------------------------------------------------


@brain_missing
def test_brain_bridge_fixture_ids_classify_as_gbif_scheme():
    fixture_path = BRAIN_ROOT / "fixtures" / "oao_bridge" / "representative_orchid_evidence.json"
    with fixture_path.open(encoding="utf-8") as fh:
        fixture = json.load(fh)
    taxon_ids = {
        record["taxon_id"]
        for record in fixture["observations"]
        if record.get("taxon_id")
    }
    assert taxon_ids, "fixture carries no taxon ids"
    for taxon_id in taxon_ids:
        cls = classify_identifier(taxon_id)
        assert cls is not None, f"unclassifiable fixture taxon id: {taxon_id}"
        assert cls.scheme == "gbif"
        assert cls.kind == "taxon"


# -- 6. name-bound correlation, never id rewriting --------------------------------


class TestNameBoundCorrelation:
    def test_correlation_binds_native_ids_across_namespaces(self):
        correlation = build_correlation(
            "Cattleya labiata",
            {
                "world-plants": "world-plants:cattleya-labiata",
                "orchid-backbone": "4242",
                "gbif": "gbif:species:cattleya-labiata",
            },
            taxonomic_authority="World Plants (Hassler)",
            taxonomy_version="2026-09",
            provenance=("integration:priority4:identifier-compatibility",),
        )
        # Identifiers stored verbatim — nothing rewritten into another scheme.
        assert correlation.identifiers["world-plants"] == "world-plants:cattleya-labiata"
        assert correlation.identifiers["orchid-backbone"] == "4242"
        assert correlation_lookup_key(correlation) == "cattleya labiata"

    def test_correlation_refuses_malformed_or_mismatched_identifiers(self):
        with pytest.raises(ValueError):
            build_correlation("Cattleya labiata", {"world-plants": "4242"})
        with pytest.raises(ValueError):
            build_correlation("Cattleya labiata", {"unknown-scheme": "x:1"})
        with pytest.raises(ValueError):
            build_correlation("", {"world-plants": "world-plants:cattleya-labiata"})
        with pytest.raises(ValueError):
            build_correlation("Cattleya labiata", {"oc-image": "oc-image:42"})

    def test_correlation_is_a_name_join_not_an_id_alias(self):
        left = build_correlation(
            "Cattleya labiata", {"world-plants": "world-plants:cattleya-labiata"}
        )
        right = build_correlation("Cattleya labiata", {"orchid-backbone": "4242"})
        assert correlation_lookup_key(left) == correlation_lookup_key(right)
        # The join key is the normalised accepted name; the ids stay distinct.
        assert left.identifiers != right.identifiers
