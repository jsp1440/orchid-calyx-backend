"""Scientific convergence demo: botanical description -> KG-compatible output.

Provider-free end-to-end demonstration of the integrated pathway:

    Botanical description
      -> anatomical concept      (Illustrated Orchid Lexicon, via Brain bridge)
      -> character/state         (OAO term registry resolution)
      -> taxonomic context       (Calyx canonical resolver, exact match only)
      -> Lexicon reference       (concept id/slug carried in provenance)
      -> Matrix evidence         (Calyx governed registry + session + report)
      -> KG-compatible output    (records valid against the Calyx
                                  oc-kg-materialization/v1 contract)

Modules used (all pre-existing, no new extraction/ontology infrastructure):
  - Brain PR #233  tools/oao_lexicon_matrix_kg_bridge.py
  - Calyx #1793-#1796 chain  runtime/matrix_identification*，
    runtime/matrix_taxon_resolution.py
  - Calyx main     app/scientific_adapter_lab/kg_materialization.py (contract)

Environment:
  OC_BRAIN_ROOT  path to a Brain checkout containing PR #233 files
                 (default: ../brain relative to OC_CALYX_ROOT's parent in the
                 local integration workspace; demo exits 2 with a clear
                 message when unavailable).
  OC_CALYX_ROOT  path to the Calyx repo root (default: parent of this file's
                 parent directory).

No network, no paid providers, no database, no migrations.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
CALYX_ROOT = Path(os.environ.get("OC_CALYX_ROOT", HERE.parents[2]))
BRAIN_ROOT = Path(os.environ.get("OC_BRAIN_ROOT", CALYX_ROOT.parent / "brain"))

sys.path.insert(0, str(CALYX_ROOT))
sys.path.insert(0, str(BRAIN_ROOT / "tools"))

try:
    import oao_lexicon_matrix_kg_bridge as brain_bridge
except ImportError:
    print(
        "OC_BRAIN_ROOT does not contain the Brain PR #233 bridge "
        f"(looked in {BRAIN_ROOT / 'tools'}). Set OC_BRAIN_ROOT.",
        file=sys.stderr,
    )
    sys.exit(2)

from app.scientific_adapter_lab.kg_materialization import (  # noqa: E402
    KGMaterializationRecord,
    KGEvidenceState,
    SourceDomain,
)
from runtime.matrix_identification import Candidate  # noqa: E402
from runtime.matrix_identification_registry import (  # noqa: E402
    RegistryCharacter,
    create_registry_version,
)
from runtime.matrix_identification_session import (  # noqa: E402
    add_observation,
    create_session,
    evaluate_session,
)
from runtime.matrix_taxon_resolution import StaticTaxonResolver, TaxonEntry  # noqa: E402

CHECKS: list[tuple[str, bool]] = []


def check(name: str, ok: bool) -> None:
    CHECKS.append((name, ok))
    print(f"   {'PASS' if ok else 'FAIL'} {name}")


def load_brain_bridge() -> "brain_bridge.OaoLexiconMatrixKgBridge":
    fixtures = BRAIN_ROOT / "fixtures" / "oao_bridge"
    return brain_bridge.OaoLexiconMatrixKgBridge(
        eq_mappings=brain_bridge.load_oao_eq_mappings(
            BRAIN_ROOT / brain_bridge.OAO_EQ_MAPPINGS_PATH
        ),
        term_registry=brain_bridge.load_oao_term_registry(
            BRAIN_ROOT / brain_bridge.OAO_TERM_REGISTRY_PATH
        ),
        lexicon=brain_bridge.load_lexicon_export(fixtures / "lexicon_export_fixture.json"),
        accessions=brain_bridge.load_accession_table(
            fixtures / "oao_accession_resolution_slice.csv"
        ),
    )


def oao_concept_uuid_map() -> dict[str, str]:
    """OAO term id -> canonical concept UUID (Brain OAO Term Registry).

    The Calyx Matrix binds characters to canonical concepts by UUID; the Brain
    OAO Term Registry is the existing canonical source of those UUIDs
    (one registry_id UUID per governed OAO term). No new resolver is invented.
    """
    return {
        row.oao_id: row.registry_id
        for row in brain_bridge.load_oao_term_registry(
            BRAIN_ROOT / brain_bridge.OAO_TERM_REGISTRY_PATH
        )
    }


def validate_against_calyx_kg_contract(payload: dict) -> KGMaterializationRecord:
    """Re-express a Brain bridge KG record under the real Calyx contract."""
    record = KGMaterializationRecord(
        record_id=payload["record_id"],
        source_domain=SourceDomain(payload["source_domain"]),
        evidence_state=KGEvidenceState(payload["evidence_state"]),
        taxon_id=payload["taxon_id"],
        taxon_name=payload["taxon_name"],
        subject_entity=payload["subject_entity"],
        predicate=payload["predicate"],
        object_entity=payload["object_entity"],
        provenance_chain=tuple(payload["provenance_chain"]),
        human_review_required=payload["human_review_required"],
        schema_version=payload["schema_version"],
    )
    record.validate()  # raises on any contract violation
    return record


def main() -> int:
    print("== 0. Load pre-existing modules (Brain bridge + Calyx Matrix + KG contract) ==")
    bridge = load_brain_bridge()
    evidence = json.loads(
        (BRAIN_ROOT / "fixtures" / "oao_bridge" / "representative_orchid_evidence.json")
        .read_text(encoding="utf-8")
    )["observations"]
    description = evidence[0]  # Cattleya sp. — Labellum Margin = fimbriate
    print(f"   botanical description: {description['taxon_name']} / "
          f"{description['character_name']} = {description['observed_state']} "
          f"(source: {description['source']})")

    print("== 1. Anatomical concept + character/state (Brain OAO-Lexicon bridge) ==")
    result = bridge.ingest_evidence(description)
    concept = result["lexicon_concept"]
    state = result["oao_state_matched"]
    print(f"   lexicon concept: {concept['slug']} ({concept['preferred_term']}, "
          f"match: {concept['match_kind']})")
    print(f"   OAO state: {state['term_label']} ({state['oao_id']}, "
          f"applicability: {result['applicability']})")
    check("anatomical_concept_matched", concept["slug"] == "labellum")
    check("character_state_resolved", state["oao_id"] == "OAO:0000017")

    print("== 2. KG-compatible output validated against the REAL Calyx contract ==")
    calyx_validated = [
        validate_against_calyx_kg_contract(rec) for rec in result["kg_records"]
    ]
    for rec in calyx_validated:
        print(f"   {rec.record_id} [{rec.predicate}] review={rec.human_review_required}")
    check("kg_records_valid_under_calyx_contract", len(calyx_validated) == 3)
    check(
        "kg_records_review_bound",
        all(r.human_review_required for r in calyx_validated),
    )
    lexicon_ref = f"lexicon:{concept['lexicon_id']}:{concept['slug']}"
    check(
        "lexicon_reference_in_provenance",
        any(lexicon_ref in r.provenance_chain for r in calyx_validated),
    )

    print("== 3. Taxonomic context (Calyx canonical resolver, exact matching only) ==")
    resolver = StaticTaxonResolver(
        [
            TaxonEntry(
                canonical_taxon_id="world-plants:cattleya-labiata",
                accepted_name="Cattleya labiata",
                synonyms=("Cattleya labiata var. autumnalis",),
            ),
            TaxonEntry(
                canonical_taxon_id="world-plants:cattleya-mossiae",
                accepted_name="Cattleya mossiae",
            ),
        ]
    )
    ctx_species = resolver.resolve("Cattleya labiata")
    ctx_genus_only = resolver.resolve(description["taxon_name"])  # "Cattleya sp."
    print(f"   'Cattleya labiata' -> {ctx_species.resolution_state} "
          f"({ctx_species.canonical_taxon_id})")
    print(f"   '{description['taxon_name']}' -> {ctx_genus_only.resolution_state} "
          "(not fabricated into a species)")
    check("canonical_resolution_exact", ctx_species.resolution_state == "resolved_canonical")
    check("unresolvable_name_stays_unresolved", ctx_genus_only.resolution_state == "unresolved")

    print("== 4. Matrix evidence (Calyx governed registry + session + report) ==")
    concept_uuids = oao_concept_uuid_map()
    margin_character = next(
        row for row in result["oao_characters"] if row["oao_id"] == "OAO:0000007"
    )
    margin_concept_uuid = margin_character["registry_id"]
    outline_concept_uuid = concept_uuids["OAO:0000008"]
    print(f"   canonical concept binding: labellum_margin -> OAO:0000007 "
          f"({margin_concept_uuid})")
    print(f"   canonical concept binding: labellum_outline_shape -> OAO:0000008 "
          f"({outline_concept_uuid})")
    check(
        "concept_uuid_from_canonical_oao_registry",
        margin_concept_uuid == concept_uuids["OAO:0000007"]
        and outline_concept_uuid == "35e67796-fbb7-4d29-86ee-769e084a6c8e",
    )
    with tempfile.TemporaryDirectory() as tmp:
        registry_root = Path(tmp) / "registries"
        session_root = Path(tmp) / "sessions"
        create_registry_version(
            registry_id="cattleya-demo",
            version="1",
            title="Cattleya bounded diagnostic matrix (convergence demo)",
            scope={"genus": "Cattleya"},
            characters=[
                RegistryCharacter(
                    "labellum_margin",
                    "Labellum margin",
                    weight=3,
                    concept_id=margin_concept_uuid,
                    provenance={
                        "oao_character_id": "OAO:0000007",
                        "oao_state_id": state["oao_id"],
                        "oao_term": state["term_label"],
                        "lexicon": concept["slug"],
                    },
                ),
                RegistryCharacter(
                    "labellum_outline_shape",
                    "Labellum outline shape",
                    weight=1,
                    concept_id=outline_concept_uuid,
                    provenance={"oao_character_id": "OAO:0000008"},
                ),
            ],
            candidates=[
                Candidate(
                    "world-plants:cattleya-labiata",
                    "Cattleya labiata",
                    {"labellum_margin": "fimbriate", "labellum_outline_shape": "ovate"},
                ),
                Candidate(
                    "world-plants:cattleya-mossiae",
                    "Cattleya mossiae",
                    {"labellum_margin": "crenulate", "labellum_outline_shape": "orbicular"},
                ),
            ],
            provenance={"source": "convergence demo governed assertions"},
            actor="convergence-demo",
            root=registry_root,
        )
        session = create_session(
            registry_id="cattleya-demo",
            version="1",
            actor="convergence-demo",
            root=session_root,
            registry_root=registry_root,
        )
        add_observation(
            session["session_id"],
            character="labellum_margin",
            value=str(description["observed_state"]),
            certainty="certain",
            source={
                "kind": "botanical_description",
                "evidence_id": description["evidence_id"],
                "lexicon_concept": concept["slug"],
                "oao_state_id": state["oao_id"],
                "bridge_kg_record_ids": [r.record_id for r in calyx_validated],
                # No human reviewed this fixture observation; say so.
                "review_state": "review_required",
            },
            actor="convergence-demo",
            access_actor="convergence-demo",
            root=session_root,
            registry_root=registry_root,
        )
        evaluation = evaluate_session(
            session["session_id"],
            access_actor="convergence-demo",
            root=session_root,
            registry_root=registry_root,
        )
    leader = evaluation["report"]["candidates"][0]
    print(f"   identification leader (hypothesis): {leader['scientific_name']} "
          f"score={leader['score']} coverage={leader['coverage']}")
    print(f"   provenance carried: evidence={description['evidence_id']} "
          f"lexicon={concept['slug']} oao={state['oao_id']}")
    check("matrix_leader_matches_evidence", leader["taxon_id"] == "world-plants:cattleya-labiata")
    check(
        "matrix_evidence_cross_referenced",
        leader["taxon_id"] == ctx_species.canonical_taxon_id,
    )

    print("== 5. Conflicting evidence preserved, never collapsed ==")
    conflict_pair = [e for e in evidence if e["evidence_id"] in ("EV-0003", "EV-0004")]
    batch = bridge.ingest_evidence_batch(conflict_pair)
    conflict = batch["conflicts"][0]
    print(f"   {conflict['taxon_id']}: {conflict['conflicting_states']} "
          f"-> {conflict['resolution']}")
    both_scored = all(r["kg_records"] for r in batch["results"])
    check("conflict_preserved_not_collapsed", conflict["resolution"] == "preserved_not_collapsed")
    check("both_conflicting_records_emitted", both_scored)

    print("== 6. Summary ==")
    failed = [name for name, ok in CHECKS if not ok]
    print(f"   {len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    if failed:
        print(f"   FAILED: {failed}")
        print("morphology_pathway_demo_ok=False")
        return 1
    print("morphology_pathway_demo_ok=True")
    return 0


if __name__ == "__main__":
    sys.exit(main())
