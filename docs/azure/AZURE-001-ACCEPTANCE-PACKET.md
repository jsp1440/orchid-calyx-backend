# AZURE-001 Governed Acceptance Packet

## Purpose

The acceptance packet is the final evidence-consolidation layer before an owner or Microsoft engineering review. It does not provision Azure, publish taxonomy, mutate a database, merge code, or authorize production migration.

## Inputs

- a release-gate bundle that passes `verify_release_bundle`;
- readiness evidence produced by `taxonomy_preflight_readiness`;
- reproducibility evidence produced by `taxonomy_preflight_reproducibility`;
- the applicable release-gate policy.

## Decisions

- `BLOCK`: release evidence is missing, malformed, or unverifiable.
- `REVIEW_ONLY`: evidence is structurally valid but one or more readiness, identity, reproducibility, digest, or safety gates remain incomplete.
- `ACCEPTANCE_REVIEW_ONLY`: all supplied evidence is internally consistent and ready for human review. This still grants no operational authority.

## Safety invariants

Every packet fixes these values to `false`:

- `azure_provisioning_authorized`
- `taxonomy_publication_authorized`
- `database_mutation_authorized`
- `production_migration_authorized`

The packet rejects unsafe or missing authority flags in its source evidence.

## CI behavior

The current synthetic CI fixture deliberately leaves the real-dataset, billing, budget, and Microsoft-review gates incomplete. Therefore readiness must remain `HOLD` and acceptance must remain `REVIEW_ONLY`. A zero-exit acceptance is not expected until all external gates are backed by real evidence.

## Remaining external gates

1. GitHub Actions must register and pass.
2. The exact `WorldOrchids 26-08 (Aug 2 2026).csv` source must pass governed validation.
3. Azure nonprofit-credit linkage must be verified for the subscription and billing profile.
4. Subscription-level budgets and alerts must be configured.
5. Microsoft or the assigned partner must review the architecture.

No deployment work should cross those boundaries automatically.
