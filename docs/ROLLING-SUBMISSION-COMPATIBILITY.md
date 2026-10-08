# Rolling-version submission compatibility

`GET /programs/submission-capabilities` requires existing owner/API-key
authentication and does not open a database. It reports wire support only:
`brain.verification_admission.v1` and `programs.idempotency.v1`.
It does not grant execution, provider, scientific or publication authority.
Existing program endpoints, request/response models and status codes are unchanged.
The static route precedes the dynamic program-ID route.

Brain's opt-in `calyx_brain.program_submission.submit_program` accepts existing
caller-owned transports: GET this endpoint and POST `/programs` to the same
authenticated Calyx target. Non-null admission/idempotency fields require their
corresponding capabilities; callers may explicitly require additional features.
Legacy requests needing none bypass discovery and retain their exact payload,
response and submission errors. Missing optional/null fields are not feature use.

For required features, unavailable/unauthorized/malformed discovery or missing
capabilities stops before POST with a compatibility error and missing-feature
identifiers. Never strip fields, downgrade, cache discovery across receivers,
retry the POST, or blanket-reject newer server versions supporting the features.
A receiving version change after preflight propagates its POST error unchanged.

Local evidence: 23 Calyx admission/build-queue/capability/HTTP-handoff tests
passed; 25 Brain compatibility/producer tests passed. Real producer/preflight/
HTTP intake/executor checks retain five programs and ten completed jobs under
replay. Changed-file lint and whitespace checks passed.

Implementation is committed locally on child branches of the existing recovery
heads so active PR branches remain unchanged. No push, Actions, providers,
merge, deployment or production database operation. Rollback before publication:
leave these local child branches; the original recovery heads remain intact.
After any separately approved release, revert only the capability endpoint and
opt-in helper; existing program APIs and stored work need no schema reversal.

Budget: the user's screenshot reports period-level Agent usage, not this task's
cost. Actual task spending/remaining allowance cannot be verified from it; no
automatic budget enforcement or numerical task-spend claim is made.
