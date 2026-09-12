# OC-ARK — Autonomous Preservation & Recovery Service

OC-ARK is the provider-independent disaster-recovery subsystem for Orchid Continuum. It is deliberately capable of running without Calyx, the frontend, Neon, Render, OpenAI, Anthropic, or any other AI provider.

## What the first implementation preserves

- Complete Git history for the Brain, Calyx backend, and frontend as portable Git bundles.
- PostgreSQL data as a custom-format `pg_dump` when `DATABASE_URL` is configured.
- SHA-256 checksums and a machine-readable manifest for every run.
- Azure Blob Storage as an off-provider cloud target when configured.
- An external drive as a second, offline target whenever `ARK_OFFLINE_ROOT` is mounted.
- A smoke restore of at least one Git bundle on every successful run.

## Runtime requirements

Required for repository preservation:

- Python 3.11+
- git

Required when database backup is enabled:

- PostgreSQL client tools (`pg_dump`, `pg_restore`)

Required when Azure upload is enabled:

- Azure CLI (`az`), authenticated with a workload identity/service principal or managed identity in production

## Environment

Never commit credentials. Configure these in the independent ARK runtime:

- `GITHUB_TOKEN` — read-only token able to clone private OC repositories.
- `DATABASE_URL` — least-privilege PostgreSQL connection capable of logical backup.
- `AZURE_STORAGE_ACCOUNT` — dedicated OC-ARK storage account.
- `AZURE_STORAGE_CONTAINER` — dedicated backup container, recommended value `oc-ark`.
- `ARK_LOCAL_ROOT` — local staging/state directory.
- `ARK_OFFLINE_ROOT` — optional external-drive mount point. If absent, cloud preservation continues normally.

## Commands

```bash
python ark/oc_ark.py inventory --config ark/ark_config.example.json
python ark/oc_ark.py backup --config ark/ark_config.example.json
```

`inventory` is non-destructive and reports configured targets and required tooling.

`backup` performs:

1. Git mirror clones and portable bundles.
2. PostgreSQL logical dump when configured.
3. Manifest creation.
4. SHA-256 verification.
5. Git clean restore smoke test.
6. Azure upload when configured.
7. Offline-drive copy when mounted.
8. Healthy-run state recording only after all required steps succeed.

A failure exits non-zero; the scheduler/watchdog should retry and alert only after the configured failure threshold.

## Autonomous scheduling

ARK must not depend on the Calyx worker or the normal Orchid Continuum orchestration queue.

Recommended production cadence:

- every hour: inventory/target health check
- every 6 hours: repository preservation if material changes exist
- daily: full repository + PostgreSQL backup
- weekly: deeper integrity verification
- monthly: isolated clean-room reconstruction test
- event-triggered: preservation after material architecture/schema releases

A systemd timer, Azure Container Apps Job, Azure Automation task, or another independent scheduler can invoke the deterministic runner. GitHub Actions may be used only as a secondary trigger, never as the sole scheduler.

## Azure target

Create a dedicated Storage Account and container for OC-ARK rather than mixing the archive with application assets. Enable appropriate redundancy, versioning/soft-delete, and an immutability policy for retained recovery sets. Give ARK only the minimum Blob permissions needed to upload and validate its own container.

The Azure copy is one independent cloud copy. Azure replication does not replace the external-drive tier because those replicas remain under the same cloud provider/account boundary.

## External drive target

The external drive should normally remain disconnected. When connected and mounted, set `ARK_OFFLINE_ROOT` to its mount path and run the backup command. ARK copies the already-verified run package into:

`<drive>/orchid-continuum-ark/<run-id>/`

The drive can then be disconnected and stored safely.

## Recovery invariant

The milestone is not complete because a backup exists. It is complete only when Orchid Continuum can be reconstructed from independently stored artifacts and the result passes integrity/smoke checks.

## Next build items

1. Add database restore smoke test into an isolated PostgreSQL instance.
2. Add material-change detection so unchanged repositories are not redundantly archived.
3. Add retention pruning without ever deleting the last known-good generation.
4. Add signed manifests and optional client-side encryption before cloud upload.
5. Add continuity telemetry to Mission Control without making Mission Control an ARK dependency.
6. Add provider-loss simulation and monthly clean-room reconstruction evidence.
