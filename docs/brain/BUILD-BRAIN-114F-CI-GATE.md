# BUILD-BRAIN-114F — CI gate

This branch is intentionally draft-only until GitHub Actions executes real steps against the current-main-derived consolidation surface.

Required checks:

- compile the complete `app/calyx_orchestrator` package;
- Ruff the autonomy executor and regression surface;
- run focused BUILD-BRAIN-114A/114B/114C/114D regressions;
- enforce diff hygiene.

A failed job with executable steps is treated as a code defect and must be corrected before expansion. A zero-step job is treated as infrastructure evidence and must not be represented as a code failure.

No merge, deploy, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation is authorized by this gate.
