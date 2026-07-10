# BUILD-051 Owner Operations Backend

## Scope

BUILD-051 adds the server-side authority for the Owner Operations Console. Browser unlock does not authorize backend writes. State-changing actions require a signed owner session or the existing server-only API key path and are recorded in the privileged action log.

## Environment

- `CALYX_OWNER_ACCESS_CODE`: owner-provided secret used only by the backend session endpoint.
- `CALYX_OWNER_SESSION_SECRET`: HMAC signing secret for stateless owner bearer sessions.
- `CALYX_API_KEY`: server-only backend actor credential. It must never be exposed to frontend bundles.
- `DATABASE_URL`: optional for local tests; required for production database persistence.

## Endpoints Added

| Endpoint | Purpose | Auth | Persistence |
|---|---|---|---|
| `POST /api/mission-control/owner/session` | Exchange owner access code for signed session | Access code | Stateless session response only |
| `GET /api/mission-control/owner/session` | Validate bearer session | Owner bearer | None |
| `GET /api/mission-control/owner/permissions` | Return per-action `allowedActions` | Owner bearer or API key | None |
| `POST /api/mission-control/owner/source-briefings` | Preserve raw source briefing and server parse provisional intelligence | Owner bearer or API key | `source_briefings`, `intelligence_items`, action log |
| `GET /api/mission-control/owner/source-briefings` | List source briefings | Owner bearer or API key | Reads `source_briefings` |
| `POST /api/mission-control/owner/intelligence/import-local` | Import owner-approved browser records with dedupe | Owner bearer or API key | `intelligence_items`, action log |
| `GET /api/mission-control/owner/intelligence` | Retrieve central intelligence queues | Owner bearer or API key | Reads `intelligence_items` |
| `PATCH /api/mission-control/owner/intelligence/{item_id}` | Update review/assignment/notes state | Owner bearer or API key | `intelligence_items`, action log |
| `POST /api/mission-control/owner/audits` | Generate live audit Markdown/JSON from backend telemetry | Owner bearer or API key | `generated_audits`, action log |
| `GET /api/mission-control/owner/audits` | List generated audits | Owner bearer or API key | Reads `generated_audits` |
| `POST /api/mission-control/owner/commands` | Parse command, apply constitutional review, create durable command and queue item | Owner bearer or API key | `owner_commands`, `operations_queue`, action log |
| `GET /api/mission-control/owner/commands` | List command history | Owner bearer or API key | Reads `owner_commands` |
| `GET /api/mission-control/owner/operations-queue` | Read durable operations queue | Owner bearer or API key | Reads `operations_queue` |
| `POST /api/mission-control/owner/operations-queue/{item_id}/{transition}` | Approve/reject/cancel/retry eligible queue items | Owner bearer or API key | `operations_queue`, action log |
| `POST /api/mission-control/owner/research-requests` | Create durable research request | Owner bearer or API key | `research_requests`, action log |
| `GET /api/mission-control/owner/research-requests` | List research requests | Owner bearer or API key | Reads `research_requests` |
| `POST /api/mission-control/owner/partnership-packets` | Generate live partnership packet | Owner bearer or API key | `partnership_packets`, action log |
| `GET /api/mission-control/owner/partnership-packets` | List partnership packets | Owner bearer or API key | Reads `partnership_packets` |

## Tables Added

`migrations/BUILD-051-owner-operations-console.sql` creates:

- `oc_admin.build051_source_briefings`
- `oc_admin.build051_intelligence_items`
- `oc_admin.build051_owner_commands`
- `oc_admin.build051_operations_queue`
- `oc_admin.build051_research_requests`
- `oc_admin.build051_generated_audits`
- `oc_admin.build051_partnership_packets`
- `oc_admin.build051_privileged_action_log`

`migrations/BUILD-051-owner-operations-smoke-test.sql` verifies these tables and indexes without changing production data.

## Control Matrix

| Capability | Backend endpoint | Auth | DB persistence | Calyx / policy integration | Production readiness |
|---|---|---|---|---|---|
| Owner session | `/owner/session` | Access code, signed bearer output | Stateless | Does not disclose API key or session secret | Ready after env config |
| Allowed actions | `/owner/permissions` | Owner bearer or API key | None | Exact action permission contract | Ready |
| Harvester run/pause/resume/reassess/retire/restore | `/api/harvesters/*` | Owner bearer or API key | Harvester control plane | Uses authenticated actor | Ready for supported actions |
| Harvester target/schedule/proposal | `/api/harvesters/*` | Owner bearer or API key | Harvester control plane | Requires structured frontend payload/proposal ID | Backend ready, UI partially blocked |
| Source briefing | `/owner/source-briefings` | Owner bearer or API key | Raw briefing and parsed items | Provisional server parse | Ready after migration |
| Intelligence import/edit | `/owner/intelligence/*` | Owner bearer or API key | Intelligence items | Dedupes local imports, records review state | Ready after migration |
| Audit generation | `/owner/audits` | Owner bearer or API key | Generated audit record | Queries Mission Control metrics/completeness/harvesters | Markdown/JSON ready; PDF/DOCX blocked |
| Command bar | `/owner/commands` | Owner bearer or API key | Commands and queue | Constitutional review for high-risk command intents | Ready |
| Operations queue | `/owner/operations-queue` | Owner bearer or API key | Queue records | Durable state transitions and action log | Ready |
| Research requests | `/owner/research-requests` | Owner bearer or API key | Research requests | Queues request, does not fabricate results | Ready |
| Partnership packets | `/owner/partnership-packets` | Owner bearer or API key | Packet records | Uses live audit capability/gap data | Markdown/JSON ready; PDF/DOCX blocked |

## Migration And Rollback

1. Review `migrations/BUILD-051-owner-operations-console.sql`.
2. Apply it manually with `psql` and `ON_ERROR_STOP`.
3. Run `migrations/BUILD-051-owner-operations-smoke-test.sql`.
4. If rollback is required before production use, drop only the new `oc_admin.build051_*` tables after exporting any records that must be retained.

No production migration is automatic.

## Validation

- `python -m py_compile app/security.py app/routers/owner_operations.py app/routers/harvesters.py app/routers/health.py`
- `pytest tests/test_build_051_owner_operations.py`
- Focused prior runtime tests before merge
