# CI-INFRA-002 — Autonomy validation incident

GitHub Actions is currently terminating selected same-repository PR jobs before checkout with `steps=null`. Affected exact heads include BUILD-BRAIN-114N current-main PR #687 and the superseded 114O precursor. These runs provide no compile, lint, test, or diff-hygiene verdict and must not be counted as application failures or successful validation.

Authoritative handling:

- keep affected autonomy PRs draft;
- continue only non-mutating engineering work that can be structurally reviewed;
- do not merge or activate new authority-bearing layers without an executable exact-head run;
- record every pre-step failure in issue #685;
- resume ordinary fix/validate progression when runners execute real steps.

The incident does not change permanent autonomy boundaries: no autonomous merge, deployment, scientific publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation.
