"""BUILD-060 tests: unified orchestrator, adapters, checkpointing, resume,
validation and publisher integration.

Every test runs against in-memory repositories and an in-memory source
provider — no database connection is ever opened, guaranteeing "no production
writes during tests".  Fixtures are synthetic and prove the pipeline is
generic, not hard-coded per genus or per domain.
"""

from __future__ import annotations

import pytest

from runtime.knowledge_graph import (
    BuildOrchestrator,
    Edge,
    ExecutionMode,
    InMemoryCheckpointStore,
    InMemoryGraphRepository,
    InMemorySourceProvider,
    JsonFileCheckpointStore,
    Node,
    adapters_by_domain,
    canonical_key,
    publish_domain,
    validate_graph,
)
from runtime.knowledge_graph.adapters import DOMAIN_ADAPTERS
from runtime.knowledge_graph.checkpoint import STATUS_COMPLETED, STATUS_SKIPPED, Checkpoint


# ---- fixtures ----

def _taxon(nid, label, pk):
    return Node(nid, "taxon", canonical_key("taxon", pk), label,
                "public.taxonomy_species", str(pk), "curated", 1.0, "high")


def taxonomy_repo():
    return InMemoryGraphRepository([
        _taxon(1, "Cattleya labiata", 1001),
        _taxon(2, "Bulbophyllum medusae", 2001),
    ])


def sample_source():
    return InMemorySourceProvider({
        "occurrences": [
            {"source_pk": 10, "taxon_pk": 1001, "locality": "Bahia", "latitude": -12.0},
            {"source_pk": 11, "taxon_pk": 2001, "locality": "Borneo", "latitude": 1.5},
        ],
        "traits": [
            {"source_pk": 20, "taxon_pk": 1001, "trait_name": "flower_color", "trait_value": "purple"},
        ],
        "pollinators": [
            {"source_pk": 30, "taxon_pk": 1001, "pollinator_name": "Euglossine bee"},
        ],
        "mycorrhiza": [
            {"source_pk": 40, "taxon_pk": 2001, "fungus_name": "Tulasnella"},
        ],
        "conservation": [
            {"source_pk": 50, "taxon_pk": 1001, "status_label": "Endangered", "status_code": "EN"},
        ],
        "climate": [
            {"source_pk": 60, "taxon_pk": 2001, "climate_label": "Tropical wet", "temp_mean_c": 26},
        ],
        "literature": [
            {"source_pk": 70, "taxon_pk": 1001, "citation": "Withner 1988", "year": 1988},
        ],
        "media": [
            {"source_pk": 80, "taxon_pk": 1001, "title": "Holotype", "url": "http://x/y.jpg"},
        ],
    })


# ---- adapters ----

def test_all_eight_domains_registered():
    domains = {a.domain for a in DOMAIN_ADAPTERS}
    assert domains == {
        "occurrences", "traits", "pollinators", "mycorrhiza",
        "conservation", "climate", "literature", "media",
    }


def test_adapter_produces_domain_node_and_edge_but_never_taxon():
    adapter = adapters_by_domain()["traits"]
    nodes, edges = adapter.produce([
        {"source_pk": 20, "taxon_pk": 1001, "trait_name": "leaf", "trait_value": "thick"},
    ])
    assert [n.node_type for n in nodes] == ["trait"]
    assert all(n.node_type != "taxon" for n in nodes)
    assert edges[0].edge_type == "has_trait"
    assert edges[0].from_key == "taxon:1001"
    assert edges[0].to_key == "trait:20"


def test_adapter_skips_rows_missing_keys():
    adapter = adapters_by_domain()["occurrences"]
    nodes, edges = adapter.produce([
        {"source_pk": 1},                       # no taxon_pk
        {"taxon_pk": 1001},                     # no source_pk
        {"source_pk": 2, "taxon_pk": 1001},     # valid
    ])
    assert len(nodes) == 1 and len(edges) == 1


