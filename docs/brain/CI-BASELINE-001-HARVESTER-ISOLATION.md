# CI-BASELINE-001 — BUILD-105 harvester isolation

## Demonstrated root cause

After the local CI PostgreSQL SSL and safety-schema repair, the BUILD-105 broad-suite failures remained but changed character: no SSL or missing `oc_admin.harvest_safety_state` error was involved. The failing tests installed fake modules only in `sys.modules`, while `harvesters.execution` imports child modules with `from harvesters import ...`. If another test imported a child module earlier, Python can reuse the cached attribute on the `harvesters` package even after `sys.modules` is replaced.

That allowed BUILD-105 tests to read prior/real harvester state (`0`, `32708`) instead of the intended fake checkpoints (`42`, `8`), and prevented the GBIF offset-window test from exercising its fake state.

## Repair

The BUILD-105 tests now install fake harvesters atomically in both locations used by Python import resolution:

- `sys.modules["harvesters.<module>"]`;
- the matching `harvesters.<module>` package attribute.

A shared `_install_fake_harvester` helper is used for iNaturalist, GBIF, TraitBank and the state helper, eliminating order-dependent module leakage across the full repository suite.

## Governance

This is test-isolation hardening only. It does not modify production harvester code, network behavior, work budgets, cursor limits, persistence, credentials, deployment, publication, taxonomy activation, or production Knowledge Graph mutation.

## Validation gate

The exact head must pass the focused BUILD-105 safety suite, Ruff and diff hygiene. Existing broad validation must then demonstrate that the three prior BUILD-105 failures are absent before this category is considered repaired.
