# BUILD-BRAIN-114U — Governed GitHub Proposal Mutation Adapter

## Mission

Implement the narrowly scoped GitHub mutation adapter authorized by issue #842 on top of the validated current-main 114S executor and 114T durability/recovery candidates. This slice makes the remote mutation boundary production-capable in code without activating a credential or enabling live production mutation.

## Dependency

This branch is stacked on PR #852 exact head `90a1e147f47b4bb66781479a8547282d32da7bae`, which is itself stacked on PR #851. It must not be merged ahead of those dependencies.

## Implemented authority

The adapter implements only the four reviewed proposal operations:

1. create `autonomy/proposal/*` branch from the exact reviewed base SHA;
2. create an exact Git commit from validated postimage bytes;
3. fast-forward only the exact authorized proposal branch to the verified created commit;
4. open exactly one **draft** pull request to the reviewed base ref.

No other GitHub mutation endpoint is implemented.

## Exactness and idempotency

- repository allowlist is re-enforced inside the adapter;
- proposal branch namespace is re-enforced inside the adapter;
- branch creation is idempotent only when an existing ref points to the exact reviewed base SHA;
- postimage bytes are obtained through an injected trusted resolver and re-hashed against the reviewed SHA-256 values before any blob is accepted;
- returned Git blob SHA is independently recomputed from exact bytes and verified;
- existing executable/symlink file modes are preserved only for a bounded safe set, with new files defaulting to regular mode;
- the resulting tree is read back and every changed path/mode/blob SHA is verified;
- commit identity is deterministic: the exact tree, reviewed parent, bounded CALYX identity, base-commit timestamp, commit title, plan digest, and patch-program job ID determine the expected Git commit SHA;
- a repeated commit operation first checks the deterministic expected SHA and accepts only an exact existing object; otherwise it creates the object and requires GitHub to return that same expected SHA;
- push obtains the created commit SHA from persisted mutation evidence, permits only an exact fast-forward from reviewed base to that commit, and uses `force: false`;
- a retry after the branch is already at the exact commit returns `already_exists_exact`;
- draft-PR creation verifies the reviewed base ref has not moved, verifies the proposal head SHA, searches for an existing open PR with that exact head/base, and accepts only one exact draft PR; any conflicting or non-draft PR fails closed;
- pull-request evidence returns number, URL, exact head/base identity, and draft state without credentials.

## Credential boundary

`RequestsGitHubTransport` accepts a credential only through constructor injection. It does not read a token from environment variables, settings, files, Brain state, Mission Control, or model context. Its representation redacts the token, transport exceptions replace underlying request text with stable error codes, and response bodies are not embedded in transport exceptions.

This PR does **not** register a token, GitHub App installation, environment secret, production feature flag, or runtime adapter instance. Credential provisioning and live registration remain a separate owner-governed step under issue #842 section D.

## Recovery integration

The adapter consumes the durable mutation journal through the minimal `latest(plan_digest=...)` evidence interface. Because the executor persists `create_commit` evidence before attempting `push_branch`, a restart can recover the exact created commit SHA without relying on process memory. Likewise, a crash after a successful push or draft-PR creation can be retried using remote `already_exists_exact` checks once the preceding durable evidence exists.

This still does not claim distributed exactly-once semantics. If both local durable evidence and remote reachability are lost, the system fails closed rather than guessing.

## Permanent non-authority

This implementation does not contain or authorize:

- merge or auto-merge;
- force push;
- branch deletion;
- deployment;
- production environment mutation;
- production database migration;
- scientific publication or Candidate Knowledge promotion;
- taxonomy activation;
- production Knowledge Graph mutation;
- billing or spending;
- secret disclosure.

## Validation contract

Hosted CI must prove:

- compile and Ruff lint/format;
- 114R execution-plan, 114S executor, 114T journal/restart, and 114U adapter regressions together;
- exact end-to-end branch → commit → push → draft-PR flow against an in-memory deterministic GitHub transport fixture;
- completed retries produce no additional remote calls/PRs;
- exact existing-branch idempotency and mismatched-branch rejection;
- wrong postimage SHA rejection before blob/commit creation;
- wrong returned blob SHA rejection;
- wrong pushed SHA rejection;
- moved reviewed base rejection;
- non-draft PR rejection;
- repository and branch confinement;
- credential redaction in repr and exceptions;
- static absence of merge/deployment/destructive/scientific authority;
- no credential activation in the implementation/test surface.

## Next dependency

After this adapter candidate is green and reviewed, the next slice is issue #842 section D: register the live executor behind explicit owner authorization, repository allowlist, exact-base identity, accepted validation receipts, durable-journal readiness, and an off-by-default feature/environment gate. Actual credential activation remains a governance boundary and must not be inferred from this implementation.
