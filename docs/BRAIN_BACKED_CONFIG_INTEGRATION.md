# Brain-Backed Calyx Runtime Configuration

## Purpose

This branch begins moving Calyx configuration out of backend code and into the Brain repository.

The backend remains the execution engine. The Brain repository becomes the source of truth for:

- runtime service registry
- infrastructure registry
- governance policy
- knowledge preservation policy
- Calyx Core manifest

## New Runtime Components

### `runtime/config_loader.py`

Loads JSON configuration from the Brain repository using the GitHub Contents API.

Environment variables:

- `CALYX_BRAIN_REPO` — defaults to `jsp1440/Orchid-Continuum-Brain`
- `CALYX_BRAIN_REF` — defaults to `calyx-core-operational-foundation`
- `GITHUB_TOKEN` or `CALYX_GITHUB_TOKEN` — required for private Brain repo access in production
- `GITHUB_API_BASE` — optional GitHub API override

### `runtime/infrastructure.py`

Loads the Brain-backed infrastructure registry and checks registered service health.

## New Endpoints

```text
/api/config/manifest
/api/config/runtime-services
/api/config/governance-policy
/api/config/knowledge-preservation-policy
/api/infrastructure/registry
/api/infrastructure/health
/api/runtime/heartbeat
```

## Heartbeat Changes

The heartbeat now includes Brain-backed infrastructure health when configuration can be loaded.

## Production Requirement

Because `jsp1440/Orchid-Continuum-Brain` is private, Render needs a GitHub token configured as either:

```text
CALYX_GITHUB_TOKEN
```

or

```text
GITHUB_TOKEN
```

The token should be read-only and scoped as narrowly as possible.

## Safety

This integration is read-only. It does not modify the Brain repository, GitHub, Render, databases, or production services.
