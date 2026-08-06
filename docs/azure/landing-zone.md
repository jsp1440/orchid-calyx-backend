# Orchid Continuum Azure Landing Zone

Status: **specification only — no production provisioning authorized**
Date: 2026-08-06

## Purpose

Create a small, reversible Azure foundation for bounded Orchid Continuum pilots while Render and Neon remain authoritative production infrastructure.

## Subscription and cost boundary

- Subscription: Five Cities Orchid Society Azure nonprofit subscription (final display name TBD).
- Annual sponsorship: USD 2,000.
- Design target: steady Azure run rate no greater than USD 125–140/month.
- First taxonomy pilot incremental target: no greater than USD 25/month.
- No reservation, savings-plan, AKS, GPU, or always-on high-tier database commitment during the pilot.

## Regions

- Preferred: `westus2`, subject to service availability and Microsoft review.
- Fallback: `westus3` or another U.S. region selected only after data-residency, service-availability, and pricing review.
- Keep pilot resources in one region unless a service requires otherwise.

## Resource groups

| Resource group | Purpose | Initial authorization |
|---|---|---|
| `rg-oc-platform-dev-westus2` | shared non-production platform controls | specification / low-cost pilot only |
| `rg-oc-taxonomy-pilot-westus2` | taxonomy preflight job and candidate artifacts | first approved pilot |
| `rg-oc-observability-dev-westus2` | logs, metrics, alerts | minimal retention only |
| `rg-oc-data-pilot-westus2` | future database benchmark | HOLD |
| `rg-oc-ai-pilot-westus2` | future Document Intelligence / Foundry tests | HOLD |

## Required tags

Every resource must include:

```text
project=orchid-continuum
environment=dev|test|prod
owner=five-cities-orchid-society
cost-center=azure-nonprofit-credit
data-classification=public|internal|sensitive|restricted
managed-by=iac|portal-exception
workload=<bounded-workload-name>
expiry-review=YYYY-MM-DD
```

Resources without these tags fail the deployment review.

## Identity and secrets

1. GitHub Actions must authenticate with workload identity federation/OIDC, not a stored Azure client secret.
2. Azure workloads use managed identities where supported.
3. Secrets belong in Key Vault; they must not be committed, emitted in logs, or passed as ordinary command-line arguments.
4. Human access uses least-privilege Azure RBAC. Subscription Owner is not the routine deployment role.
5. Production access and public-user identity are separate future design decisions.

## Taxonomy pilot topology

```text
Operator / GitHub workflow
        |
        v
candidate CSV -> private Blob container (planned adapter)
        |
        v
Azure Container Apps Job (scale to zero / run on demand)
        |
        +--> JSON preflight report
        +--> Markdown human summary
        +--> logs/metrics with short retention

No database write. No publication. No automatic replacement of the approved taxonomy.
```

The validator must remain runnable locally and in CI without Azure.

## Observability baseline

- Correlation/run identifier for each validation.
- Log source checksum, validator version, row counts, status, and duration.
- Never log file contents or secrets.
- Application Insights / Log Analytics retention set to the shortest practical period for the pilot.
- Alert on repeated failures, job execution errors, and abnormal cost growth.

## Deployment gates

### Gate 0 — code only
- Local validator and tests complete.
- No Azure resource creation.

### Gate 1 — plan/dry run
- Billing-credit linkage verified.
- Budget and alerts configured.
- IaC plan reviewed with projected monthly cost.
- No production data.

### Gate 2 — bounded pilot
- Private candidate file only.
- On-demand execution.
- No database mutation or publication path.
- Removal procedure tested.

### Gate 3 — evaluation
- Compare correctness, operator usability, runtime, reliability, and cost.
- Explicit go/no-go before any expansion.

## Explicitly prohibited during this phase

- Production cutover.
- Render or Neon decommissioning.
- Public Blob containers.
- AKS.
- Third-party Marketplace purchases.
- Large image-corpus migration.
- PostgreSQL production migration.
- Autonomous taxonomy publication.
- Unbounded AI or agent loops.
