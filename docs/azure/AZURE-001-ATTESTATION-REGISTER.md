# AZURE-001 Canonical Attestation Register

## Purpose

External readiness gates are accumulated in one deterministic JSON register rather than passed as transient booleans. The register manager validates every candidate update through the canonical attestation evaluator before atomically replacing the register.

## Commands

```bash
python -m runtime.taxonomy_preflight_attestation_register init evidence/gate-register.json
python -m runtime.taxonomy_preflight_attestation_register upsert evidence/gate-register.json evidence/ci-attestation.json
python -m runtime.taxonomy_preflight_attestation_register upsert evidence/gate-register.json evidence/ci-attestation-v2.json --replace
python -m runtime.taxonomy_preflight_attestation_register evaluate evidence/gate-register.json
```

## Operational rules

- One attestation per readiness gate.
- Replacement is rejected unless `--replace` is explicit.
- Entries are sorted deterministically by gate.
- Updates are written atomically.
- Unknown fields, malformed metadata, duplicate gates, future timestamps, invalid digests, and unsupported schema versions fail closed.
- A partially populated register is valid structurally but evaluates as not ready.
- The register never authorizes Azure provisioning, taxonomy publication, database mutation, or production migration.

## Evidence intake sequence

1. Capture the source evidence outside the repository when it contains sensitive identifiers.
2. Compute the source SHA-256 digest.
3. Create a narrowly scoped attestation containing only the minimum metadata required for the gate.
4. Upsert it into the register.
5. Run the canonical evaluator and readiness pipeline.
6. Retain the register, evaluator output, and source evidence under the applicable retention policy.

## Current boundary

The exact WorldOrchids 26-08 file was searched for in the current conversation and file library but was not located. No real-dataset attestation has therefore been created. Billing, budget-alert, and Microsoft-review attestations likewise require durable source evidence rather than reconstructed claims.
