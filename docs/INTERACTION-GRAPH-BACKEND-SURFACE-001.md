# INTERACTION-GRAPH-BACKEND-SURFACE-001 — which service serves the Interaction Graph?

Status: evidence record for an owner decision. No code changes. Backend side only;
the frontend (`orchid-continuum-frontend`) was read, not modified, and nothing
below asserts what the separate public-API service does or does not serve.

Evidence captured 2026-09-25 against `orchid-calyx-backend` `main` (87dca7bb) and
`orchid-continuum-frontend` `src/lib/interactions.ts` as checked out locally.

## 1. What the frontend calls

`src/lib/interactions.ts` builds every request with `apiRequest()` from
`src/lib/api.ts`, whose base is `VITE_API_BASE_URL` (documented in the frontend
`README.md:52` as the Orchid Continuum public API,
`https://orchid-continuum-public-api.onrender.com`). It does not use the Calyx
backend base and it does not use `OC_BACKEND_BASE` from `src/lib/ocBackend.ts:11`
(same default origin, different constant).

| Frontend call | File:line | Path requested | Declared response type |
| --- | --- | --- | --- |
| `interactionsApi.panel()` | `src/lib/interactions.ts:125-133` | `GET /api/interactions/{taxonomyId}/panel` | `InteractionPanel` (`:107-118`) |
| `interactionsApi.summary()` | `src/lib/interactions.ts:135-143` | `GET /api/interactions/{taxonomyId}/summary` | `InteractionSummary` (`:60-74`) |
| `interactionsApi.partners()` | `src/lib/interactions.ts:145-153` | `GET /api/interactions/{taxonomyId}/partners` | `PartnerRow[]` (`:76-92`) |
| `interactionsApi.badges()` | `src/lib/interactions.ts:155-163` | `GET /api/interactions/{taxonomyId}/badges` | `InteractionBadge[]` (`:94-105`) |
| `interactionsApi.fetch()` (legacy) | `src/lib/interactions.ts:166-172` | `GET /api/interactions/{taxonomyId}/{kind}` | `InteractionPanelData` (`:45-50`) |

The type comments in the frontend say the four contracts "mirror the `oc_api`
views" `species_page_globi_interaction_panel_v1`,
`v_species_globi_interaction_summary_v1`, `v_species_globi_partner_summary_v1`
and `v_species_page_ecological_interaction_badges_v1`.

Live consumers: `src/components/interactions/EcologicalInteractionPanel.tsx:52` and
`src/components/widgets/index.tsx:340`, both calling `interactionsApi.panel()`.

## 2. What this backend serves under `/api/interactions`

Route table, captured with `from app.main import app` and iterating
`app.routes` for paths containing `interaction`:

```
['GET'] /api/interactions/discovery  get_interaction_discovery  app.interaction_discovery.routes
```

That is the only route. Source:

- `app/interaction_discovery/routes.py:18` — `router = APIRouter(prefix="/api/interactions", tags=["interaction-discovery"])`
- `app/interaction_discovery/routes.py:21-28` — `@router.get("/discovery")` with query params `taxon`, `category` (`pollinator | mycorrhizal | all`), `limit` (1..500)
- `app/main.py:28` imports the router; `app/main.py:540` includes it

### 2.1 The four frontend sub-paths, exercised with `fastapi.testclient.TestClient(app)`

| Request | Status | Body |
| --- | --- | --- |
| `GET /api/interactions/oc-tax-123/panel` | 404 | `{"detail":"Not Found"}` |
| `GET /api/interactions/oc-tax-123/summary` | 404 | `{"detail":"Not Found"}` |
| `GET /api/interactions/oc-tax-123/partners` | 404 | `{"detail":"Not Found"}` |
| `GET /api/interactions/oc-tax-123/badges` | 404 | `{"detail":"Not Found"}` |
| `GET /api/interactions/oc-tax-123/pollination` (legacy `fetch`) | 404 | `{"detail":"Not Found"}` |

None of the four sub-paths the frontend declares is served by this backend. There
is no path-parameterised `/api/interactions/{taxonomy_id}/...` route at all.

Repository search (`app/`, `runtime/`, `migrations/`, `docs/`, `*.py *.sql *.md
*.json`) for the four `oc_api` view names named in the frontend comments returns
zero hits, and `git log -S"interaction_panel" -- app runtime` finds no commit that
ever added such a route. So this repository has never carried these contracts;
they are not a regression here.

### 2.2 The one route that exists: `GET /api/interactions/discovery`

Captured response for `?taxon=Dendrobium%20nobile&category=pollinator&limit=2`
(status 200; the local index is empty, so `interactions` is `[]`):

