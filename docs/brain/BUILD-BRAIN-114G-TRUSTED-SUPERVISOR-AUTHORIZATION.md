# BUILD-BRAIN-114G — Trusted supervisor authorization

## Why this corrective slice was required

BUILD-BRAIN-114F initially required a strict workspace marker before executable validation, but a marker is still repository-local evidence. Repository-local evidence alone must never be sufficient to authorize repository-code execution.

This slice closes that gap before the executable validator can advance beyond draft.

## Implemented

- Added `SandboxValidationAuthorizer`, a trusted-runtime protocol that lives outside the repository-workspace trust boundary.
- Added `SandboxAuthorization`, a non-secret authorization receipt containing an authorization ID, evidence URI, and SHA-256 policy digest.
- `SandboxedExecutableValidationExecutor` now requires both:
  1. a valid repository sandbox marker; and
  2. a successful trusted supervisor authorization for the exact workspace, repository, branch, and marker claims.
- Marker-only execution fails closed with `SANDBOX_VALIDATION_SUPERVISOR_REQUIRED` before subprocess launch.
- Supervisor rejection fails closed with `SANDBOX_VALIDATION_SUPERVISOR_REJECTED` before subprocess launch.
- Authorization evidence is included in the final execution receipt without exposing credentials or supervisor secrets.
- The default `AuthoritativeExecutorRegistry` does **not** register the executable-validation role.
- The role becomes claimable only when a trusted `sandbox_validation_authorizer` is injected into the registry by the runtime supervisor.
- Registry status truthfully exposes whether sandboxed repository-code execution is currently authorized.

## Autonomous-cycle consequence

A normal Calyx autonomous worker using the default registry cannot claim an executable-validation job. Such a job remains queued with zero attempts until a trusted runtime creates a registry with a supervisor authorizer.

When a trusted authorizer is injected, the existing governed sequence can proceed:

patch → static validation → supervisor-authorized executable validation → authoritative receipt → program completion/block.

## Tests added/updated

- marker alone cannot launch subprocess;
- rejected supervisor cannot launch subprocess;
- default registry omits executable-validation role;
- authorized registry exposes it explicitly;
- end-to-end patch/static/executable cycle requires an injected supervisor;
- no-supervisor end-to-end program leaves executable validation queued with attempt count zero;
- successful authorization evidence is bound into receipts.

## Remaining boundary

This protocol authenticates the *decision* of a trusted supervisor; it does not itself implement Linux namespaces, container networking, seccomp, read-only mounts, or another OS sandbox. Production activation therefore still requires an external supervisor implementation that actually enforces the marker policy before issuing authorization.

Until that supervisor exists and passes independent validation, executable repository-code validation remains draft-only.

## Governance preserved

No automatic Git commit, push, PR creation, merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation is enabled.

Issues: #543, #546
