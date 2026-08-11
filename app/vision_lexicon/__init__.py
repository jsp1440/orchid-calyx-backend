"""CALYX-VISION-LEXICON-BRIDGE-001

End-to-end bridge between Calyx Vision analysis, canonical Lexicon concepts,
Knowledge Graph relationships, Figure Specification / validation, and
frontend-readable evidence APIs.

Scientific safeguards enforced at the domain-model layer:
- Uncalibrated images cannot produce absolute physical measurements.
- Color phenotype class is strictly IMAGE_DERIVED for Vision-only evidence.
- Cannot-determine states are preserved, never silently dropped.
- Machine-generated assertions remain distinct from reviewed scientific knowledge.
- Community review cannot automatically promote to scientific truth.
- Duplicate analysis requests are idempotent (stable request_hash).
- Re-analysis with a new model version creates a new record; prior records
  are never overwritten.
"""
