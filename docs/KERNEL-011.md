# KERNEL-011 — Scientific Integrity and Audit Engine

KERNEL-011 introduces immutable integrity findings and audit records for validating Orchid Continuum Scientific Kernel objects.

## Purpose

Scientific objects need cross-object integrity checks, audit trails, blocking findings, and repeatable validation runs without coupling the domain model to a specific persistence or rule engine.

## Contract

`IntegrityFinding` records a stable rule identifier, severity, message, optional affected object and field, and immutable details.

`IntegrityAudit` records an `EVENT` OCID, unique target OCIDs, lifecycle status, requester attribution, UTC-normalized timestamps, immutable findings, and read-only metadata.

## Validation invariants

- Audits require at least one unique target OCID.
- Running audits require `started_at`.
- Terminal audits require `started_at` and `completed_at`.
- Start cannot precede creation; completion cannot precede start.
- Passed audits cannot contain error or critical findings.
- Failed audits require an error or critical finding.
- Finding identifiers and messages cannot be empty.

## Service boundary

`IntegrityAuditService` defines audit execution, retrieval, object-centric listing, and cancellation.

## Validation

```bash
python -m pytest -q \
  tests/kernel/test_foundation.py \
  tests/kernel/test_evidence.py \
  tests/kernel/test_assertions.py \
  tests/kernel/test_relationships.py \
  tests/kernel/test_publications.py \
  tests/kernel/test_queries.py \
  tests/kernel/test_knowledge.py \
  tests/kernel/test_events.py \
  tests/kernel/test_runtime.py \
  tests/kernel/test_governance.py \
  tests/kernel/test_integrity.py
```