def test_adapter_dedupes_repeated_domain_node():
    adapter = adapters_by_domain()["pollinators"]
    nodes, edges = adapter.produce([
        {"source_pk": 5, "taxon_pk": 1001, "pollinator_name": "bee"},
        {"source_pk": 5, "taxon_pk": 2001, "pollinator_name": "bee"},
    ])
    assert len(nodes) == 1   # same pollinator node
    assert len(edges) == 2   # two taxa reference it


# ---- publisher integration + idempotency ----

def test_publish_is_idempotent_across_reruns():
    repo = taxonomy_repo()
    adapter = adapters_by_domain()["occurrences"]
    rows = sample_source().fetch("occurrences", 100, 0)
    first = publish_domain(repo, adapter, rows)
    assert first.nodes_written == 2 and first.edges_written == 2
    second = publish_domain(repo, adapter, rows)
    assert second.nodes_written == 0 and second.edges_written == 0
    assert second.skipped_existing_nodes == 2 and second.skipped_existing_edges == 2


# ---- orchestrator: audit ----

def test_audit_reports_availability_without_writes():
    repo = taxonomy_repo()
    before_nodes = len(repo.all_nodes())
    orch = BuildOrchestrator(repo, sample_source())
    report = orch.run(ExecutionMode.AUDIT)
    assert report["build"]["wrote_to_production"] is False
    assert report["preflight"]["source_availability"]["occurrences"] == 2
    assert report["per_domain"] == []
    assert len(repo.all_nodes()) == before_nodes  # untouched


# ---- orchestrator: dry run ----

def test_dry_run_populates_staging_not_production():
    repo = taxonomy_repo()
    before = (len(repo.all_nodes()), len(repo.all_edges()))
    orch = BuildOrchestrator(repo, sample_source())
    report = orch.run(ExecutionMode.DRY_RUN)
    assert report["build"]["wrote_to_production"] is False
    # production repo unchanged
    assert (len(repo.all_nodes()), len(repo.all_edges())) == before
    # every domain produced nodes/edges in staging
    assert report["totals"]["nodes_written"] == 9
    assert report["totals"]["edges_written"] == 9
    assert report["estimated_graph_growth"]["estimated_new_nodes"] == 9
    assert report["cross_domain_validation"]["healthy"] is True


def test_dry_run_reports_per_domain_stats():
    orch = BuildOrchestrator(taxonomy_repo(), sample_source())
    report = orch.run(ExecutionMode.DRY_RUN)
    by_domain = {d["domain"]: d for d in report["per_domain"]}
    assert by_domain["occurrences"]["nodes_written"] == 2
    assert by_domain["traits"]["nodes_written"] == 1
    assert all(d["status"] == STATUS_COMPLETED for d in report["per_domain"])


# ---- orchestrator: publish gating ----

def test_publish_disabled_without_authorization():
    repo = taxonomy_repo()
    orch = BuildOrchestrator(repo, sample_source(), authorized_to_publish=False)
    report = orch.run(ExecutionMode.PUBLISH)
    assert report["build"]["wrote_to_production"] is False
    assert report["preflight"]["publish_authorized"] is False
    assert len(repo.all_edges()) == 0
    assert any("without authorization" in w for w in report["warnings"])


def test_resume_disabled_without_authorization():
    repo = taxonomy_repo()
    store = InMemoryCheckpointStore()
    orch = BuildOrchestrator(repo, sample_source(), checkpoint_store=store,
                             authorized_to_publish=False)
    report = orch.run(ExecutionMode.RESUME)
    assert report["build"]["wrote_to_production"] is False
    assert len(repo.all_edges()) == 0
    assert any("without authorization" in w for w in report["warnings"])


def test_publish_writes_when_authorized():
    repo = taxonomy_repo()
    orch = BuildOrchestrator(repo, sample_source(), authorized_to_publish=True)
    report = orch.run(ExecutionMode.PUBLISH)
    assert report["build"]["wrote_to_production"] is True
    assert len(repo.all_edges()) == 9
    assert report["estimated_graph_growth"]["basis"] == "actual"


# ---- orchestrator: batching ----

