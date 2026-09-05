from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SYNTHESIS_CONTRACT_VERSION = "CALYX-EVIDENCE-SYNTHESIS-002"

_STOPWORDS = {
    "about", "after", "again", "against", "also", "among", "because", "before",
    "being", "between", "could", "does", "from", "have", "into", "more", "most",
    "other", "over", "same", "should", "than", "that", "their", "there", "these",
    "they", "this", "through", "under", "very", "what", "when", "where", "which",
    "while", "with", "would", "across", "orchid", "orchids",
}


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _text(value: Any, limit: int = 1200) -> str:
    return " ".join(str(value or "").split())[:limit]


def _terms(value: Any) -> set[str]:
    words = re.findall(r"[a-z][a-z0-9-]{2,}", _text(value, 5000).casefold())
    return {word for word in words if word not in _STOPWORDS}


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


def _mission_items(
    mission: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[dict[str, Any]]]:
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
            str(value)
            for value in (item.get("subject"), item.get("predicate"), item.get("value"))
            if value not in (None, "")
        )
        supporting.append(
            _evidence_item(
                evidence_id=f"{mission_id}:support:{index}",
                source_family="brain_mission",
                evidence_type="canonical_extracted_evidence",
                status="supports",
                title="Brain mission supporting evidence",
                statement=statement,
                subject=item.get("subject"),
                predicate=item.get("predicate"),
                value=item.get("value"),
                provenance={
                    "mission_id": mission_id,
                    "candidate_id": item.get("candidate_id"),
                    "source_revision_id": item.get("source_revision_id"),
                    "source_anchor_ids": item.get("source_anchor_ids"),
                },
                review_state=mission.get("review_status"),
                confidence=mission.get("confidence"),
            )
        )
    for index, item in enumerate(mission.get("contradicting_evidence") or []):
        if not isinstance(item, dict):
            continue
        statement = " ".join(
            str(value)
            for value in (item.get("subject"), item.get("predicate"), item.get("value"))
            if value not in (None, "")
        )
        contradicting.append(
            _evidence_item(
                evidence_id=f"{mission_id}:contradict:{index}",
                source_family="brain_mission",
                evidence_type="canonical_extracted_evidence",
                status="contradicts",
                title="Brain mission contradicting evidence",
                statement=statement,
                subject=item.get("subject"),
                predicate=item.get("predicate"),
                value=item.get("value"),
                provenance={
                    "mission_id": mission_id,
                    "candidate_id": item.get("candidate_id"),
                    "source_revision_id": item.get("source_revision_id"),
                    "source_anchor_ids": item.get("source_anchor_ids"),
                },
                review_state=mission.get("review_status"),
                confidence=mission.get("confidence"),
            )
        )
    for index, item in enumerate(mission.get("conclusions") or []):
        if isinstance(item, dict) and _text(item.get("text")):
            conclusions.append(
                {
                    "conclusion_id": f"{mission_id}:conclusion:{index}",
                    "type": item.get("type") or "inference",
                    "text": _text(item.get("text"), 1800),
                    "claim_ids": item.get("claim_ids") or [],
                    "confidence": mission.get("confidence"),
                    "review_state": mission.get("review_status"),
                }
            )
    return supporting, contradicting, [str(v) for v in mission.get("missing_evidence") or []], conclusions


def _question_claims(question: str) -> list[dict[str, Any]]:
    cleaned = _text(question, 4000)
    parts = [
        part.strip(" .?!")
        for part in re.split(
            r"[?;]+|\band\s+(?=how|why|what|which|whether|can|does|do|is|are|should)\b",
            cleaned,
            flags=re.IGNORECASE,
        )
        if part.strip(" .?!")
    ]
    if not parts and cleaned:
        parts = [cleaned]
    return [
        {"claim_id": f"question:{index}", "kind": "question_component", "text": part}
        for index, part in enumerate(parts[:8])
    ]


