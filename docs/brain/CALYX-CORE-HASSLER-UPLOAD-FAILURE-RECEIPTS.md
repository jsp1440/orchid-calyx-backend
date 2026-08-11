# CALYX CORE — Hassler upload mutation-failure receipts

Date: 2026-08-11
Issue: #386
Current-main convergence: successor to historical #843/#861

## Corrected contract

The guarded Hassler client preserves a three-state mutation outcome: `NONE` when no upload request was issued, `CONFIRMED` when the exact durable upload response was validated, and `UNKNOWN` when a request was issued but the response cannot establish whether the server committed.

Receipt schema remains `1.2`. Confirmed upload followed by failed later verification returns `MUTATED_VERIFICATION_FAILED`; an indeterminate upload response returns `UPLOAD_RESULT_UNKNOWN`. Both carry exact source identity, permanent non-authority flags, a sanitized error, and a SHA-256 `artifact_hash`.

Current-main hardening additionally guarantees that the bytes sent are the exact bytes whose size and SHA-256 were validated, that the receipt destination is proven writable before any live request, and that successful immutable readback remains recorded as `readback_verified=true` even if a later readiness check fails.

The CLI writes receipts atomically. Failures before the upload POST remain exceptions because no production mutation has been invoked.

## Governance

No production upload was executed while implementing or validating this work. No taxonomy staging, taxonomy activation, publication, deployment, Knowledge Graph mutation, or credential action is authorized by this tooling.
