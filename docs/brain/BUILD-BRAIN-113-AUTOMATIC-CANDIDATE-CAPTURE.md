# BUILD-BRAIN-113 — Automatic Brain Candidate Capture

## Status

Implemented as an atomic candidate-capture contract. Not merged, deployed, published, or connected to the production Knowledge Graph.

## Delivered

- reviewed artifact-to-Brain candidate transformation;
- build, validation, artifact, dependency, risk, and decision record classes;
- source artifact IDs, source paths, source checksums, record checksums, and bundle checksums;
- atomic bundle validation before mutation;
- exact replay idempotency and immutable conflict rejection;
- Mission Control capture-status projection;
- rollback for candidate bundles;
- repeatability, conflict, checksum, review-gate, and rollback tests.

## Validation repairs

The first registered focused run reached compilation successfully and identified only Ruff findings. The stack was corrected to use `TypeError` for invalid decoded evidence types and to apply deterministic import formatting. A bundle replay-order defect found during manual review was also repaired so bundle conflicts produce the authoritative bundle-conflict code before record-level validation.

## Governance boundary

Only release-eligible reviewed artifacts can be captured. Captured records remain candidates. Capture does not accept scientific claims, publish knowledge, activate taxonomy, mutate the Knowledge Graph, merge code, or deploy services.
