# BUILD-040 Kernel

## Architecture

BUILD-040 adds the Orchid Continuum Kernel as read-only backend infrastructure. The Kernel lives in `runtime.kernel_registry` and is exposed through `runtime.kernel_router` at `/api/kernel/*`.

The Kernel does not replace Mission Control, Atlas, or any frontend route. It makes existing and planned platform surfaces discoverable through typed registries that Mission Control can consume in a later build.

## Registries

The Kernel implements:

- Application Registry: Mission Control, Atlas, Species Explorer, Knowledge Graph, Vision Lab, Grant Office, Research Workspace, University, Conservatory, and Settings.
- Service Registry: FastAPI, Postgres, Supabase, Render, Harvester Runner, Scheduler, Telemetry, Image Service, and Taxonomy Service.
- Capability Registry: queryable application capabilities, including Atlas exploration layers and Mission Control telemetry, health, recommendations, build tracking, safety, and governance.
- Integration Registry: GitHub, Render, Azure, OpenAI, Claude, Kimi, Google Drive, Gmail, Supabase, Neon, GBIF, iNaturalist, EOL, TraitBank, World Plants, Zenodo, GenBank, BOLD, and Zotero.
- Task / Build Registry: structured build records for BUILD-040 and recent supporting build context.
- Constitution Registry support: governance version, policy count, decision count, and constitutional status are sourced from the existing constitutional orchestrator.

Each registry object reports status, health, owner, repository, dependencies, capabilities, telemetry source, last update, evidence, warning, and recommendation.

## API

Read-only endpoints:

- `GET /api/kernel/applications`
- `GET /api/kernel/services`
- `GET /api/kernel/capabilities`
- `GET /api/kernel/capabilities?application_id=atlas`
- `GET /api/kernel/capabilities?query=health`
- `GET /api/kernel/integrations`
- `GET /api/kernel/builds`
- `GET /api/kernel/health`

No write endpoints were added. The Kernel does not bypass authentication, read secrets, or mutate deployments.

## Future Extensions

- Replace static health values with deployment-aware service probes.
- Add provider-specific integration checks through approved connector services.
- Let Mission Control consume `/api/kernel/builds` instead of hardcoded build cards.
- Add registry loaders for repo-hosted configuration once the registry schema stabilizes.
- Add frontend route probes for Mission Control, Atlas, and related applications.

## Migration Notes

Existing Mission Control and Atlas behavior is unchanged. Frontend deployment is not required for this build unless a later frontend consumer is added. Backend deployment is required to expose the new `/api/kernel/*` endpoints in production.
