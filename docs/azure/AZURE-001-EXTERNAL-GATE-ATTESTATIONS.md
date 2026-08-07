# AZURE-001 External Gate Attestations

## Purpose

Readiness decisions must not depend solely on command-line boolean flags. External gates now use typed, checksummed attestations with explicit issuers, timestamps, scope, evidence identifiers, and gate-specific metadata.

## Required gates

1. `ci_validation`
2. `real_dataset_validation`
3. `billing_credit_linkage`
4. `budget_alerts`
5. `microsoft_architecture_review`

A register is complete only when every gate has one non-expired `verified` attestation. Duplicate, future-dated, malformed, unsupported, or incomplete attestations fail closed.

## Gate-specific evidence

- **CI validation:** repository, commit digest, and workflow-run identifier.
- **Real dataset:** exact source filename, source SHA-256, and validator run identifier.
- **Billing linkage:** subscription identifier, billing profile, and credit expiration timestamp.
- **Budget alerts:** configured percentage thresholds.
- **Architecture review:** review reference, reviewer organization, and accepted outcome.

## Safety boundary

A valid attestation register can advance AZURE-001 only to `READY_FOR_REVIEW`. It never authorizes:

- Azure resource creation;
- taxonomy publication;
- database mutation;
- production migration.

Those authorities remain false in every generated evaluation.

## Current state

GitHub Actions can create durable CI evidence. The exact August World Orchids source-file run, budget-alert configuration, and architecture-review evidence remain external work. Azure billing and nonprofit-credit linkage have been visually verified in the Azure portal, but a durable exported or checksummed evidence artifact should be registered before the gate is marked verified in the machine-readable readiness packet.
