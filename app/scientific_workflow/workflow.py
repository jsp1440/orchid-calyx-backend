"""End-to-end scientific workflow orchestration (offline, deterministic).

Implements the mission's demonstration pipeline entirely over governed,
existing components plus deterministic fixtures:

    SOURCE -> ACQUISITION (fixture load) -> EXTRACTION (rule-based)
    -> TAXON RESOLUTION (fixture resolver) -> TERMINOLOGY NORMALISATION
    (lexicon service) -> CHARACTER EVIDENCE (store with provenance)
    -> KNOWLEDGE GRAPH (offline slice) -> MATRIX (governed engine)
    -> SPECIES DOSSIER (oc-species-dossier-v1) -> ILLUSTRATED GLOSSARY

No production database, no live provider calls, no paid services.  Live
acquisition (BHL harvest, POWO/IPNI resolution, Vision Lab) binds through the
same interfaces outside tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .dossier_bridge import build_dossier
from .evidence import CharacterEvidenceStore
from .extraction import CHARACTERS, extract_characters, parse_description_text
from .glossary import IllustrationRegistry, build_glossary_entry, build_glossary_index
from .graph_bridge import GraphSlice, build_graph_slice
from .matrix_bridge import (
    candidates_from_evidence,
    identify,
    observations_from_views,
    persist_registry,
)
from .models import CharacterObservationRecord, StateKind
from .taxonomy import FixtureTaxonResolver, TaxonRecord, TaxonResolution
from .terminology import CuratedTerminologyService, TermMatch

WORKFLOW_VERSION = "scientific-workflow-001"


@dataclass(frozen=True)
class DocumentResult:
    source_path: str
    resolution: TaxonResolution
    records: tuple[CharacterObservationRecord, ...]
    term_matches: tuple[TermMatch, ...]
    skipped: bool = False
    skip_reason: str | None = None


@dataclass
class WorkflowResult:
    documents: list[DocumentResult]
    taxa: dict[str, TaxonRecord]
    store: CharacterEvidenceStore
    registry_receipt: dict[str, Any] | None = None
    identifications: dict[str, dict[str, Any]] = field(default_factory=dict)
    dossiers: dict[str, Any] = field(default_factory=dict)
    glossary: dict[str, Any] = field(default_factory=dict)
    graph: GraphSlice | None = None

    def dossier_payload(self, taxon_id: str) -> dict[str, Any]:
        envelope = self.dossiers[taxon_id]
        return envelope.model_dump(mode="json")


@dataclass(frozen=True)
class FixtureLayout:
    """Locations of the deterministic fixtures used by the workflow."""

    root: Path

    @property
    def descriptions_dir(self) -> Path:
        return self.root / "descriptions"

    @property
    def lexicon_terms_csv(self) -> Path:
        return self.root / "lexicon_terms.csv"

    @property
    def oao_accessions_csv(self) -> Path:
        return self.root / "oao_accessions.csv"

    @property
    def taxa_csv(self) -> Path:
        return self.root / "taxa.csv"

    @property
    def illustrations_csv(self) -> Path:
        return self.root / "illustrations.csv"


def run_workflow(
    description_paths: list[Path],
    layout: FixtureLayout,
    *,
    registry_root: Path | None = None,
    registry_id: str = "scientific-workflow-demo",
    registry_version: str = "1",
    actor: str = "scientific-workflow-tests",
    identify_for: list[str] | None = None,
) -> WorkflowResult:
    """Run the full pipeline over a set of authorised description fixtures."""

    terminology = CuratedTerminologyService(layout.lexicon_terms_csv, layout.oao_accessions_csv)
    resolver = FixtureTaxonResolver(layout.taxa_csv)
    illustrations = IllustrationRegistry(layout.illustrations_csv)
    store = CharacterEvidenceStore()
    documents: list[DocumentResult] = []
    taxa: dict[str, TaxonRecord] = {}

    for path in description_paths:
        text = path.read_text(encoding="utf-8")
        parsed = parse_description_text(text, fallback_source_id=path.stem)
        resolution = resolver.resolve(parsed.taxon_name)
        if resolution.status != "resolved" or resolution.taxon is None:
            documents.append(
                DocumentResult(
                    source_path=str(path),
                    resolution=resolution,
                    records=(),
                    term_matches=(),
                    skipped=True,
                    skip_reason=resolution.explanation,
                )
            )
            continue
        records = extract_characters(parsed, resolution.taxon.taxon_id)
        store.add(records)
        term_matches = terminology.match_text(parsed.body)
        taxa[resolution.taxon.taxon_id] = resolution.taxon
        documents.append(
            DocumentResult(
                source_path=str(path),
                resolution=resolution,
                records=tuple(records),
                term_matches=tuple(term_matches),
            )
        )

    names = {taxon_id: taxon.full_scientific_name for taxon_id, taxon in taxa.items()}
    candidates = candidates_from_evidence(store, CHARACTERS, names=names)

    registry_receipt = None
    registry_ref = None
    if candidates:
        registry_receipt = persist_registry(
            store,
            registry_id=registry_id,
            version=registry_version,
            title="Scientific workflow demonstration matrix",
            scope={"family": "Orchidaceae", "fixture_run": True},
            actor=actor,
            root=registry_root,
        )
        registry_ref = {
            "registry_id": registry_id,
            "version": registry_version,
            "checksum_sha256": registry_receipt.get("record", {}).get("checksum_sha256"),
            "publication_state": registry_receipt.get("record", {}).get(
                "publication_state", "review_required"
            ),
        }

    result = WorkflowResult(documents=documents, taxa=taxa, store=store, registry_receipt=registry_receipt)

    for taxon_id in identify_for or []:
        views = store.views_for_taxon(taxon_id, [d.character_id for d in CHARACTERS])
        observations = observations_from_views(views, CHARACTERS)
        result.identifications[taxon_id] = identify(observations, candidates)

    for taxon_id, taxon in taxa.items():
        result.dossiers[taxon_id] = build_dossier(taxon, store, registry_ref=registry_ref)

    matrix_terms = sorted(
        {d.lexicon_term_id for d in CHARACTERS if d.lexicon_term_id}
    )
    result.glossary = {
        "index": build_glossary_index(terminology, illustrations),
        "entries": {
            term_id: build_glossary_entry(
                term_id,
                terminology,
                illustrations,
                matrix_character_ids=[
                    d.character_id for d in CHARACTERS if d.lexicon_term_id == term_id
                ],
            )
            for term_id in matrix_terms
        },
    }

    result.graph = build_graph_slice(store, taxa.values(), terminology)
    return result
