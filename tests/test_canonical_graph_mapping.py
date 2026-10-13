import pytest

from runtime.knowledge_graph.canonical_graph_mapping import (
    AMBIGUOUS,
    AUTHORITY_ID_CONFLICT,
    GRAPH_DUPLICATE_LABEL,
    GRAPH_HAS_SEPARATE_NODE_FOR_SYNONYM,
    GRAPH_NODE_NOT_FOUND,
    NAME_NORMALIZATION_UNSAFE,
    PRO_PARTE_SYNONYM,
    REGISTRY_HOMONYM,
    SYNONYM_IS_ACCEPTED_NAME,
    SYNONYM_TARGET_NOT_LINKED,
    UNRESOLVED,
    build_taxon_graph_mapping,
    normalization_safe,
    strict_name_key,
)
from runtime.knowledge_graph.canonical_taxonomy import (
    MAP_ACCEPTED_NAME,
    MAP_EXACT_ID,
    build_canonical_registry,
)
from runtime.knowledge_graph.models import Node


def node(key, label, **payload):
    return {"canonical_key": key, "node_type": "taxon", "display_label": label, "payload": payload}


def syn(synonym, accepted):
    return {"input_match_name": synonym, "accepted_match_name": accepted, "relationship": "synonym"}


LOAD = [
    {"name": "Exemplaria aurea Fict.", "taxon_code": "S"},
    {"name": "Exemplaria rubra Fict.", "taxon_code": "S"},
]
GRAPH = [node("taxon:101", "Exemplaria aurea"), node("taxon:102", "Exemplaria rubra")]


def test_unique_exact_names_link_and_synonyms_follow_their_accepted_taxon():
    mapping = build_taxon_graph_mapping(LOAD, [syn("Fictorchis aurea", "Exemplaria aurea")], GRAPH)
    aurea = mapping.link_for_name("Exemplaria aurea Fict.")
    assert aurea.status == "accepted" and aurea.node_key == "taxon:101"
    assert aurea.mapping_class == MAP_ACCEPTED_NAME
    assert aurea.authority == "world_plants" and aurea.automatic_fuzzy_matching is False
    synonym = mapping.link_for_name("Fictorchis aurea")
    assert synonym.status == "synonym"
    assert synonym.node_key == "taxon:101"
    assert synonym.accepted_name == "Exemplaria aurea"


def test_runtime_node_objects_are_accepted_as_graph_input():
    nodes = [Node(101, "taxon", "taxon:101", "Exemplaria aurea"), Node(5, "genus", "genus:5", "Exemplaria")]
    assert build_taxon_graph_mapping(LOAD, (), nodes).node_key_for_name("Exemplaria aurea") == "taxon:101"


def test_missing_graph_node_is_unresolved_never_guessed():
    mapping = build_taxon_graph_mapping(LOAD, (), [node("taxon:101", "Exemplaria aurea")])
    rubra = mapping.link_for_name("Exemplaria rubra")
    assert rubra.status == UNRESOLVED and rubra.node_key is None
    assert rubra.reasons == (GRAPH_NODE_NOT_FOUND,)


def test_duplicate_graph_labels_are_ambiguous_and_list_every_candidate():
    graph = GRAPH + [node("taxon:999", "Exemplaria aurea Fict.")]
    link = build_taxon_graph_mapping(LOAD, (), graph).link_for_name("Exemplaria aurea")
    assert link.status == AMBIGUOUS and link.node_key is None
    assert GRAPH_DUPLICATE_LABEL in link.reasons
    assert link.candidate_node_keys == ("taxon:101", "taxon:999")


def test_inactive_and_non_taxon_nodes_are_ignored():
    graph = [node("taxon:101", "Exemplaria aurea"), {**node("taxon:7", "Exemplaria aurea"), "is_active": False}]
    assert build_taxon_graph_mapping(LOAD, (), graph).node_key_for_name("Exemplaria aurea") == "taxon:101"


def test_registry_homonym_is_ambiguous_even_when_the_registry_silently_keeps_one():
    load = LOAD + [{"name": "Exemplaria aurea Other", "taxon_code": "S"}]
    registry = build_canonical_registry(load)
    assert registry.resolve("Exemplaria aurea") is not None  # first-wins in the registry
    link = build_taxon_graph_mapping(load, (), GRAPH).link_for_name("Exemplaria aurea")
    assert link.status == AMBIGUOUS and REGISTRY_HOMONYM in link.reasons and link.node_key is None


def test_pro_parte_synonym_is_never_mapped_to_one_of_its_targets():
    synonyms = [syn("Fictorchis dubia", "Exemplaria aurea"), syn("Fictorchis dubia", "Exemplaria rubra")]
    registry = build_canonical_registry(LOAD, synonyms)
    assert registry.resolve("Fictorchis dubia").canonical_name == "Exemplaria aurea"  # silent first-wins
    link = build_taxon_graph_mapping(LOAD, synonyms, GRAPH).link_for_name("Fictorchis dubia")
    assert link.status == AMBIGUOUS and PRO_PARTE_SYNONYM in link.reasons and link.node_key is None


