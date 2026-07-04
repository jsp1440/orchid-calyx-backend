# BUILD-012A Smoke Test

After Render deploys this branch:

1. Confirm `/api/runner/health` returns `mode: build_012a_autonomous_runtime_engine`.
2. Confirm `/api/runner/autonomous-status` loads.
3. Leave `OC_RUNNER_AUTOLOOP=false` for the first deploy and manually run `/api/runner/autonomous-cycle` once.
4. Confirm `/api/runner/summary` still returns modules, jobs, actions, and runtime engine state.
5. Set `OC_RUNNER_AUTOLOOP=true` only after the manual cycle behaves correctly.
6. Confirm `cycle_count` increases over time and recent pending jobs drain without manual `execute-next` calls.
