# KERNEL-001 — Scientific Object Framework

KERNEL-001 establishes the first enforceable contracts of the Orchid Continuum Scientific Kernel.

## Implemented contracts

- `ScientificObject`: immutable base model for durable scientific objects.
- `OCID`: parseable permanent identifier in the form `OC:<KIND>:<UUIDHEX>`.
- `OCIDFactory`: UUID-based identifier generation.
- Kernel exception hierarchy.
- Abstract service interfaces for Evidence, Assertions, and Relationships.

## Invariants

1. Scientific objects are immutable after construction.
2. Every object has a globally unique OCID.
3. Creation timestamps are timezone-aware and normalized to UTC.
4. Metadata is exposed as a read-only mapping.
5. Specialized object types must use specialized OCID kinds.

## Validation

Run:

```bash
python -m pytest -q tests/kernel/test_foundation.py
```

This milestone defines contracts only. Persistence engines and domain-specific Evidence, Assertion, and Relationship models are intentionally deferred to subsequent Kernel milestones.
