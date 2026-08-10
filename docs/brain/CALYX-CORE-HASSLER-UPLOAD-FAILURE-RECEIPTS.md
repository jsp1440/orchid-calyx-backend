# CALYX CORE — Hassler upload mutation-failure receipts

Date: 2026-08-08
Issue: #386
PR: #734

## Defect found by static production-safety audit

The guarded Hassler client already failed closed before mutation and verified immutable readback after a successful upload. However, the original current-main implementation had an auditability gap after the production POST was issued: if the POST succeeded but readback/readiness verification later failed, `execute_upload()` raised before `main()` wrote the local receipt. A production database mutation could therefore have occurred while the operator retained no hash-bound local mutation record.

A transport or HTTP failure during the upload request was also ambiguous: the client could not know whether the server committed before the response failed, but the prior exception path preserved no explicit `unknown` mutation state.

## Corrected contract

The guarded client now records a three-state mutation outcome:

- `NONE` — no upload request was issued / exact durable replay was a no-op;
- `CONFIRMED` — the upload response passed exact immutable release-identity validation;
- `UNKNOWN` — the upload request was issued but a transport/HTTP/response-validation failure prevents proving whether the mutation committed.

Receipt schema version is `1.2`.

After the upload request is issued, verification failures no longer disappear as bare exceptions:

- confirmed upload followed by failed readback/readiness returns `MUTATED_VERIFICATION_FAILED`, `production_mutation=true`, `mutation_state=CONFIRMED`, `readback_verified=false`;
- upload request with indeterminate outcome returns `UPLOAD_RESULT_UNKNOWN`, `production_mutation=null`, `mutation_state=UNKNOWN`, `readback_verified=false`.

Both failure receipts contain the exact source identity, non-authority flags, sanitized exception class/message, and a SHA-256 `artifact_hash`. The CLI writes the receipt before exiting non-zero for either failure state.

Failures before the POST remain exceptions because no production mutation has been invoked.

## Regression coverage

`tests/test_upload_hassler_release_guarded_failure_receipts.py` proves:

1. a successful exact upload response followed by a 503 readback produces a `MUTATED_VERIFICATION_FAILED` receipt instead of losing evidence;
2. a 503 upload response produces `UPLOAD_RESULT_UNKNOWN` rather than falsely asserting that no mutation occurred;
3. both receipts are hash-bound and preserve the permanent no-staging/no-activation/no-KG-mutation boundaries.

## Governance

This correction does not authorize the production upload. It makes a future explicitly authorized mutation more auditable and safer to recover from. No live request, production database mutation, taxonomy staging, taxonomy activation, publication, deployment, or Knowledge Graph mutation was performed while implementing this correction.

Executable exact-head validation remains required. A hosted-runner job with `steps=null` is infrastructure evidence only and does not validate this code.