def _claim_evidence_edges(
    claims: list[dict[str, Any]], evidence: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for claim in claims:
        claim_terms = _terms(claim.get("text"))
        ranked: list[tuple[float, dict[str, Any]]] = []
        for item in evidence:
            evidence_terms = _terms(
                " ".join(
                    str(v or "")
                    for v in (
                        item.get("title"),
                        item.get("statement"),
                        item.get("subject"),
                        item.get("predicate"),
                        item.get("value"),
                    )
                )
            )
            score = len(claim_terms & evidence_terms) / max(1, len(claim_terms))
            if item.get("source_family") == "brain_mission" and item.get("status") in {
                "supports",
                "contradicts",
            }:
                score += 0.25
            if score > 0:
                ranked.append((score, item))
        for score, item in sorted(ranked, key=lambda pair: pair[0], reverse=True)[:6]:
            if item.get("status") == "contradicts":
                relation = "contradicts"
            elif item.get("status") == "context_only":
                # Time-sensitive climate and other context may inform how a
                # question is framed, but it is not evidence that supports the
                # biological claim itself.
                relation = "informs_context"
            else:
                relation = "supports_or_informs"
            edges.append(
                {
                    "claim_id": claim["claim_id"],
                    "evidence_id": item["evidence_id"],
                    "relation": relation,
                    "relevance": round(min(score, 1.0), 3),
                }
            )
    return edges


def _reasoning_graph(
    question: str,
    evidence: list[dict[str, Any]],
    conclusions: list[dict[str, Any]],
    missing: list[str],
) -> dict[str, Any]:
    claims = _question_claims(question)
    for conclusion in conclusions:
        claims.append(
            {
                "claim_id": conclusion["conclusion_id"],
                "kind": conclusion.get("type") or "inference",
                "text": conclusion["text"],
            }
        )
    edges = _claim_evidence_edges(claims, evidence)
    by_claim: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        by_claim.setdefault(edge["claim_id"], []).append(edge)
    coverage = []
    for claim in claims:
        linked = by_claim.get(claim["claim_id"], [])
        has_support = any(edge["relation"] == "supports_or_informs" for edge in linked)
        has_context = any(edge["relation"] == "informs_context" for edge in linked)
        has_contradiction = any(edge["relation"] == "contradicts" for edge in linked)
        if has_support and has_contradiction:
            coverage_state = "contested"
        elif has_support:
            coverage_state = "supported"
        elif has_contradiction:
            coverage_state = "contradicted"
        else:
            coverage_state = "unresolved"
        coverage.append(
            {
                "claim_id": claim["claim_id"],
                "evidence_count": len(linked),
                "supporting_or_informing_count": sum(
                    edge["relation"] in {"supports_or_informs", "informs_context"}
                    for edge in linked
                ),
                "supporting_count": sum(
                    edge["relation"] == "supports_or_informs" for edge in linked
                ),
                "informing_count": sum(
                    edge["relation"] == "informs_context" for edge in linked
                ),
                "contradicting_count": sum(edge["relation"] == "contradicts" for edge in linked),
                "has_context_only": has_context,
                "has_contradiction": has_contradiction,
                "coverage": coverage_state,
            }
        )
    return {
        "claims": claims,
        "edges": edges,
        "coverage": coverage,
        "missing_evidence": list(
            dict.fromkeys(_text(item, 800) for item in missing if _text(item, 800))
        ),
        "instructions": [
            "Reason claim-by-claim, not source-by-source.",
            "Use evidence edges to combine different source families around the same biological claim.",
            "Treat context-only evidence as framing information, never as support for a biological claim.",
            "Treat contradiction as a reason to qualify or reject a claim, never as support for it.",
            "Do not convert correlation into mechanism or adaptation unless the linked evidence supports that step.",
        ],
    }


def _bounded_graph_evidence(
    *,
    genus: str,
    graph: dict[str, Any] | None,
    source_label: str,
    evidence_prefix: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    if not isinstance(graph, dict):
        return []
    evidence: list[dict[str, Any]] = []
    remaining = limit
    for collection in ("nodes", "edges"):
        for index, record in enumerate(graph.get(collection) or []):
            if remaining <= 0:
                return evidence
            if not isinstance(record, dict):
                continue
            record_text = _text(json.dumps(record, sort_keys=True, default=str), 1200)
            if not record_text:
                continue
            evidence.append(
                _evidence_item(
                    evidence_id=f"{evidence_prefix}:{genus}:{collection}:{index}",
                    source_family="knowledge_graph",
                    evidence_type=f"canonical_{source_label}_{collection[:-1]}",
                    status="available",
                    title=f"{source_label.replace('_', ' ').title()} {collection[:-1]} for {genus}",
                    statement=record_text,
                    provenance={
                        "taxon": genus,
                        "graph_source": source_label,
                        "collection": collection,
                        "canonical_key": record.get("canonical_key"),
                        "edge_type": record.get("edge_type"),
                    },
                    review_state="CANONICAL_READ_ONLY",
                )
            )
            remaining -= 1
    return evidence


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
    """Normalize heterogeneous tool outputs and map them onto the claims being answered."""
    interaction_context = interaction_context or {}
    resolved_question = _text(
        question
        or interaction_context.get("current_question")
        or interaction_context.get("question"),
        4000,
    )
    evidence: list[dict[str, Any]] = []
    for index, item in enumerate(retrieval.get("results") or []):
        if not isinstance(item, dict):
            continue
        evidence.append(
            _evidence_item(
                evidence_id=f"retrieval:{item.get('result_id') or index}",
                source_family="continuum_retrieval",
                evidence_type=str(item.get("object_type") or "canonical_object").lower(),
                status="available",
                title=str(item.get("title") or item.get("object_type") or "Continuum evidence"),
                statement=str(
                    item.get("authorized_excerpt")
                    or item.get("text")
                    or item.get("summary")
                    or ""
                ),
                provenance={
                    "result_id": item.get("result_id"),
                    "citation": item.get("citation"),
                    "revision_id": item.get("revision_id"),
                },
                review_state=str(item.get("review_state") or "CANONICAL_OR_GOVERNED"),
            )
        )
    external = retrieval.get("external_literature") or {}
    for index, item in enumerate(external.get("results") or []):
        if not isinstance(item, dict):
            continue
        ids = {key: item.get(key) for key in ("doi", "pmid", "pmcid") if item.get(key)}
        evidence.append(
            _evidence_item(
                evidence_id=f"external-literature:{item.get('pmid') or item.get('doi') or index}",
                source_family="external_literature",
                evidence_type="literature_discovery",
                status="review_required",
                title=str(item.get("title") or "External literature"),
                statement=str(item.get("abstract") or item.get("authorized_excerpt") or ""),
                provenance={
                    "provider": item.get("source") or "Europe PMC",
                    **ids,
                    "authors": item.get("authors"),
                    "publication_date": item.get("publication_date"),
                    "journal": item.get("journal"),
                },
                review_state=str(item.get("review_state") or "REVIEW_REQUIRED"),
            )
        )
    for taxon in continuum.get("taxa") or []:
        if not isinstance(taxon, dict):
            continue
        genus = str(taxon.get("genus") or taxon.get("scientific_name") or "resolved taxon")
        graph = taxon.get("knowledge_graph") or {}
        brain_graph = taxon.get("brain_graph") or {}
        evidence.extend(
            _bounded_graph_evidence(
                genus=genus,
                graph=graph,
                source_label="knowledge_graph",
                evidence_prefix="graph",
            )
        )
        evidence.extend(
            _bounded_graph_evidence(
                genus=genus,
                graph=brain_graph,
                source_label="brain_graph",
                evidence_prefix="brain-graph",
            )
        )
        for index, fact in enumerate(taxon.get("environmental_facts") or []):
            if isinstance(fact, dict):
                statement = str(fact.get("statement") or fact.get("value") or fact)
                provenance = {"taxon": genus, "fact": fact}
            else:
                statement = str(fact)
                provenance = {"taxon": genus}
            evidence.append(
                _evidence_item(
                    evidence_id=f"graph:{genus}:environment:{index}",
                    source_family="knowledge_graph",
                    evidence_type="canonical_graph_fact",
                    status="available",
                    title=f"Knowledge Graph environmental fact for {genus}",
                    statement=statement,
                    provenance=provenance,
                    review_state="CANONICAL_READ_ONLY",
                )
            )
    for index, link in enumerate(continuum.get("semantic_links") or []):
        if not isinstance(link, dict):
            continue
        evidence.append(
            _evidence_item(
                evidence_id=f"semantic-link:{index}",
                source_family="knowledge_graph",
                evidence_type="approved_semantic_link",
                status="available",
                title="Approved Continuum semantic link",
                statement=_text(json.dumps(link, sort_keys=True, default=str), 1200),
                provenance={"semantic_link": link},
                review_state="APPROVED_SEMANTIC_READ_ONLY",
            )
        )
    for index, product in enumerate(climate.get("products") or []):
        if not isinstance(product, dict):
            continue
        points = product.get("summary_points") or []
        climate_text = " ".join(str(v) for v in points[:8]) or str(product.get("text") or "")
        statement = (
            "NOAA/NWS Climate Prediction Center: " + climate_text
            if climate_text
            else "NOAA/NWS Climate Prediction Center context was retrieved."
        )
        evidence.append(
            _evidence_item(
                evidence_id=f"climate:{index}",
                source_family="climate",
                evidence_type="time_sensitive_external_context",
                status="context_only",
                title=str(product.get("product") or "NOAA CPC climate product"),
                statement=statement,
                provenance={
                    "provider": climate.get("provider")
                    or "NOAA/NWS Climate Prediction Center",
                    "issued_text": product.get("issued_text"),
                },
                review_state="EXTERNAL_TIME_SENSITIVE",
            )
        )
    supporting, contradicting, missing, conclusions = _mission_items(mission)
    evidence.extend(supporting)
    evidence.extend(contradicting)
    source_families = sorted(
        {str(item.get("source_family")) for item in evidence if item.get("source_family")}
    )
    retrieval_gap = not bool(retrieval.get("results"))
    if mission_error:
        missing.append(f"Brain mission unavailable: {mission_error}")
    if mission is None and retrieval_gap and not (external.get("results") or []):
        missing.append(
            "No canonical or external literature retrieval evidence was available for this turn."
        )
    reasoning_graph = _reasoning_graph(resolved_question, evidence, conclusions, missing)
    packet = {
        "contract_version": SYNTHESIS_CONTRACT_VERSION,
        "question": resolved_question,
        "question_preserved": bool(resolved_question),
        "interaction_context": interaction_context,
        "evidence_items": evidence,
        "reconciliation": {
            "supporting_evidence_ids": [item["evidence_id"] for item in supporting],
            "contradicting_evidence_ids": [item["evidence_id"] for item in contradicting],
            "unresolved_conflict": bool(contradicting),
            "missing_evidence": reasoning_graph["missing_evidence"],
            "source_families": source_families,
            "canonical_retrieval_gap": retrieval_gap,
            "external_literature_review_required": bool(external.get("results")),
        },
        "candidate_conclusions": conclusions,
        "reasoning_graph": reasoning_graph,
        "synthesis_plan": {
            "answer_first": True,
            "integrate_across_sources": True,
            "do_not_narrate_sources_sequentially": True,
            "steps": [
                "Identify the biological claim or decision the user is actually asking about.",
                "Walk the reasoning_graph claim-by-claim and combine evidence linked to the same claim regardless of source family.",
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
    return {
        "synthesis_packet": governed_context.get("synthesis_packet") or {},
        "scientific_memory": governed_context.get("scientific_memory") or {},
        "epistemic_policy": governed_context.get("epistemic_policy") or {},
        "deliverable_capabilities": governed_context.get("deliverable_capabilities") or {},
        "provider_configuration": governed_context.get("provider_configuration") or {},
        "casual": bool(governed_context.get("casual")),
    }
