# CALYX Production Certification Operator Runbook

This runbook covers the only next production action after the authenticated, read-only eligible-ledger discovery workflow. Discovery performs no graph mutation and invokes no publication endpoint. Do not invent or substitute a ledger ID, version, or review hash.

## Run discovery

Manually dispatch **CALYX Eligible Ledger Discovery** on `main`. Download `calyx-eligible-ledger-discovery-<run-id>` and verify the artifact hash, `read_only: true`, `production_mutation: false`, and `publication_endpoint_invoked: false` before selecting an outcome below.

## A. `ELIGIBLE_LEDGER_FOUND`

Confirm the selected artifact entry contains a non-empty `ledger_id`, positive `version`, and 64-character `review_content_hash`. A human owner must then manually dispatch **CALYX Supervised Production Demonstration** on `main` exactly once with those three values unchanged, confirmation `PUBLISH ONE REVIEWED LEDGER`, and an operator-reviewed publication note. Monitor the run and retain its evidence artifact. This explicit dispatch is the only remaining supervised publication demonstration; do not enable schedules, retries, autonomous dispatch, or any alternate publication call.

## B. `NO_ELIGIBLE_LEDGER`

Stop. Do not dispatch the supervised production demonstration and do not fabricate values. A human reviewer must complete and approve an actual Reasoning Ledger revision through the existing governance process. After that approval exists, a human owner reruns **CALYX Eligible Ledger Discovery** and follows outcome A only if the deployed backend returns `ELIGIBLE_LEDGER_FOUND` with the exact current values.

## Deployment readiness boundary

Pull-request CI can prove the discovery route contract, authentication boundary, read-only SQL, response fields, no-eligible result, and absence of publication calls without production deployment or publication. A post-merge manual discovery dispatch is still required to prove the deployed backend has the merged contract. Only outcome A authorizes a separate, explicit human decision to perform the single supervised demonstration.
