from runtime.knowledge_graph import InMemoryGraphRepository
from runtime.knowledge_graph.adapters import IMAGES_ADAPTER
from runtime.knowledge_graph.models import Node
from runtime.knowledge_graph.resumable_dry_run import JsonSessionStore, RUN_COMPLETED, RUN_RUNNING
from runtime.knowledge_graph.resumable_executor import create_session, resume_session
from runtime.knowledge_graph.sources import InMemorySourceProvider


def graph_with_taxon():
    repo = InMemoryGraphRepository()
    repo.upsert_node(Node(
        kg_node_id=1,
        node_type="taxon",
        canonical_key="taxon:42",
        display_label="Cattleya labiata",
        source_table="taxonomy",
        source_pk="42",
    ))
    return repo


def test_resumable_execution_is_bounded_and_zero_delta(tmp_path):
    rows = [
        {"source_pk": f"image-{i}", "taxon_pk": 42, "media_url": f"https://example.org/{i}.jpg"}
        for i in range(5)
    ]
    source = InMemorySourceProvider({"media": rows})
    store = JsonSessionStore(str(tmp_path / "sessions"))
    session = create_session(
        store,
        domains=["media"],
        allowed_domains={"media"},
        batch_size=2,
        max_batches_per_step=1,
    )

    first = resume_session(
        store, str(tmp_path / "staging"), graph_with_taxon(), source,
        {"media": IMAGES_ADAPTER}, session.run_id,
    )
    state = first["session"]["domain_states"]["media"]
    assert first["session"]["status"] == RUN_RUNNING
    assert state["offset"] == 2
    assert state["first_nodes"] == 2

    report = first
    for _ in range(10):
        report = resume_session(
            store, str(tmp_path / "staging"), graph_with_taxon(), source,
            {"media": IMAGES_ADAPTER}, session.run_id,
        )
        if report["session"]["status"] == RUN_COMPLETED:
            break

    state = report["session"]["domain_states"]["media"]
    assert report["session"]["status"] == RUN_COMPLETED
    assert state["first_nodes"] == 5
    assert state["first_edges"] == 5
    assert state["second_nodes"] == 0
    assert state["second_edges"] == 0
    assert report["zero_delta"] is True
    assert report["publication_authorization_ready"] is True
    assert report["production_graph_mutation"] is False


def test_session_rejects_unavailable_domain(tmp_path):
    store = JsonSessionStore(str(tmp_path / "sessions"))
    try:
        create_session(
            store,
            domains=["not-a-domain"],
            allowed_domains={"media"},
            batch_size=10,
            max_batches_per_step=1,
        )
    except ValueError as exc:
        assert "Unsupported or unavailable domains" in str(exc)
    else:
        raise AssertionError("Unavailable domain should be rejected")
