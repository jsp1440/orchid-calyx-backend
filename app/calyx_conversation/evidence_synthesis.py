from __future__ import annotations

import hashlib
import json
from typing import Any

SYNTHESIS_CONTRACT_VERSION = "CALYX-EVIDENCE-SYNTHESIS-001"


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _text(value: Any, limit: int = 1200) -> str:
    return " ".join(str(value or "").split())[:limit]


def _evidence_item(
    *,
    evidence_id: str,
    source_family: str,
    evidence_type: str,
    status: str,
    title: str,
    statement: str,
    provenance: dict[str, Any] | None = None,
    subject: str | None = None,
    predicate: str | None = None,
    value: Any = None,
    review_state: str | None = None,
    confidence: float | None = None,
) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "source_family": source_family,
        "evidence_type": evidence_type,
        "status": status,
        "title": _text(title, 300),
        "statement": _text(statement),
        "subject": _text(subject, 300) if subject else None,
        "predicate": _text(predicate, 300) if predicate else None,
        "value": value,
        "review_state": review_state,
        "confidence": confidence,
        "provenance": provenance or {},
    }


def _mission_items(mission: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    if not mission:
        return [], [], [], []
    supporting: list[dict[str, Any]] = []
    contradicting: list[dict[str, Any]] = []
    conclusions: list[dict[str, Any]] = []
    mission_id = str(mission.get("mission_id") or "mission")

    for index, item in enumerate(mission.get("supporting_evidence") or []):
        if not isinstance(item, dict):
            continue
        statement = " ".join(
            str(value) for value in (item.get("subject"), item.get("predicate"), item.get("value"))
            if value not in (None, "")
        )
        supporting.append(_evidence_item(
            evidence_id=f"{mission_id}:support:{index}", source_family="brain_mission",
            evidence_type="canonical_extracted_evidence", status="supports", title="Brain mission supporting evidence",
            statement=statement, subject=item.get("subject"), predicate=item.get("predicate"), value=item.get("value"),
            provenance={"mission_id": mission_id, "candidate_id": item.get("candidate_id"), "source_revision_id": item.get("source_revision_id"), "source_anchor_ids": item.get("source_anchor_ids")},
            review_state=mission.get("review_status"), confidence=mission.get("confidence"),
        ))
    for index, item in enumerate(mission.get("contradicting_evidence") or []):
        if not isinstance(item, dict):
            continue
        statement = " ".join(
            str(value) for value in (item.get("subject"), item.get("predicate"), item.get("value"))
            if value not in (None, "")
        )
        contradicting.append(_evidence_item(
            evidence_id=f"{mission_id}:contradict:{index}", source_family="brain_mission",
            evidence_type="canonical_extracted_evidence", status="contradicts", title="Brain mission contradicting evidence",
            statement=statement, subject=item.get("subject"), predicate=item.get("predicate"), value=item.get("value"),
            provenance={"mission_id": mission_id, "candidate_id": item.get("candidate_id"), "source_revision_id": item.get("source_revision_id"), "source_anchor_ids": item.get("source_anchor_ids")},
            review_state=mission.get("review_status"), confidence=mission.get("confidence"),
        ))
    for index, item in enumerate(mission.get("conclusions") or []):
        if isinstance(item, dict) and _text(item.get("text")):
            conclusions.append({
                "conclusion_id": f"{mission_id}:conclusion:{index}",
                "type": item.get("type") or "inference",
                "text": _text(item.get("text"), 1800),
                "claim_ids": item.get("claim_ids") or [],
                "confidence": mission.get("confidence"),
                "review_state": mission.get("review_status"),
            })
    return supporting, contradicting, [str(v) for v in mission.get("missing_evidence") or []], conclusions


def build_synthesis_packet(
    *,
    question: str,
    retrieval: dict[str, Any],
    continuum: dict[str, Any],
    climate: dict[str, Any],
    mission: dict[str, Any] | None,
    mission_error: str | None,
    interaction_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize heterogeneous Calyx tool outputs into one reasoning-ready contract.

    The packet is intentionally conversational, read-only, and non-publishing. It does
    not replace the scientific interpretation/promotion pipeline; it standardizes the
    handoff into conversational synthesis so the model reasons across sources instead
    of narrating each source family independently.
    """
    evidence: list[dict[str, Any]] = []

    for index, item in enumerate(retrieval.get("results") or []):
        if not isinstance(item, dict):
            continue
        evidence.append(_evidence_item(
            evidence_id=f"retrieval:{item.get('result_id') or index}",
            source_family="continuum_retrieval", evidence_type=str(item.get("object_type") or "canonical_object").lower(),
            status="available", title=str(item.get("title") or item.get("object_type") or "Continuum evidence"),
            statement=str(item.get("authorized_excerpt") or item.get("text") or item.get("summary") or ""),
            provenance={"result_id": item.get("result_id"), "citation": item.get("citation"), "revision_id": item.get("revision_id")},
            review_state=str(item.get("review_state") or "CANONICAL_OR_GOVERNED"),
        ))

    external = retrieval.get("external_literature") or {}
    for index, item in enumerate(external.get("results") or []):
        if not isinstance(item, dict):
            continue
        ids = {key: item.get(key) for key in ("doi", "pmid", "pmcid") if item.get(key)}
        evidence.append(_evidence_item(
            evidence_id=f"external-literature:{item.get('pmid') or item.get('doi') or index}",
            source_family="external_literature", evidence_type="literature_discovery", status="review_required",
            title=str(item.get("title") or "External literature"),
            statement=str(item.get("abstract") or item.get("authorized_excerpt") or ""),
            provenance={"provider": item.get("source") or "Europe PMC", **ids, "authors": item.get("authors"), "publication_date": item.get("publication_date"), "journal": item.get("journal")},
            review_state=str(item.get("review_state") or "REVIEW_REQUIRED"),
        ))

    for taxon in continuum.get("taxa") or []:
        if not isinstance(taxon, dict):
            continue
        genus = str(taxon.get("genus") or taxon.get("scientific_name") or "resolved taxon")
        for index, fact in enumerate(taxon.get("environmental_facts") or []):
            if isinstance(fact, dict):
                statement = str(fact.get("statement") or fact.get("value") or fact)
                provenance = {"taxon": genus, "fact": fact}
            else:
                statement, provenance = str(fact), {"taxon": genus}
            evidence.append(_evidence_item(
                evidence_id=f"graph:{genus}:{index}", source_family="knowledge_graph", evidence_type="canonical_graph_fact",
                status="available", title=f"Knowledge Graph fact for {genus}", statement=statement,
                provenance=provenance, review_state="CANONICAL_READ_ONLY",
            ))

    for index, product in enumerate(climate.get("products") or []):
        if not isinstance(product, dict):
            continue
        points = product.get("summary_points") or []
        statement = " ".join(str(v) for v in points[:8]) or str(product.get("text") or "")
        evidence.append(_evidence_item(
            evidence_id=f"climate:{index}", source_family="climate", evidence_type="time_sensitive_external_context",
            status="context_only", title=str(product.get("product") or "NOAA CPC climate product"), statement=statement,
            provenance={"provider": climate.get("provider"), "issued_text": product.get("issued_text")}, review_state="EXTERNAL_TIME_SENSITIVE",
        ))

    supporting, contradicting, missing, conclusions = _mission_items(mission)
    evidence.extend(supporting)
    evidence.extend(contradicting)

    source_families = sorted({str(item.get("source_family")) for item in evidence if item.get("source_family")})
    unresolved_conflict = bool(contradicting)
    retrieval_gap = not bool(retrieval.get("results"))
    if mission_error:
        missing.append(f"Brain mission unavailable: {mission_error}")
    if retrieval_gap and not (external.get("results") or []):
        missing.append("No canonical or external literature retrieval evidence was available for this turn.")

    packet = {
        "contract_version": SYNTHESIS_CONTRACT_VERSION,
        "question": _text(question, 4000),
        "interaction_context": interaction_context or {},
        "evidence_items": evidence,
        "reconciliation": {
            "supporting_evidence_ids": [item["evidence_id"] for item in supporting],
            "contradicting_evidence_ids": [item["evidence_id"] for item in contradicting],
            "unresolved_conflict": unresolved_conflict,
            "missing_evidence": list(dict.fromkeys(_text(item, 800) for item in missing if _text(item, 800))),
            "source_families": source_families,
            "canonical_retrieval_gap": retrieval_gap,
            "external_literature_review_required": bool(external.get("results")),
        },
        "candidate_conclusions": conclusions,
        "synthesis_plan": {
            "answer_first": True,
            "integrate_across_sources": True,
            "do_not_narrate_sources_sequentially": True,
            "steps": [
                "Identify the biological claim or decision the user is actually asking about.",
                "Combine evidence items that bear on the same claim, regardless of source family.",
                "Resolve agreement and contradiction before composing prose.",
                "Connect morphology/anatomy to function, physiology, habitat, interactions, evolution, cultivation, or conservation when supported.",
                "State the best-supported conclusion first, then explain why it follows from the combined evidence.",
                "Label inference, uncertainty, external review-required literature, and missing evidence naturally.",
                "Keep implementation details and source-by-source inventories out of the main answer unless requested.",
            ],
        },
        "publication_boundary": {
            "read_only": True,
            "automatic_publication": False,
            "knowledge_graph_mutation": False,
        },
    }
    packet["fingerprint"] = _fingerprint(packet)
    return packet


def provider_context(governed_context: dict[str, Any]) -> dict[str, Any]:
    """Return the compact semantic handoff used by generative providers.

    Raw subsystem payloads remain available server-side and in the API response for
    diagnostics, but generative providers receive the normalized synthesis contract
    plus only the policies/capabilities needed to answer safely.
    """
    return {
        "synthesis_packet": governed_context.get("synthesis_packet") or {},
        "epistemic_policy": governed_context.get("epistemic_policy") or {},
        "deliverable_capabilities": governed_context.get("deliverable_capabilities") or {},
        "provider_configuration": governed_context.get("provider_configuration") or {},
        "casual": bool(governed_context.get("casual")),
    }
