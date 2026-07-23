# KERNEL-002 — Evidence Engine

## Objective

Establish immutable, provenance-rich scientific evidence as the mandatory foundation for future assertions and relationships in the Orchid Continuum Scientific Kernel.

## Contracts

- `EvidenceType` defines canonical evidence categories.
- `Provenance` records source identity, retrieval time, acquisition method, collector, URL, and read-only metadata.
- `Evidence` extends `ScientificObject` with an `EVIDENCE` OCID, title, type, provenance, citation, content, and deterministic SHA-256 fingerprint.
- Evidence content and provenance metadata are immutable after construction.
- Equivalent evidence payloads produce the same fingerprint regardless of mapping key order.
- All timestamps must be timezone-aware and are normalized to UTC.

## Deferred

Persistence adapters, deduplication repositories, evidence supersession, and assertion linkage are intentionally deferred to later Kernel milestones.

## Validation

```bash
python -m pytest -q tests/kernel/test_foundation.py tests/kernel/test_evidence.py
```
