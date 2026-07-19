import json
from pathlib import Path

from app.architecture import BrainArchitect


def write_doc(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_brain_architect_ingests_documents_and_preserves_provenance(tmp_path: Path):
    write_doc(
        tmp_path,
        "brain/philosophy/FOUNDING_CHARTER.md",
        "# Founding Charter\n\nThe Knowledge Graph and Runtime preserve provenance for scientific learning and conservation.",
    )
    write_doc(
        tmp_path,
        "docs/BUILD-077.md",
        "# BUILD-077\n\nOntology registry resolves evidence through /api/ontology without publication.",
    )

    result = BrainArchitect(tmp_path, tmp_path / "out").run(write=False)

    assert len(result.documents) == 2
    assert any(document.provenance for document in result.documents)
    assert "Knowledge Graph" in {domain for document in result.documents for domain in document.domains}
    assert "ontology registry" in result.canonical_terms


def test_brain_architect_writes_reproducible_outputs(tmp_path: Path):
    write_doc(
        tmp_path,
        "docs/architecture_note.md",
        "# Architecture Note\n\nRuntime depends on Mission Queue. Future roadmap should add Educational Intelligence detail.",
    )

    output_dir = tmp_path / "docs" / "architecture" / "BUILD-080"
    BrainArchitect(tmp_path, output_dir).run(write=True)
    first = (output_dir / "architecture_ontology.json").read_text(encoding="utf-8")
    BrainArchitect(tmp_path, output_dir).run(write=True)
    second = (output_dir / "architecture_ontology.json").read_text(encoding="utf-8")

    assert first == second
    assert (output_dir / "Orchid_Continuum_Master_Architecture.md").exists()
    assert (output_dir / "dependency_graph.md").exists()
    assert (output_dir / "roadmap.md").exists()


def test_build_080_outputs_are_additive_and_do_not_wire_runtime_or_routes():
    architecture_source = Path("app/architecture/brain_architect.py").read_text(encoding="utf-8").lower()
    main_source = Path("app/main.py").read_text(encoding="utf-8").lower()
    runtime_source = Path("runtime/router_fastapi.py").read_text(encoding="utf-8").lower()

    assert "drop table" not in architecture_source
    assert "delete from oc_" not in architecture_source
    assert "update oc_" not in architecture_source
    assert "include_router" not in architecture_source
    assert "build_080" not in main_source
    assert "build_080" not in runtime_source


def test_generated_ontology_contains_required_domains(tmp_path: Path):
    write_doc(
        tmp_path,
        "docs/source.md",
        "# Brain Source\n\nScientific Intelligence, Educational Intelligence, Knowledge Graph, Runtime, Governance, Infrastructure, Planning, Conservation, Community, Vision, Reasoning, Historical Intelligence, Research Intelligence, Collection Management.",
    )

    result = BrainArchitect(tmp_path, tmp_path / "out").run(write=True)
    domains = {domain.name for domain in result.ontology}
    payload = json.loads((tmp_path / "out" / "architecture_ontology.json").read_text(encoding="utf-8"))

    assert {
        "Scientific Intelligence",
        "Educational Intelligence",
        "Research Intelligence",
        "Engineering Intelligence",
        "Knowledge Graph",
        "Runtime",
        "Vision",
        "Collection Management",
        "Conservation",
        "Historical Intelligence",
        "Reasoning",
        "Community",
        "Governance",
        "Infrastructure",
        "Planning",
    }.issubset(domains)
    assert all("provenance" in domain for domain in payload)
