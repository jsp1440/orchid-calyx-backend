# Autonomous integration handoff

`oc-autonomous-integration` must produce a real, exact-head validation receipt after every push before downstream convergence is treated as healthy.

The active handoff is `.github/workflows/oc-integration-handoff.yml`.

It deliberately replaces the obsolete AGENT-007 one-shot dispatch/observer workflows, which were hard-coded to historical PR #1043 and could create zero-job red workflow records unrelated to current integration health.

The handoff:

1. checks out the exact integration head;
2. compiles backend sources;
3. validates the governed Relationship Matrix producer path and focused regressions;
4. records the exact SHA in the workflow summary;
5. dispatches the same-repository continuous-completion supervisor only after validation succeeds.

A workflow that receives no runner and executes no repository steps is not an integration-code failure and is not green validation. A downstream consumer must not advance on such a record.

This workflow does not merge to `main`, deploy, mutate production data, publish scientific state, activate taxonomy, or bypass owner gates.
