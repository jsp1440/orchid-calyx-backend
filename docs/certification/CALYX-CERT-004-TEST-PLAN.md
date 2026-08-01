# CALYX-CERT-004 live retest plan

1. Merge and deploy this accounting fix only after CI passes.
2. Keep disposable PR #220 draft and unmerged.
3. Confirm its failing workflow has completed.
4. Run one governed repair attempt against branch `calyx/certification-2026-08-01b` and the single disposable test file.
5. Require all of the following before certification passes:
   - `repair_outcome` is `repair_committed`;
   - `repair_applied` is `true`;
   - `commits` is greater than zero;
   - PR #220 head SHA advances;
   - exactly the intended test file changes;
   - follow-up CI passes;
   - no merge or deployment occurs.

Do not repeat the live repair if the attempt fails. Inspect the returned status and branch diff first.
