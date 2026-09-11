"""CALYX-EVOLVE-001: a bounded, staging-only experiment loop for taxonomy curation.

The package implements LEARN -> DESIGN -> EXPERIMENT -> ANALYZE -> REMEMBER over a
locked taxonomy-reconciliation fixture.  It has no activation, publication, or
production-mutation capability by construction, and none may be added here: any
promotion is a proposal for human scientific review.

Architectural adaptation of the published ASI-Evolve pattern
(arXiv:2603.29640; reference implementation GAIR-NLP/ASI-Evolve, Apache-2.0).
No upstream code is copied or vendored.
"""

from __future__ import annotations

__all__ = [
    "analysis",
    "campaign",
    "candidates",
    "cognition",
    "defaults",
    "fixture",
    "governance",
    "memory",
    "metrics",
    "provenance",
    "reconciler",
    "redaction",
    "safety",
    "sandbox",
    "selection",
    "status",
]
