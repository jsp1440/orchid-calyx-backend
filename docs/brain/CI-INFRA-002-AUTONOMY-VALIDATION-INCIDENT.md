# CI-INFRA-002 — Autonomy validation incident

GitHub Actions is currently terminating selected same-repository PR jobs before checkout with `steps=null`. Affected exact heads include BUILD-BRAIN-114N current-main PR #687 and authoritative BUILD-BRAIN-114O replacement PR #689. These runs provide no compile, lint, test, or diff-hygiene verdict and must not be counted as application failures or successful validation.

## Zero-dependency isolation proof

Temporary diagnostic PR #690 tested the hosted-runner boundary without repository/runtime dependencies. Its workflow used `ubuntu-latest` and exactly one shell step:

`run: echo "runner-step-executed"`

It used no `actions/checkout`, no `actions/setup-python`, no Python, no PostgreSQL, no repository code, and no third-party action. Run `31283413535`, job `93168245025`, still failed before step 1 and the job API returned `steps=null`.

This rules out repository code, Python/PostgreSQL startup, and allowed-actions policy for checkout/setup as the immediate cause. The remaining failure boundary is hosted-runner/job allocation or repository/account/organization policy before workflow steps are materialized. PR #690 was closed unmerged after evidence capture.

Authoritative handling:

- keep affected autonomy PRs draft;
- continue only non-mutating engineering work that can be structurally reviewed;
- do not merge or activate new authority-bearing layers without an executable exact-head run;
- record pre-step failures in canonical repository CI issue #481;
- resume ordinary fix/validate progression when runners execute real steps.

Former issue #685 is closed as a duplicate of #481 so the repository has one CI control-plane incident.

The incident does not change permanent autonomy boundaries: no autonomous merge, deployment, scientific publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation.
