"""Tests for deterministic taxon resolution and synonym reconciliation."""

from __future__ import annotations

from runtime.matrix_taxon_resolution import (
    StaticTaxonResolver,
    TaxonEntry,
    collapse_synonym_candidates,
    resolver_from_candidates,
)

ENTRIES = [
    TaxonEntry(
        canonical_taxon_id="world-plants:phragmipedium-kovachii",
        accepted_name="Phragmipedium kovachii",
        synonyms=("Phragmipedium peruvianum",),
    ),
    {
        "canonical_taxon_id": "world-plants:phragmipedium-besseae",
        "accepted_name": "Phragmipedium besseae",
        "synonyms": [],
    },
]


def test_canonical_name_resolves_directly() -> None:
    resolver = StaticTaxonResolver(ENTRIES)
    result = resolver.resolve("Phragmipedium kovachii")
    assert result.resolution_state == "resolved_canonical"
    assert result.canonical_taxon_id == "world-plants:phragmipedium-kovachii"
    assert result.accepted_name == "Phragmipedium kovachii"
    assert result.matched_via == "accepted_name"


def test_synonym_resolves_to_accepted_taxon_and_preserves_query() -> None:
    resolver = StaticTaxonResolver(ENTRIES)
    result = resolver.resolve("Phragmipedium peruvianum")
    assert result.resolution_state == "resolved_synonym"
    assert result.query_name == "Phragmipedium peruvianum"
    assert result.accepted_name == "Phragmipedium kovachii"
    assert result.canonical_taxon_id == "world-plants:phragmipedium-kovachii"
    assert result.matched_via == "synonym"
    assert "not a taxonomy mutation" in result.note


def test_near_miss_names_are_unresolved_never_fuzzy_matched() -> None:
    resolver = StaticTaxonResolver(ENTRIES)
    result = resolver.resolve("Phragmipedium kovachi")  # missing final i
    assert result.resolution_state == "unresolved"
    assert result.canonical_taxon_id is None
    empty = resolver.resolve("   ")
    assert empty.resolution_state == "unresolved"


def test_matching_is_case_and_whitespace_normalized() -> None:
    resolver = StaticTaxonResolver(ENTRIES)
    result = resolver.resolve("  phragmipedium   KOVACHII ")
    assert result.resolution_state == "resolved_canonical"


def test_first_entry_wins_deterministically_on_name_collisions() -> None:
    resolver = StaticTaxonResolver(
        [
            {"canonical_taxon_id": "a", "accepted_name": "Name X", "synonyms": []},
            {"canonical_taxon_id": "b", "accepted_name": "name x", "synonyms": []},
        ]
    )
    assert resolver.resolve("Name X").canonical_taxon_id == "a"


def test_governed_synonym_entries_take_precedence_over_candidate_names() -> None:
    candidates = [
        {
            "taxon_id": "world-plants:phragmipedium-kovachii",
            "scientific_name": "Phragmipedium kovachii",
        },
        {
            "taxon_id": "unreconciled:peruvianum-row",
            "scientific_name": "Phragmipedium peruvianum",
        },
    ]
    resolver = resolver_from_candidates(candidates, extra_entries=ENTRIES[:1])
    resolution = resolver.resolve("Phragmipedium peruvianum")
    assert resolution.resolution_state == "resolved_synonym"
    assert resolution.canonical_taxon_id == "world-plants:phragmipedium-kovachii"

    groups = collapse_synonym_candidates(
        [
            {"taxon_id": c["taxon_id"], "scientific_name": c["scientific_name"], "score": 1.0}
            for c in candidates
        ],
        resolver,
    )
    collapsed = [group for group in groups if group["collapsed"]]
    assert len(collapsed) == 1
    group = collapsed[0]
    assert group["canonical_taxon_id"] == "world-plants:phragmipedium-kovachii"
    assert group["accepted_name"] == "Phragmipedium kovachii"
    assert group["aliases"] == ["Phragmipedium peruvianum"]
    # Both ranked rows are preserved as members; nothing is deleted.
    assert {m["taxon_id"] for m in group["members"]} == {
        "world-plants:phragmipedium-kovachii",
        "unreconciled:peruvianum-row",
    }
