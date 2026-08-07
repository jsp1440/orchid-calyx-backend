# PR #515 — Authoritative Validation Receipt

## Validated code head

`8aecc58a2ebcbf0fba4646f6ab66c3d0b250b689`

## Purpose

Validate the integration bridge from the constitution-gated Canonical Brain build queue into the repository's existing `app/calyx_orchestrator/scheduler.py` dependency scheduler.

## GitHub Actions evidence

Canonical Brain Validation run `31148881627` completed successfully.

- compile: success
- Ruff: success
- focused pytest: success

The first run found one Ruff modernization defect (`FURB188`) in architecture-key normalization. It was corrected with `str.removeprefix()` before the successful run.

## Validated integration behavior

- constitutionally blocked builds remain non-runnable after projection;
- admitted, scheduled, running, completed, and cancelled queue states map deterministically into the existing scheduler model;
- completed prerequisites release downstream jobs through the existing dependency scheduler;
- Brain queue priority is preserved;
- `architecture:<name>` identifiers normalize to existing scheduler architecture keys;
- missing metadata fails closed;
- orphaned metadata fails closed;
- duplicate metadata identities fail closed;
- the existing mutating-branch serialization guard remains effective;
- existing critical-path and capacity logic remains authoritative rather than being reimplemented in the Brain.

## Architecture decision

Do not maintain a second dependency scheduler inside Canonical Brain. Canonical Brain owns admission, governance, queue identity, and evidence boundaries. `calyx_orchestrator.scheduler.DependencyScheduler` owns deterministic dependency/capacity projection. The bridge is the governed translation boundary between them.

## Safety boundary

The bridge is read-only projection logic. It does not change queue state, assign or launch agents, execute code, access credentials, merge, deploy, publish, write production data, or mutate the production Knowledge Graph.

## Disposition

PR #515 remains draft and unmerged. Its validation gate is satisfied. This integration base is suitable for the next governed control-plane slice without duplicating scheduler functionality.
