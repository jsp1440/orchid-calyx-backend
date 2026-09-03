"""Continuum Engineering Memory v1.

A repository-scoped, non-scientific engineering memory layer for coding agents
(Claude, Codex, Gemini, GitHub agents).  It captures sanitized run outcomes,
derives verified lessons, retrieves relevant verified memory via lexical
search, records feedback, and measures usage/savings telemetry.

Engineering memory is explicitly ``non_scientific_evidence`` and must never be
presented as scientific evidence, provenance, or authoritative fact.  Secrets
and protected locality are redacted before persistence, writes fail closed on
malformed classification/provenance/redaction, and every read/write is scoped
to a single workspace.
"""

from __future__ import annotations

from .models import (
    DATA_CLASSIFICATIONS,
    EVIDENCE_CLASS_NON_SCIENTIFIC,
    LESSON_STATUSES,
    EngineeringMemoryLesson,
    EngineeringMemoryRetrieval,
    EngineeringMemoryRun,
)

__all__ = [
    "DATA_CLASSIFICATIONS",
    "EVIDENCE_CLASS_NON_SCIENTIFIC",
    "LESSON_STATUSES",
    "EngineeringMemoryLesson",
    "EngineeringMemoryRetrieval",
    "EngineeringMemoryRun",
]
