# Orchid Calyx Backend — Coding Agent Instructions

This is the canonical Orchid Continuum backend and Calyx engineering runtime. The existing durable Calyx mission/orchestration substrate is canonical; do not create a competing master queue or orchestrator.

Before implementation:
1. Inspect current `main`.
2. Search open issues and PRs touching the same subsystem.
3. Search the Brain for the governing architecture/mission record.
4. Classify the mission as `NEW`, `CONTINUE`, `CONVERGE`, `SUPERSEDE`, or `ALREADY_DONE`.
5. Prefer extending existing `app/calyx_orchestrator`, canonical Brain, graph, publication, and governance components over parallel frameworks.

Engineering rules:
- Never fabricate service health, scientific evidence, provenance, test status, production state, or completion.
- Preserve evidence state, uncertainty, contradiction, provenance, and publication/activation gates.
- Keep external calls bounded and fail closed when a contract cannot be verified.
- Add focused tests for behavior changes.
- Run focused pytest/Ruff/compile checks first, then required CI appropriate to the changed surface.
- Distinguish CI/runner failure from code failure.
- Inspect existing PR lineage before creating a new branch; converge overlapping work where appropriate.
- Automatic repair is bounded: after three unsuccessful iterations on the same deterministic failure class, escalate rather than consuming more model budget.

Output:
- Default to a draft PR for implementation work.
- State mission classification and related/superseded PRs.
- Include exact validation evidence and remaining blockers.

Permanent authority boundaries:
Do not merge/auto-merge, deploy production, apply production migrations, mutate production DB/Knowledge Graph, activate taxonomy, publish scientific claims, expose/create privileged credentials, spend funds, force-push, or delete branches/repos without required owner authorization.
