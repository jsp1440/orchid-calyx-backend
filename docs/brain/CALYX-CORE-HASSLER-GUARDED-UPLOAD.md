# CALYX CORE — Guarded Hassler production upload boundary

Date: 2026-08-11
Issue: #386
Current-main convergence: successor to historical #843/#861

## Status

IMPLEMENTED / EXACT-HEAD VALIDATION REQUIRED / PRODUCTION EXECUTION NOT AUTHORIZED.

The tooling is being converged onto current canonical main. This status does **not** authorize a production upload.

## Purpose

Prepare the exact production upload/readback operation for the real Hassler release without executing it. The client preserves the explicit owner governance boundary around the first production taxonomy write.

## Canonical source identity

`WorldOrchids 26-08 (Aug 2 2026).csv`

- size: `11,529,836` bytes
- SHA-256: `e5be9268e1a48cb0e1777137ac386a9a870f3581c35f10678c9b810c59688c6f`
- version label: `26-08`
- acquisition date: `2026-08-02`

## Guarded operator client

`scripts/upload_hassler_release_guarded.py` is fail closed and dry-run by default. A live upload requires `--execute`, exact source identity, owner-session credentials, backend URL, and confirmation token `UPLOAD_WORLD_ORCHIDS_26_08`.

Current-main hardening closes three production-safety gaps found during review:

1. **Validated-byte binding.** The client reads the source bytes once, validates exact filename/size/SHA-256, retains those exact bytes, and sends those same bytes if execution is later authorized. It no longer reopens the path after validation, eliminating the validation-to-upload TOCTOU window.
2. **Receipt-destination preflight.** The report destination is created/probed for writability before any live mutation can be attempted, and receipts are finalized atomically with fsync + replace.
3. **Truthful readback state.** Exact immutable readback is tracked independently from subsequent readiness checks, so a later readiness failure cannot erase evidence that durable readback already succeeded.

The client still performs immutable readback before mutation. Exact existing durable identity returns a no-op; only a genuine 404 plus upload readiness may proceed to the inspection POST. After an upload, exact durable readback is mandatory and the workflow stops at staging-smoke readiness.

The client never calls staging or activation and permanently reports `staging_invoked=false`, `taxonomy_activation_authorized=false`, `knowledge_graph_mutation_authorized=false`, and `automatic_promotion=false`.

## Mutation-truth receipts

Receipt schema `1.2` preserves three mutation states:

- `NONE`: no upload request was issued.
- `CONFIRMED`: the upload response confirmed the exact durable release identity.
- `UNKNOWN`: a request was issued but the response does not prove whether the mutation committed.

A confirmed mutation followed by a later verification failure returns `MUTATED_VERIFICATION_FAILED`. An indeterminate request returns `UPLOAD_RESULT_UNKNOWN`. Both are hash-bound and cause non-zero CLI exit.

## Validation target

Current-main validation covers compile, Ruff, guarded behavior tests, failure-receipt regressions, runtime dependency installation, and governance assertions that prohibit staging, taxonomy activation, publication, and Knowledge Graph mutation.

## Governance boundary

The first real production upload remains an owner-governed production database mutation. Engineering convergence, tests, and merge of the dry-run-default tooling do not authorize `--execute`. Production upload, bounded staging, taxonomy activation, canonical taxonomy mutation, Knowledge Graph mutation, scientific publication, deployment, and credential use remain separate governed actions.
