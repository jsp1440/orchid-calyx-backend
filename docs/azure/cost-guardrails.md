# Azure Cost Guardrails

## Financial boundary

- Sponsorship period: 2026-08-06 through 2027-08-04.
- Original credit: USD 2,000.
- Working average: USD 166.67/month.
- Preferred steady-state envelope: USD 125–140/month.
- Initial taxonomy pilot ceiling: USD 25/month incremental.

Budgets are alerts, not hard spending caps. Every workload must therefore also have architectural limits and a removal procedure.

## Required alerts

At subscription scope, configure actual-cost alerts at:

- USD 25/month — pilot review
- USD 75/month — architecture review
- USD 125/month — spending freeze on new resources
- USD 150/month — incident-level investigation

Also configure forecast alerts at USD 125 and USD 150/month, plus annual credit-consumption checkpoints at 25%, 50%, 75%, and 90%.

## Pilot constraints

- Run Container Apps Jobs on demand; no always-on replica requirement.
- Scale-to-zero wherever supported.
- Use private, minimal Blob storage for candidate files and reports only.
- Keep log retention short and cap verbose diagnostics.
- No database server for the taxonomy pilot.
- No AI model invocation for deterministic CSV validation.
- No egress-heavy image or dataset migration.

## Cost review template

Every Azure pull request or provisioning request must state:

1. service and SKU;
2. region;
3. minimum and maximum scale;
4. expected executions/transactions per month;
5. storage and retention;
6. expected egress;
7. estimated monthly low/expected/high cost;
8. shutdown and deletion method;
9. accountable owner;
10. expiry/review date.

## Automatic stop conditions

Stop or remove the pilot if any of the following occurs:

- monthly forecast exceeds USD 25 for the taxonomy pilot;
- a public endpoint or public container is created unexpectedly;
- the workload cannot scale to zero as designed;
- secrets appear in code, workflow configuration, or logs;
- the validator mutates a database or publishes taxonomy data;
- Azure cost visibility is unavailable for more than seven days;
- Microsoft recommends a materially safer or cheaper implementation.

## Prohibited commitments

Do not purchase reservations, savings plans, support plans, Marketplace products, GPU capacity, AKS clusters, or high-availability database tiers during AZURE-001.