def test_a_graph_node_for_a_synonym_blocks_the_synonym_link():
    graph = GRAPH + [node("taxon:300", "Fictorchis aurea")]
    link = build_taxon_graph_mapping(LOAD, [syn("Fictorchis aurea", "Exemplaria aurea")], graph).link_for_name(
        "Fictorchis aurea"
    )
    assert link.status == AMBIGUOUS
    assert GRAPH_HAS_SEPARATE_NODE_FOR_SYNONYM in link.reasons
    assert link.node_key is None and link.candidate_node_keys == ("taxon:300",)


def test_synonym_that_is_also_an_accepted_name_blocks_the_accepted_link():
    mapping = build_taxon_graph_mapping(LOAD, [syn("Exemplaria rubra", "Exemplaria aurea")], GRAPH)
    rubra = mapping.link_for_name("Exemplaria rubra")
    assert rubra.status == AMBIGUOUS and SYNONYM_IS_ACCEPTED_NAME in rubra.reasons


def test_synonym_of_an_unlinked_accepted_taxon_is_unresolved():
    link = build_taxon_graph_mapping(LOAD, [syn("Fictorchis aurea", "Exemplaria aurea")], []).link_for_name(
        "Fictorchis aurea"
    )
    assert link.status == UNRESOLVED and link.reasons == (SYNONYM_TARGET_NOT_LINKED,)


@pytest.mark.parametrize(
    "name,safe",
    [
        ("Exemplaria aurea Fict.", True),
        ("Exemplaria aurea (L.) Fict.", True),
        ("Exemplaria", True),
        ("Cattleya labiata var. alba", False),
        ("Sobralia foo van den Berg", False),
        ("× Brassocattleya foo", False),
        ("Dendrobium nobile subsp. fictum Fict.", False),
    ],
)
def test_names_the_shared_normaliser_would_collapse_are_detected(name, safe):
    assert normalization_safe(name) is safe


def test_collapsed_infraspecific_names_are_not_mapped():
    load = [{"name": "Cattleya labiata var. alba", "taxon_code": "V"}]
    link = build_taxon_graph_mapping(load, (), [node("taxon:1", "Cattleya labiata var")]).link_for_name(
        "Cattleya labiata var. alba"
    )
    assert link.status == AMBIGUOUS and NAME_NORMALIZATION_UNSAFE in link.reasons and link.node_key is None
    assert strict_name_key("Cattleya labiata var. alba") == "Cattleya labiata var. alba"


def test_authority_ids_corroborate_or_block():
    authority = [{"canonical_name": "Exemplaria aurea", "authority": "powo", "external_id": "77-1"}]
    agree = build_taxon_graph_mapping(LOAD, (), [node("taxon:101", "Exemplaria aurea", authority_ids={"POWO": "77-1"})], authority)
    assert agree.link_for_name("Exemplaria aurea").mapping_class == MAP_EXACT_ID
    clash = build_taxon_graph_mapping(LOAD, (), [node("taxon:101", "Exemplaria aurea", authority_ids={"POWO": "99-9"})], authority)
    link = clash.link_for_name("Exemplaria aurea")
    assert link.status == AMBIGUOUS and AUTHORITY_ID_CONFLICT in link.reasons and link.node_key is None


def test_registry_adapter_never_returns_a_key_for_an_unverified_link():
    load = LOAD + [{"name": "Exemplaria aurea Other", "taxon_code": "S"}]
    registry = build_canonical_registry(load)
    mapping = build_taxon_graph_mapping(load, (), GRAPH)
    lookup = mapping.taxon_node_key(registry)
    ids = {t.canonical_name: t.canonical_id for t in registry.taxa.values()}
    assert lookup(ids["Exemplaria aurea"]) is None  # homonym
    assert lookup(ids["Exemplaria rubra"]) == "taxon:102"
    assert lookup(10_000) is None


def test_summary_counts_statuses_and_reasons():
    mapping = build_taxon_graph_mapping(
        LOAD + [{"name": "Exemplaria nivea Fict.", "taxon_code": "S"}],
        [syn("Fictorchis aurea", "Exemplaria aurea")],
        GRAPH + [node("taxon:5", "Lonely label"), node("taxon:6", "Lonely label")],
    )
    summary = mapping.summary()
    assert summary["by_status"] == {"accepted": 2, "synonym": 1, "unresolved": 1}
    assert summary["by_reason"] == {GRAPH_NODE_NOT_FOUND: 1}
    assert summary["graph_duplicate_labels"] == 1
    assert {row["canonical_name"] for row in mapping.to_dict()["links"]} >= {"Exemplaria nivea"}


def test_offline_script_builds_a_report_from_csv_exports(tmp_path):
    import json

    from scripts.build_taxon_graph_mapping import main

    (tmp_path / "load.csv").write_text("name,taxon_code\nExemplaria aurea Fict.,S\n")
    (tmp_path / "nodes.csv").write_text(
        "canonical_key,node_type,display_label,is_active\ntaxon:1,taxon,Exemplaria aurea,true\n"
        "taxon:2,taxon,Exemplaria aurea,false\n"
    )
    out = tmp_path / "mapping.json"
    assert main(
        [
            "--load-rows", str(tmp_path / "load.csv"),
            "--graph-nodes", str(tmp_path / "nodes.csv"),
            "--release-label", "test",
            "--output", str(out),
        ]
    ) == 0
    report = json.loads(out.read_text())
    assert report["summary"]["by_status"] == {"accepted": 1}
    assert report["links"][0]["node_key"] == "taxon:1"
    assert len(report["summary"]["release"]["inputs_sha256"]["load_rows"]) == 64
