#!/usr/bin/env python3
"""Quick test of the evidence state resolution reasoning operation."""

from app.cognitive_integration.reasoning_operations import (
    evidence_state_weight,
    resolve_by_evidence_state,
)

# Test weight function
assert evidence_state_weight("SUPPORTED") == 4
assert evidence_state_weight("CONTESTED") == 2
assert evidence_state_weight("REPORTED_UNVERIFIED") == 1
assert evidence_state_weight("REFUTED") == 0
assert evidence_state_weight("UNKNOWN") == 0
print("✓ Weight function works")

# Test resolution with same scope and asymmetric evidence states
first = {
    "geographic_scope": "predominant throughout the range",
    "evidence_state": "SUPPORTED",
}
second = {
    "geographic_scope": "predominant throughout the range",
    "evidence_state": "CONTESTED",
}
result = resolve_by_evidence_state(first, second)
assert result == "resolved_by_evidence_state", f"Expected resolved_by_evidence_state, got {result}"
print("✓ Resolves SUPPORTED vs CONTESTED with same scope")

# Test with unresolved case (same evidence states)
first2 = {
    "geographic_scope": "predominant throughout the range",
    "evidence_state": "SUPPORTED",
}
second2 = {
    "geographic_scope": "predominant throughout the range",
    "evidence_state": "SUPPORTED",
}
result2 = resolve_by_evidence_state(first2, second2)
assert result2 == "unresolved_presented_as_contested", f"Expected unresolved, got {result2}"
print("✓ Stays unresolved when both SUPPORTED")

# Test with small weight difference (only 1 level)
first3 = {
    "geographic_scope": "predominant throughout the range",
    "evidence_state": "SUPPORTED",
}
second3 = {
    "geographic_scope": "predominant throughout the range",
    "evidence_state": "REPORTED_UNVERIFIED",
}
result3 = resolve_by_evidence_state(first3, second3)
# Weight diff is 4 - 1 = 3, which is >= 2, so should resolve
assert result3 == "resolved_by_evidence_state", f"Expected resolved, got {result3}"
print("✓ Resolves SUPPORTED vs REPORTED_UNVERIFIED (weight diff 3)")

# Test with different scopes
first4 = {
    "geographic_scope": "predominant throughout the range",
    "evidence_state": "SUPPORTED",
}
second4 = {
    "geographic_scope": "sporadically reported, chiefly in the Mediterranean",
    "evidence_state": "CONTESTED",
}
result4 = resolve_by_evidence_state(first4, second4)
assert result4 == "unresolved_presented_as_contested", f"Expected unresolved, got {result4}"
print("✓ Stays unresolved when scopes differ")

print("\n✓ All tests passed!")
