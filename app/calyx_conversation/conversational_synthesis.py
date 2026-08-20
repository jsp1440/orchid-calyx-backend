"""Compose ONE integrated conversational answer from the governed synthesis packet.

This is a RESPONSE COMPOSER, not a second reasoning engine, conversation service
or evidence store. It consumes the packet that
``CALYX-EVIDENCE-SYNTHESIS-002`` (``evidence_synthesis.build_synthesis_packet``)
already produces and renders it as conversation.

Why it exists
-------------
The synthesis packet decomposes the user's question into claims, links evidence
to each claim across source families, and marks each claim ``supported`` /
``contested`` / ``contradicted`` / ``unresolved``. Its own ``synthesis_plan``
says ``do_not_narrate_sources_sequentially``.

The previous deterministic composer discarded that structure and emitted one
labelled block per source family -- "Evidence summary:", "External literature
context:", "Climate context:", "Governed provenance:" -- which is the
source-inventory behaviour the reasoning contract exists to prevent. Anything
walking source families instead of claims produces a list of facts and leaves
the reader to integrate them.

What this module may and may not do
-----------------------------------
It walks ``reasoning_graph.claims`` and, for each claim, combines the evidence
linked to it regardless of which subsystem supplied it. Every sentence it emits
is built from statements already present in the packet plus connective language.

It must never:
  * assert a mechanism, cause or adaptation that no linked evidence states;
  * turn contradicting evidence into support;
  * render unavailable evidence as a measured zero or as biological absence;
  * put counts, identifiers, confidence scores or subsystem names into the prose
    (those belong in the inspectable structure, per the conversational
    constitution).

It is a DEGRADED path: it composes, it does not reason generatively. When it is
used because no generative provider is configured or the provider failed, it
says so plainly rather than impersonating a full synthesis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

COMPOSER_CONTRACT_VERSION = "CALYX-CONVERSATIONAL-SYNTHESIS-001"

# A follow-up turn carries its subject only by reference ("why?", "what about
# that?"). These are matched to decide whether the prior subject must be
# restated so the answer visibly continues the same investigation.
_FOLLOW_UP_PATTERNS = (
    r"^why\b",
    r"^how so\b",
    r"^and\b",
    r"^so\b",
    r"^what (?:evidence|about|does that|do you)\b",
    r"^(?:what|which) (?:is|are) (?:that|those|it|they)\b",
    r"^tell me more\b",
    r"^go on\b",
    r"^explain\b",
    r"^(?:is|are|does|do|can|could|would) (?:that|it|they|those)\b",
)

_REFERENTIAL_ONLY_MAX_WORDS = 12


@dataclass
class ComposedAnswer:
    """Conversational prose plus the machinery that must stay out of it."""

    text: str
    structure: dict[str, Any] = field(default_factory=dict)


def _clean(value: Any, limit: int = 600) -> str:
    return " ".join(str(value or "").split())[:limit]


def _sentence(text: str) -> str:
    text = _clean(text).rstrip(" ;,")
    if not text:
        return ""
    if text[-1] not in ".?!":
        text += "."
    return text[0].upper() + text[1:]


def _humanize(text: str) -> str:
    """Render machine predicates as language.

    Graph and mission evidence arrives as subject/predicate/value triples whose
    predicates are identifiers (``characterised_by``, ``not_correlated_with``).
    Printed verbatim they read as database output, which is precisely the
    register this composer exists to avoid. Only the separator changes -- no
    word is added, removed or reinterpreted.
    """

    return re.sub(r"(?<=\w)_(?=\w)", " ", text)


def _statement_of(item: dict[str, Any]) -> str:
    """The most human phrasing an evidence item offers, without labels."""

    statement = _clean(item.get("statement"))
    if statement:
        return _humanize(statement.rstrip("."))
    parts = [
        _clean(item.get(key), 200)
        for key in ("subject", "predicate", "value")
        if _clean(item.get(key), 200)
    ]
    if parts:
        return _humanize(" ".join(parts))
    return _humanize(_clean(item.get("title"), 200).rstrip("."))


def is_follow_up(question: str) -> bool:
    """True when the turn depends on a prior subject to be intelligible."""

    normalized = " ".join(str(question or "").casefold().split()).strip(" .!?,")
    if not normalized:
        return False
    if len(normalized.split()) > _REFERENTIAL_ONLY_MAX_WORDS:
        return False
    return any(re.match(pattern, normalized) for pattern in _FOLLOW_UP_PATTERNS)


def resolve_subject(question: str, history: list[dict[str, str]] | None) -> str:
    """Recover the substantive subject a follow-up turn refers back to.

    Only prior USER turns are consulted. Prior assistant statements are never
    treated as evidence or as the subject of record.
    """

    if not is_follow_up(question):
        return _clean(question, 400)
    for item in reversed(history or []):
        if str(item.get("role")) != "user":
            continue
        content = _clean(item.get("content"), 400)
        if content and not is_follow_up(content):
            return content
    return _clean(question, 400)


def _evidence_by_id(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("evidence_id")): item
        for item in packet.get("evidence_items") or []
        if isinstance(item, dict) and item.get("evidence_id")
    }


def _claim_groups(packet: dict[str, Any]) -> list[dict[str, Any]]:
    """Group evidence under each question claim, ACROSS source families.

    This is the whole point of the module: iteration is claim-first. A claim
    supported by a trait record, a habitat record and a paper becomes one
    integrated statement, not three subsystem announcements.
    """

    reasoning = packet.get("reasoning_graph") or {}
    evidence_by_id = _evidence_by_id(packet)
    coverage_by_claim = {
        str(entry.get("claim_id")): entry
        for entry in reasoning.get("coverage") or []
        if isinstance(entry, dict)
    }

    edges_by_claim: dict[str, list[dict[str, Any]]] = {}
    for edge in reasoning.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        edges_by_claim.setdefault(str(edge.get("claim_id")), []).append(edge)

    groups: list[dict[str, Any]] = []
    for claim in reasoning.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        claim_id = str(claim.get("claim_id"))
        edges = sorted(
            edges_by_claim.get(claim_id, []),
            key=lambda item: float(item.get("relevance") or 0.0),
            reverse=True,
        )
        supporting: list[dict[str, Any]] = []
        contradicting: list[dict[str, Any]] = []
        for edge in edges:
            item = evidence_by_id.get(str(edge.get("evidence_id")))
            if not item:
                continue
            if edge.get("relation") == "contradicts":
                contradicting.append(item)
            else:
                supporting.append(item)
        coverage = coverage_by_claim.get(claim_id) or {}
        groups.append(
            {
                "claim_id": claim_id,
                "kind": str(claim.get("kind") or ""),
                "text": _clean(claim.get("text"), 400),
                "supporting": supporting,
                "contradicting": contradicting,
                "coverage": str(coverage.get("coverage") or "unresolved"),
                "source_families": sorted(
                    {
                        str(item.get("source_family"))
                        for item in supporting + contradicting
                        if item.get("source_family")
                    }
                ),
            }
        )
    return groups


def _integrated_sentence(group: dict[str, Any]) -> str:
    """One sentence connecting everything linked to a single claim.

    The connective language ("taken together with", "alongside") joins evidence;
    it never asserts a relationship the evidence does not already state.
    """

    statements: list[str] = []
    for item in group["supporting"][:3]:
        statement = _statement_of(item)
        if statement and statement not in statements:
            statements.append(statement)
    if not statements:
        return ""

    claim_text = group["text"].rstrip("?.")
    if len(statements) == 1:
        body = statements[0]
    elif len(statements) == 2:
        body = f"{statements[0]}, taken together with {statements[1][0].lower() + statements[1][1:]}"
    else:
        head = ", ".join(statements[:-1])
        body = f"{head}, and alongside those {statements[-1][0].lower() + statements[-1][1:]}"

    if (
        claim_text
        and group["kind"] == "question_component"
        and not is_follow_up(claim_text)
        and len(claim_text.split()) >= 4
    ):
        return _sentence(f"On {claim_text.lower()}: {body}")
    return _sentence(body)


def _crosses_source_families(groups: list[dict[str, Any]]) -> bool:
    return any(len(group["source_families"]) > 1 for group in groups)


def compose_conversational_answer(
    *,
    packet: dict[str, Any],
    history: list[dict[str, str]] | None = None,
    casual: bool = False,
    mission_error: str | None = None,
    generative: bool = False,
    resolved_subject: str | None = None,
    follow_up: bool | None = None,
) -> ComposedAnswer:
    """Render the governed synthesis packet as one continuous answer.

    ``resolved_subject`` is the investigation subject the turn continues, as
    resolved server-side from persistent conversation state. It is supplied
    rather than re-derived because the provider message window is truncated as
    a conversation grows, which would silently drop the original subject.
    """

    packet = packet or {}
    question = _clean(packet.get("question"), 600)
    subject = _clean(resolved_subject, 600) or resolve_subject(question, history)
    if follow_up is None:
        follow_up = is_follow_up(question) and subject != question
    follow_up = bool(follow_up) and bool(subject)

    reconciliation = packet.get("reconciliation") or {}
    conclusions = [
        _clean(item.get("text"), 600)
        for item in packet.get("candidate_conclusions") or []
        if isinstance(item, dict) and _clean(item.get("text"), 600)
    ]
    missing = [
        _clean(item, 300)
        for item in reconciliation.get("missing_evidence") or []
        if _clean(item, 300)
    ]
    groups = _claim_groups(packet)
    answerable = [group for group in groups if group["supporting"]]
    cited_families = {
        family for group in groups for family in group["source_families"] if family
    }
    contested = [
        group
        for group in groups
        if group["contradicting"] and group["coverage"] in {"contested", "contradicted"}
    ]

    structure: dict[str, Any] = {
        "composer_contract": COMPOSER_CONTRACT_VERSION,
        "generative": bool(generative),
        "degraded_composition": not generative,
        "resolved_subject": subject,
        "follow_up_turn": follow_up,
        "claim_coverage": [
            {
                "claim_id": group["claim_id"],
                "claim": group["text"],
                "coverage": group["coverage"],
                "source_families": group["source_families"],
                "supporting_count": len(group["supporting"]),
                "contradicting_count": len(group["contradicting"]),
            }
            for group in groups
        ],
        "integrated_across_source_families": _crosses_source_families(groups),
        "cited_source_families": sorted(cited_families),
        "source_families": reconciliation.get("source_families") or [],
        "missing_evidence": missing,
        "canonical_retrieval_gap": bool(reconciliation.get("canonical_retrieval_gap")),
        "external_literature_review_required": bool(
            reconciliation.get("external_literature_review_required")
        ),
        "unresolved_conflict": bool(reconciliation.get("unresolved_conflict")),
    }

    if casual:
        return ComposedAnswer(
            text=(
                "Hello. I'm Calyx, the Orchid Continuum's scientific collaborator. Ask me an "
                "orchid-science question and I'll work through the evidence the Continuum "
                "actually holds with you, keeping what's solid, what's contested and what's "
                "still missing clearly apart."
            ),
            structure={**structure, "casual": True},
        )

    if mission_error:
        # An unavailable governed mission is a retrieval failure, never a
        # finding. Say so, and do not present anything as established.
        return ComposedAnswer(
            text=(
                f"I couldn't complete a governed evidence run for {subject or 'this question'}, "
                "so I'm not going to give you a conclusion that would look more settled than it is. "
                "Whatever records are on hand stay evidence inputs until that run succeeds — "
                "this is a gap in what I could retrieve, not a finding about the biology."
            ),
            structure={**structure, "mission_unavailable": True},
        )

    paragraphs: list[str] = []

    # 1. Answer first — the question that was actually asked, restating the
    #    subject when the turn only referred to it.
    opener_prefix = ""
    if follow_up and subject:
        reference = subject.rstrip("?.")
        if len(reference) > 110:
            reference = reference[:107].rstrip(" ,;") + "…"
        opener_prefix = f"Staying with {reference} — "

    if conclusions:
        lead = " ".join(_sentence(text) for text in conclusions[:2])
        paragraphs.append(_sentence(opener_prefix + lead[0].lower() + lead[1:]) if opener_prefix else lead)
    elif answerable:
        best = answerable[0]
        lead_body = _integrated_sentence(best)
        supported_claims = [g for g in answerable if g["coverage"] == "supported"]
        if supported_claims:
            qualifier = "here is what the linked evidence supports"
        else:
            qualifier = "the evidence points this way without settling it"
        paragraphs.append(_sentence(f"{opener_prefix}{qualifier}: {lead_body[0].lower() + lead_body[1:]}"))
    else:
        gap_reason = (
            "nothing in the Continuum came back linked to it"
            if structure["canonical_retrieval_gap"]
            else "the evidence that did come back doesn't reach the question"
        )
        paragraphs.append(
            _sentence(
                f"{opener_prefix}I can't answer that from evidence yet — {gap_reason}. "
                "That's an absence of records, not an indication that the biology works either way"
            )
        )

    # 2. Integration — one pass over CLAIMS, combining source families per claim.
    integration: list[str] = []
    seen_evidence: set[frozenset[str]] = set()
    if answerable and not conclusions:
        # The lead paragraph already spoke for the first answerable claim.
        seen_evidence.add(
            frozenset(str(item.get("evidence_id")) for item in answerable[0]["supporting"][:3])
        )
    for group in answerable:
        key = frozenset(str(item.get("evidence_id")) for item in group["supporting"][:3])
        if not key or key in seen_evidence:
            continue
        sentence = _integrated_sentence(group)
        if sentence:
            seen_evidence.add(key)
            integration.append(sentence)
    if integration:
        paragraphs.append(" ".join(integration[:4]))

    # 3. Qualification — contradiction stays contradiction.
    if contested:
        conflict_bits: list[str] = []
        for group in contested:
            for item in group["contradicting"]:
                against = _statement_of(item).rstrip(".")
                if against and against not in conflict_bits:
                    conflict_bits.append(against)
            if len(conflict_bits) >= 2:
                break
        if conflict_bits:
            paragraphs.append(
                _sentence(
                    "The evidence isn't all pointing one way, though: "
                    + "; ".join(conflict_bits)
                    + ". I'm treating that as a reason to hold the conclusion loosely rather than "
                    "as further support for it"
                )
            )

    if structure["external_literature_review_required"]:
        paragraphs.append(
            _sentence(
                "Some of what informed that came from published literature that hasn't been "
                "through Continuum review yet, so treat it as provisional rather than as "
                "settled Continuum evidence"
            )
        )

    if "climate" in cited_families:
        # Climate products are time-sensitive external conditions. They can
        # frame a question but do not establish orchid physiological responses,
        # and the composer must not let them pass as biological support.
        paragraphs.append(
            _sentence(
                "The climate material in there is time-sensitive external context about "
                "conditions — it does not establish orchid physiological responses on its own, "
                "so I'm not treating it as evidence for the biology"
            )
        )

    # 4. What is genuinely not known.
    if missing:
        paragraphs.append(
            _sentence(
                "What would actually move this forward is "
                + "; ".join(item.rstrip(".") for item in missing[:3])
                + " — that's missing evidence, not evidence of absence"
            )
        )

    if not generative:
        paragraphs.append(
            _sentence(
                "One caveat about this particular reply: my generative reasoning path wasn't "
                "available, so this is composed directly from the linked evidence rather than "
                "reasoned through in full. The evidence and its limits are accurate; the "
                "explanation is thinner than it would otherwise be"
            )
        )

    return ComposedAnswer(
        text="\n\n".join(paragraph for paragraph in paragraphs if paragraph),
        structure=structure,
    )