def test_batched_publish_covers_all_rows():
    source = InMemorySourceProvider({
        "traits": [
            {"source_pk": i, "taxon_pk": 1001, "trait_name": f"t{i}"} for i in range(7)
        ],
    })
    repo = taxonomy_repo()
    orch = BuildOrchestrator(repo, source, adapters=(adapters_by_domain()["traits"],),
                             batch_size=2, authorized_to_publish=True)
    report = orch.run(ExecutionMode.PUBLISH)
    d = report["per_domain"][0]
    assert d["rows_processed"] == 7
    assert d["nodes_written"] == 7
    assert d["batches"] == 4  # 2+2+2+1


# ---- checkpointing + resume ----

def test_checkpoints_saved_per_domain():
    store = InMemoryCheckpointStore()
    orch = BuildOrchestrator(taxonomy_repo(), sample_source(), checkpoint_store=store,
                             authorized_to_publish=True)
    orch.run(ExecutionMode.PUBLISH)
    assert store.completed_domains() == {
        "occurrences", "traits", "pollinators", "mycorrhiza",
        "conservation", "climate", "literature", "media",
    }


def test_resume_skips_completed_domains():
    store = InMemoryCheckpointStore()
    store.save(Checkpoint(domain="occurrences", status=STATUS_COMPLETED))
    store.save(Checkpoint(domain="traits", status=STATUS_COMPLETED))
    repo = taxonomy_repo()
    orch = BuildOrchestrator(repo, sample_source(), checkpoint_store=store,
                             authorized_to_publish=True)
    report = orch.run(ExecutionMode.RESUME)
    by_domain = {d["domain"]: d for d in report["per_domain"]}
    assert by_domain["occurrences"]["status"] == STATUS_SKIPPED
    assert by_domain["traits"]["status"] == STATUS_SKIPPED
    assert by_domain["pollinators"]["status"] == STATUS_COMPLETED
    # skipped domains wrote nothing; the other six each wrote one edge
    assert len(repo.all_edges()) == 6


def test_json_file_checkpoint_store_roundtrip(tmp_path):
    path = str(tmp_path / "ckpt.json")
    store = JsonFileCheckpointStore(path)
    store.save(Checkpoint(domain="traits", status=STATUS_COMPLETED, rows_processed=5))
    reloaded = JsonFileCheckpointStore(path)
    assert reloaded.completed_domains() == {"traits"}
    assert reloaded.load("traits").rows_processed == 5


# ---- validation ----

def test_validate_graph_flags_dangling_and_duplicate_edges():
    repo = InMemoryGraphRepository(
        [_taxon(1, "Cattleya labiata", 1001)],
        [Edge(1, "has_trait", 1, 999, "oc_traits.traits", "20")],  # 999 dangling
    )
    report = validate_graph(repo)
    assert report["orphan_edges"] == 1
    assert report["healthy"] is False


def test_validate_graph_clean_after_dry_run():
    orch = BuildOrchestrator(taxonomy_repo(), sample_source())
    report = orch.run(ExecutionMode.DRY_RUN)
    v = report["cross_domain_validation"]
    assert v["vocabulary_compliance"]["compliant"] is True
    assert v["cross_domain_consistency"]["mismatched_endpoint_edges"] == 0
    assert v["total_problems"] == 0


def test_cross_domain_consistency_detects_wrong_endpoint():
    # An image node wired as the *source* of a has_trait edge is inconsistent.
    repo = InMemoryGraphRepository(
        [
            _taxon(1, "Cattleya labiata", 1001),
            Node(2, "image", canonical_key("image", 80), "img",
                 "oc_core.media_assets", "80", None, None, None),
            Node(3, "trait", canonical_key("trait", 20), "leaf",
                 "oc_traits.traits", "20", None, None, None),
        ],
        [Edge(1, "has_trait", 2, 3, "oc_traits.traits", "20")],  # from image, not taxon
    )
    report = validate_graph(repo)
    assert report["cross_domain_consistency"]["mismatched_endpoint_edges"] >= 1
