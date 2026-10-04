# Orchid Continuum Homeostasis v1

Orchid Continuum is governed as a self-regulating scientific system, not a collection of independent modules or GitHub tasks.

- GitHub is the governed genome.
- Neon/PostgreSQL is living scientific memory and durable system state.
- Render workers, queues, schedulers, leases and budgets are metabolism.
- Federation adapters, cache/provenance/licensing/rate-limit controls and provider gates are the selectively permeable membrane.
- Brain/Calyx is the nervous and executive layer.

## Homeostatic loop
1. Observe authoritative vital signs.
2. Compare them with explicit target ranges and freshness requirements.
3. Diagnose drift without inventing evidence.
4. Reuse local, cached or already-acquired evidence first.
5. Piggyback acquisitions across modules.
6. Use free or already-authorized federation before paid retrieval.
7. Request bounded external intelligence through the existing provider governor.
8. Request owner budget only above current authorization.
9. Execute only through existing authoritative schedulers/executors.
10. Verify outcome, persist provenance/receipts, and re-observe.

## Neon rule
The production database should increasingly answer: what does Orchid Continuum know, what work is pending, what is stale, and what is unhealthy?

Before adding overlapping tables, perform a read-only inventory of existing Neon schemas and map harvested data to canonical responsibilities.

## Existing machinery retained
The provider-intent reservoir, budget governor, shared Firecrawl cache/ledger, persisted scheduler and budget-denial routing remain authoritative. Homeostasis supplies reason and urgency; existing governors decide admission and execution.

## First implementation
The initial policy engine is intentionally provider-free and side-effect-free. Neon observation adapters, Mission Control display and scheduler integration follow after the production database inventory.
