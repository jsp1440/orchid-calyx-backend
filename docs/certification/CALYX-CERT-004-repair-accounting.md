# CALYX-CERT-004 — Repair accounting guarantee

A governed repair attempt must not be reported as applied unless the target pull request branch actually advances.

The repair endpoint now distinguishes:

- `repair_committed_waiting_for_ci`: at least one commit SHA was returned and the PR head SHA advanced.
- `repair_not_applied_no_failed_checks`: no failed workflow checks were available to justify a repair.
- `repair_not_applied_no_changes_generated`: the provider returned no bounded file changes.
- `repair_not_applied_branch_unchanged`: a write response was returned but the PR branch head did not advance.

The certification script derives a normalized `repair_outcome` of `repair_committed`, `repair_generated`, or `repair_not_applied`, and sets `repair_applied=true` only for a verified committed repair.

Safety properties remain unchanged: no autonomous merge and no deployment.
