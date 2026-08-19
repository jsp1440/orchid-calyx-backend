# CALYX-MATRIX-022 — Durability deployment contract

## Status

Repository-side deployment tooling only. This document does not assert that production migrations or persistent hosting settings have been changed.

## Supported entrypoint

The supported direct-command entrypoint is:

`python scripts/calyx_matrix_durability_run.py`

The file `scripts/calyx_matrix_durability_deploy.py` is an internal implementation module and is not the supported direct operator entrypoint.

The launcher bootstraps the repository root before importing local modules, so it is safe to invoke directly from a standard repository checkout.

## Custom registry source

When `--source-root` is supplied to the launcher, that root is used consistently for the registry-copy operation and for the post-copy readiness verification performed during the same invocation. The launcher temporarily scopes `CALYX_MATRIX_REGISTRY_DIR` to the selected source and restores the previous process environment afterward.

This prevents a successful copy from one registry directory from being verified against a different default registry directory.

## Mutation boundary

Dry-run is the default. The guarded write phase is explicitly requested through the launcher. Repository tooling may apply the governed Matrix persistence migrations and copy immutable registry packages, but it does not persistently change hosting environment settings.

Persistent activation remains a separate deployment operation after readiness reports that both Matrix persistence components are activation-ready.

## Verification

The Matrix regression suite includes tests that:

- execute the launcher directly as a subprocess from the repository checkout;
- verify repository-root import bootstrapping;
- verify custom source-root scoping during the underlying deployment call;
- verify prior environment state is restored after the call;
- verify no custom source leaves the configured registry root unchanged.

The integrated durability readiness endpoint remains read-only and is used to verify activation state after deployment.