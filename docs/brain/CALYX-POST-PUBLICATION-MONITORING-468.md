# CALYX-468 — Post-publication monitoring and evidence-change review tasks

Status: IMPLEMENTED / VALIDATED / GOVERNED REVIEW-ONLY

## Delivered

- Immutable published-assertion baseline linking publication ID, assertion ID, Reasoning Ledger ID/revision/hash, publication/approval timestamps, approval TTL, confidence, and exact evidence/source hashes.
- Later evidence observations preserve observation history rather than overwriting the published baseline.
- Deterministic detection of evidence-hash changes, source-hash changes, supersession, withdrawal, retraction, stale approval, and confidence changes.
- Idempotent review-task generation keyed to publication, reason, evidence identity, and observed fingerprint.
- Explicit distinction between superseded, withdrawn, and retracted evidence.
- Monitoring status exposes last observation, observation count, review-task count, monitoring lag, and review/current decision.
- Unknown evidence identities fail closed rather than being silently attached to a publication.
- Protected Mission Control register/read/observe/task/status APIs plus deterministic fixture/API tests.

## Integration model

CALYX-468 accepts evidence-state observations from governed source monitors and ties them back to the immutable publication/ledger/evidence identity that was actually published. The monitor does not itself fetch external sources or modify the publication. Review tasks are human-review requests only.

This provides the post-publication half of the scientific lifecycle: a previously approved assertion can remain historically intact while new evidence, source changes, retractions, or confidence shifts trigger a new review decision.

## Governance boundaries

No automatic republication, production Knowledge Graph rewrite, scientific approval, source acquisition, deployment, or merge authority exists in this slice. Historical publication records remain immutable; review tasks never imply that the original assertion has been invalidated or replaced until governed review occurs.

## Validation

Initial implementation validation exposed one repository-wide integration failure: Ruff required the new Mission Control router import to be multiline-formatted. That failure was corrected before expansion.

Corrected implementation commit `ed1e647a205d3c78dfb5933ed495b9eed2bde422` then passed all available gates:

- CALYX Post Publication Monitoring 468: success; compile, 8 deterministic monitoring/API tests, permanent governance assertions, Ruff, and diff hygiene all passed.
- CALYX Workflow Governance Audit: success.
- CALYX-AUTONOMY-DEPLOYMENT-001: success after the import-format correction.
- CALYX-SUPERVISED-PILOT-001: success after the same correction.
- BUILD-088E publication pipeline operational readiness: success, including PostgreSQL readiness/regression validation.

PR #636 remains draft/unmerged. This documentation-only validation-record commit remains subject to the same PR checks.