```json
{
  "status": "ok",
  "count": 0,
  "total_matched": 0,
  "truncated": false,
  "category": "pollinator",
  "taxon_filter": "Dendrobium nobile",
  "review_bound": true,
  "knowledge_graph_mutation": false,
  "note": "These are unverified candidate ecological interactions discovered from Global Biotic Interactions (GloBI), not verified Knowledge Graph edges. Each record carries its source study citation and dataset provenance; promotion to a verified graph edge requires separate scientific review.",
  "interactions": []
}
```

Each element of `interactions` (`app/interaction_discovery/service.py:65-86`) has:
`source_taxon_name`, `source_taxon_id`, `target_taxon_name`, `target_taxon_id`,
`interaction_type`, `categories`, `study_citation`, `study_source_citation`,
`study_external_id`, `provider`, `provider_stability`, `dataset_version`,
`verification_state` (always `"UNVERIFIED"`), `knowledge_graph_mutation`
(always `false`), `revision_id`, `locator`.

## 3. Shape comparison against the frontend's declared types

| Frontend type | Served by Calyx? | Shape relationship |
| --- | --- | --- |
| `InteractionPanel` (`taxonomy_id`, `canonical_name?`, `summary?`, `partners?`, `badges?`, `data_needed?`, `data_needed_reason?`, `last_updated?`, `source?`) | No (404) | No Calyx payload has `taxonomy_id`, `summary`, `partners` or `badges` keys. |
| `InteractionSummary` (`taxonomy_id`, `pollinator_count?`, `flower_visitor_count?`, `mycorrhizal_partner_count?`, `herbivore_count?`, `total_interactions?`, `partner_diversity_index?`, …) | No (404) | Calyx `discovery` returns `count` / `total_matched` for one `category` filter, not per-interaction-class counts, and is not keyed by `taxonomy_id`. |
| `PartnerRow[]` (`partner_taxon`, `partner_kingdom?`, `partner_family?`, `interaction_type`, `interaction_count?`, `evidence_records?`, `reference_count?`, `first_observed?`, `last_observed?`, `primary_source?`, `reference_url?`) | No (404) | Closest Calyx analogue is a `discovery.interactions[]` record: it has `interaction_type` and `target_taxon_name` (not `partner_taxon`), carries `study_citation` / `provider` / `dataset_version` provenance instead of `reference_url` / `primary_source`, has no aggregates (`interaction_count`, `evidence_records`, `reference_count`) and no observation dates, and is explicitly `verification_state: "UNVERIFIED"`. |
| `InteractionBadge[]` (`code`, `label`, `tone?`, `evidence_strength?`, `count?`, `description?`) | No (404) | Nothing in Calyx produces badge codes/labels. |
| `InteractionPanelData` (legacy: `kind`, `total`, `records[]` of `partner_taxon`, `evidence?`, `source?`, `reference_url?`, `confidence?`) | No (404) | No `kind`/`records` payload exists. |

Only `interaction_type` overlaps by name between `PartnerRow` and a Calyx
discovery record; every other field name differs or is absent.

## 4. What this means for the decision

- Calyx (`orchid-calyx-backend`) serves exactly one Interaction Graph read
  surface, `GET /api/interactions/discovery`: unverified, review-bound GloBI
  candidates with study/dataset provenance, filtered by taxon text and category.
  It is a candidate-evidence surface, not the species-page aggregate the frontend
  renders.
- The frontend's four calls target the public-API origin and describe aggregate
  `oc_api` views. Whether that service serves them is outside this repository's
  evidence and is not asserted here.
- If the owner decides Calyx should produce the Interaction Graph panel, the
  backend work is a new path-parameterised router (`/api/interactions/{taxonomy_id}/
  panel|summary|partners|badges`) plus the aggregation behind it, and the
  frontend would have to be pointed at the Calyx origin for these calls; the
  existing `discovery` route would remain the provenance-bearing candidate feed.
  If the owner decides the public API produces it, nothing changes in Calyx and
  the `discovery` route stays as the only Calyx interaction surface.

## 5. Reproduction

```bash
cd orchid-calyx-backend
python - <<'PY'
from fastapi.testclient import TestClient
from app.main import app
print([(r.path, sorted(r.methods)) for r in app.routes if "interaction" in r.path])
c = TestClient(app)
for sub in ("panel", "summary", "partners", "badges"):
    r = c.get(f"/api/interactions/oc-tax-123/{sub}"); print(sub, r.status_code, r.text)
print(c.get("/api/interactions/discovery", params={"taxon": "Dendrobium nobile", "category": "pollinator", "limit": 2}).json())
PY
```
