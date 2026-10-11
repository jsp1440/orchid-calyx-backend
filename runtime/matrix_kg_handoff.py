"""Governed Knowledge Graph handoff for Matrix identification reports (Phase 4).

Materializes ``oc-kg-materialization/v1`` records from the governed
identification report through the *existing* Scientific Adapter Lab contract
(``app.scientific_adapter_lab.kg_materialization``) — the same schema the
Brain bridge (PR #233) emits — without duplicating that implementation and
without any graph mutation:

* every record carries ``human_review_required=True`` (enforced by the
  contract's own validation) and a non-empty provenance chain;
* ``KnowledgeGraphPipeline`` governance is constructed here so the
  no-automatic-publication / no-KG-mutation invariants are enforced at
  handoff time, not just documented;
* evidence state is ``canonical_unreviewed``: the ranking derives from
  canonical Matrix data and review-gated observations, but promotion to
  ``canonical_reviewed`` is itself the human scientific decision these
  records request — it is never asserted automatically;
* record ids are deterministic (uuid5 over the content-addressed report
  checksum + candidate taxon), so rebuilding the handoff from identical
  evidence yields identical records — idempotent, restart-stable, and
  safe to regenerate;
* nothing is published, written to a graph, or mutated in canonical
  taxonomy. Publication requires explicit owner authorization and a
  separate governed step.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.scientific_adapter_lab.kg_materialization import (
    SCHEMA_VERSION as KG_SCHEMA_VERSION,
    KGEvidenceState,
    KGMaterializationRecord,
    KnowledgeGraphPipeline,
    SourceDomain,
)
from runtime.matrix_identification_session import get_session
from runtime.matrix_identification_workflow import (
    DEFAULT_AMBIGUITY_EPSILON,
    build_identification_report,
)
from runtime.matrix_taxon_resolution import TaxonResolver

KG_HANDOFF_SCHEMA = "matrix-kg-handoff/v1"

HANDOFF_PREDICATE = "oc:rankedIdentificationCandidate"

PROMOTION_RULE = (
    "These records are governed KG-ready materializations of a Matrix "
    "identification report. Publication into the Knowledge Graph and any "
    "promotion to canonical_reviewed evidence require explicit owner "
    "authorization and human scientific review; nothing is published or "
    "mutated automatically."
)


def _record_id(report_checksum: str, taxon_id: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"orchid-continuum:matrix-kg-handoff:{report_checksum}:{taxon_id}",
        )
    )


def _provenance_chain(report: dict[str, Any], session: dict[str, Any]) -> tuple[str, ...]:
    """Assemble the bounded provenance chain shared by this handoff's records."""
    registry = report.get("registry") or {}
    chain: list[str] = [
        f"matrix-identification-report:{report.get('checksum_sha256')}",
        f"matrix-session:{session.get('session_id')}",
        (
            f"matrix-registry:{registry.get('registry_id')}@"
            f"{registry.get('version')}:{registry.get('checksum_sha256')}"
        ),
    ]
    reviewers = sorted(
        {
            str((item.get("source") or {}).get("reviewer"))
            for item in session.get("observations", [])
            if (item.get("source") or {}).get("reviewer")
        }
    )
    chain.extend(f"matrix-reviewer:{reviewer}" for reviewer in reviewers)
    images = session.get("contributor_images") or {}
    for submission_id in sorted(images):
        image = images[submission_id] or {}
        chain.append(
            f"contributor-image:{submission_id}:{image.get('content_sha256')}"
        )
    for analysis_id in sorted(session.get("vision_analyses") or {}):
        chain.append(f"vision-analysis:{analysis_id}")
    return tuple(chain)


def build_kg_handoff(
    session_id: str,
    *,
    limit: int = 20,
    ambiguity_epsilon: float = DEFAULT_AMBIGUITY_EPSILON,
    taxon_resolver: TaxonResolver | None = None,
    synonym_entries: list[dict[str, Any]] | None = None,
    source_assertions: list[dict[str, Any]] | None = None,
    access_actor: str | None = None,
    root=None,
    registry_root=None,
) -> dict[str, Any]:
    """Materialize governed KG records from one session's identification report.

    Read-only with respect to evidence (the report build only refreshes the
    session's own evaluation cache). One record per ranked candidate; an
    empty ranking yields an empty, explicitly reported record set.
    """
    pipeline = KnowledgeGraphPipeline()  # governance invariants enforced here
    report = build_identification_report(
        session_id,
        limit=limit,
        ambiguity_epsilon=ambiguity_epsilon,
        taxon_resolver=taxon_resolver,
        synonym_entries=synonym_entries,
        source_assertions=source_assertions,
        access_actor=access_actor,
        root=root,
        registry_root=registry_root,
    )
    session = get_session(session_id, root=root, access_actor=access_actor)
    chain = _provenance_chain(report, session)

    records: list[KGMaterializationRecord] = []
    for candidate in report.get("ranked_candidates", []):
        resolution = candidate.get("taxonomic_resolution") or {}
        accepted_name = resolution.get("accepted_name") or candidate.get(
            "scientific_name"
        )
        record = KGMaterializationRecord(
            record_id=_record_id(
                str(report["checksum_sha256"]), str(candidate.get("taxon_id"))
            ),
            source_domain=SourceDomain.TRAITS,
            evidence_state=KGEvidenceState.CANONICAL_UNREVIEWED,
            taxon_id=str(candidate.get("taxon_id")),
            taxon_name=str(accepted_name or ""),
            subject_entity=f"matrix:identification-session/{session_id}",
            predicate=HANDOFF_PREDICATE,
            object_entity=f"taxon:{candidate.get('taxon_id')}",
            provenance_chain=chain,
            human_review_required=True,
        )
        record.validate()
        records.append(record)

    return {
        "schema_version": KG_HANDOFF_SCHEMA,
        "kg_schema_version": KG_SCHEMA_VERSION,
        "session_id": session_id,
        "report_checksum_sha256": report.get("checksum_sha256"),
        "handoff_state": "materialized_for_governed_review",
        "publication_state": "not_published",
        "records": [record.to_safe_dict() for record in records],
        "record_count": len(records),
        "candidate_evidence": [
            {
                "record_id": record.record_id,
                "taxon_id": record.taxon_id,
                "score": candidate.get("score"),
                "coverage": candidate.get("coverage"),
                "resolution_state": (
                    candidate.get("taxonomic_resolution") or {}
                ).get("resolution_state"),
            }
            for record, candidate in zip(
                records, report.get("ranked_candidates", []), strict=True
            )
        ],
        "governance": {
            "automatic_publication": pipeline.automatic_publication,
            "knowledge_graph_mutation": pipeline.knowledge_graph_mutation,
            "human_review_required": True,
            "evidence_state": KGEvidenceState.CANONICAL_UNREVIEWED.value,
            "promotion_rule": PROMOTION_RULE,
        },
    }
