"""Canonical taxon resolution for a scientific question.

Resolution reads the World Plants ``CanonicalRegistry`` (BUILD-065) and never
guesses: a name the registry does not hold is ``UNRESOLVED``; names that bind
to more than one accepted taxon are ``AMBIGUOUS``; a synonym is resolved to its
accepted taxon and the synonym hop is recorded rather than hidden.
"""

from __future__ import annotations

import re

from runtime.knowledge_graph.canonical_taxonomy import (
    CANONICAL_AUTHORITY,
    SYNONYM,
    CanonicalRegistry,
    canonical_name_of,
)

from .contracts import MAX_TAXA_PER_QUESTION, ResolutionState, TaxonResolution

#: Capitalised genus followed by a lower-case epithet (optionally with an
#: infraspecific rank).  Detection only: identity comes from the registry.
_BINOMIAL = re.compile(
    r"\b([A-Z][a-z]+(?:\s+(?:x|×)\s*)?\s+[a-z][a-z-]+"
    r"(?:\s+(?:subsp\.|var\.|f\.)\s+[a-z][a-z-]+)?)\b"
)


#: Capitalised question and command words that the binomial pattern would
#: otherwise read as a genus ("Which pollinators", "Describe the").
_NON_GENUS_WORDS = frozenset(
    {
        "Are", "Can", "Compare", "Could", "Describe", "Did", "Do", "Does", "Explain",
        "Give", "How", "In", "Is", "List", "On", "Please", "Should", "Show", "Summarize",
        "Tell", "The", "What", "When", "Where", "Which", "Who", "Why", "Would",
    }
)


def mentioned_names(text: str) -> tuple[str, ...]:
    seen: list[str] = []
    for match in _BINOMIAL.finditer(text):
        name = " ".join(match.group(1).split())
        if name.split()[0] in _NON_GENUS_WORDS:
            continue
        if name not in seen:
            seen.append(name)
    return tuple(seen)


def resolve_question_taxon(text: str, registry: CanonicalRegistry) -> TaxonResolution:
    names = mentioned_names(text)
    release = registry.canonical_release.to_dict() if registry.canonical_release else None
    candidates: list[dict] = []
    for name in names:
        cid = registry.name_index.get(canonical_name_of(name))
        taxon = registry.taxa.get(cid) if cid is not None else None
        if taxon is None:
            continue
        accepted = taxon
        if taxon.status == SYNONYM:
            accepted = registry.taxa.get(taxon.accepted_canonical_id or -1)
            if accepted is None:
                continue
        candidates.append(
            {
                "mentioned_name": name,
                "matched_status": taxon.status,
                "accepted_canonical_id": accepted.canonical_id,
                "accepted_name": accepted.canonical_name,
            }
        )

    accepted_ids = {c["accepted_canonical_id"] for c in candidates}
    common = {
        "mentioned_names": names,
        "candidates": tuple(candidates),
        "authority": CANONICAL_AUTHORITY,
        "release": release,
    }
    if not accepted_ids:
        return TaxonResolution(state=ResolutionState.UNRESOLVED, **common)
    # A taxon-like mention the registry cannot resolve, beside one it can,
    # must not be dropped: answering for the known taxon alone would silently
    # change the question.
    unresolved_mentions = len(names) > len(candidates)
    if len(accepted_ids) > 1 or unresolved_mentions or len(candidates) > MAX_TAXA_PER_QUESTION:
        return TaxonResolution(state=ResolutionState.AMBIGUOUS, **common)
    chosen = candidates[0]
    synonym = next(
        (c["mentioned_name"] for c in candidates if c["matched_status"] == SYNONYM),
        None,
    )
    return TaxonResolution(
        state=(
            ResolutionState.RESOLVED_VIA_SYNONYM
            if synonym
            else ResolutionState.RESOLVED_ACCEPTED
        ),
        accepted_canonical_id=chosen["accepted_canonical_id"],
        accepted_name=chosen["accepted_name"],
        via_synonym=synonym,
        **common,
    )
