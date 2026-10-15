"""Reasoning operations that resolve contradictions in the Cognitive Integration path.

These operations decide between conflicting evidence claims by applying
deterministic rules about evidence state, geographic scope, and support quality.
"""

from __future__ import annotations

from typing import Any


def evidence_state_weight(state: str) -> int:
    """Assign a weight to evidence states for decision-making.
    
    Higher weights indicate stronger support. Used to break ties when one
    claim is more strongly supported than another and the two cannot be
    resolved by geography alone.
    """
    return {
        "SUPPORTED": 4,
        "CONTESTED": 2,
        "REPORTED_UNVERIFIED": 1,
        "REFUTED": 0,
    }.get(state, 0)


def resolve_by_evidence_state(
    first: dict[str, Any], second: dict[str, Any]
) -> str:
    """Whether a disagreement can be resolved by evidence state weighting.
    
    When two incompatible claims apply to the same or overlapping ground
    (i.e., cannot be resolved by geography), and one is markedly stronger
    than the other, the stronger claim may be treated as the predominant
    answer with the weaker noted as an exception or variant.
    
    This operation implements the reasoning: when SUPPORTED evidence conflicts
    with CONTESTED or REPORTED_UNVERIFIED evidence for overlapping geographic
    scope, the SUPPORTED claim describes the predominant case and the weaker
    claim describes an exception or minority variant.
    
    Returns "resolved_by_evidence_state" only when the criteria are met,
    otherwise returns "unresolved_presented_as_contested".
    """
    first_scope = first.get("geographic_scope") or "unspecified"
    second_scope = second.get("geographic_scope") or "unspecified"
    
    # If scopes explicitly describe the same place, evidence state weighting applies
    if first_scope == second_scope:
        first_state = first.get("evidence_state")
        second_state = second.get("evidence_state")
        first_weight = evidence_state_weight(first_state)
        second_weight = evidence_state_weight(second_state)
        
        # Two or more levels of difference is a significant asymmetry
        weight_diff = abs(first_weight - second_weight)
        if weight_diff >= 2:
            # One claim is substantially better supported
            return "resolved_by_evidence_state"
    
    return "unresolved_presented_as_contested"
