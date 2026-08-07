# BUILD-BRAIN-114J — External sandbox supervisor proof

## Objective

Turn the executable-validation trust boundary from a repository-only contract into a demonstrable OS-level sandbox proof without granting production activation, merge, deployment, publication, taxonomy activation, database mutation, or Knowledge Graph mutation authority.

## Implemented

The BUILD-BRAIN-114J workflow launches a disposable Docker runtime with:

- `--network=none`;
- read-only container root filesystem;
- repository mounted read-only;
- all Linux capabilities dropped;
- `no-new-privileges` enforced;
- unprivileged uid/gid 65534;
- bounded tmpfs for `/tmp` with `noexec,nosuid,nodev`;
- no repository/application credentials passed into the container.

`scripts/verify_calyx_sandbox_runtime.py` fails closed unless it can independently demonstrate:

- expected credential variables are absent;
- `/proc/self/status` reports `NoNewPrivs: 1`;
- writes to the repository fail;
- writes to the container root filesystem fail;
- an outbound TCP connection cannot be established.

## Relationship to BUILD-BRAIN-114I

BUILD-BRAIN-114I already requires a trusted `SandboxValidationAuthorizer` before the executable-validation role becomes claimable and binds authorization to the exact repository, autonomy branch, checkout commit, sandbox assertions, validation preset, target files/hashes, and timeout.

BUILD-BRAIN-114J supplies an executable proof pattern for the external runtime controls that such an authorizer must enforce. It does not yet wire a production service to issue authorizations automatically.

## Validation evidence

GitHub-hosted run `31225128294` completed successfully on 2026-08-07. The workflow executed checkout, Python compilation of the verifier, the Docker-isolated runtime proof, and diff hygiene. The isolated-runtime step passed with network disabled, repository/root writes blocked, credentials absent, all capabilities dropped, `no-new-privileges` enforced, and an unprivileged runtime identity.

## Remaining boundary

A production supervisor still needs durable authorization issuance/evidence plumbing and deployment outside the repository process. The repository may not self-authorize based solely on this workflow or a marker file.

No arbitrary shell/argv acceptance, package installation inside the sandbox, network, credentials, Git mutation, autonomous PR creation, merge, deployment, scientific publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation is authorized.
