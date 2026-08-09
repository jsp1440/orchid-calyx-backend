# BUILD-619-R3 — Scope-aware Reasoning Map on canonical BUILD-618

## Status

IMPLEMENTED / EXACT-HEAD VALIDATION REQUIRED.

This reconstruction starts directly from canonical main after BUILD-618-R4 merged as `6daef86a171f962604cc84f72ec26c19169bbf57`. Historical BUILD-619-R2 PR #788 remains behavioral source material only and is not integration authority because its BUILD-618 parent is superseded.

## Contract

`POST /brain/reasoning-map/scoped` remains owner-protected and read-only. It evaluates the existing deterministic Reasoning Map against an explicit BUILD-618 causal applicability scope without changing traversal semantics or manufacturing causal edges.

Each causal edge and returned pathway is labeled `applicable`, `out_of_scope`, or `indeterminate`. Unknown claim scope is never treated as applicable. Missing required query dimensions remain indeterminate. Out-of-scope pathways remain visible for transparency. An empty map is never marked safe to generalize.

The evaluator consumes the canonical BUILD-618 normalized scope contract, including semantic-empty mapping rejection and normalized categorical mapping identity.

## Scientific and governance boundaries

Scope evaluation is explanatory context only. It does not prove causality, resolve contradictions, approve or publish Candidate Knowledge, mutate the canonical Knowledge Graph, write production data, activate taxonomy, or deploy services.

Canonical reasoning remains distinct from later local plant observations; no co-occurrence or similarity is converted into causal evidence.

## Validation

Dedicated BUILD-619 validation compiles, lints, format-checks, and tests the scoped reasoning surfaces; runs canonical BUILD-618 and BUILD-612 prerequisite regressions; verifies the protected scoped route; and checks hygiene. Applicable Workflow Governance, Canonical Brain, Calyx Brain Integration, Brain E2E, and related Calyx agent checks must pass on the unchanged exact head before merge.

## Child dependency

After this build is canonical, BUILD-620-R2 must be synchronized/reconstructed onto the BUILD-619 merge and revalidated. Historical BUILD-620 validation cannot be reused as merge proof after its parent changes.
