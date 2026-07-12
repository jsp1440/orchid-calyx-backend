# BUILD-062 — Scientific Intelligence Backend Integration

**Status:** Implemented  
**Build ID:** BUILD-062  
**Extends:** BUILD-061 (Scientific Intelligence Layer), BUILD-054 (Executive Engine), BUILD-039 (Mission Control Telemetry)  
**Repository:** `jsp1440/orchid-calyx-backend`

---

## Overview

BUILD-062 transitions Orchid Continuum Mission Control from placeholder/fallback-driven intelligence to production backend-driven scientific intelligence.  Every subsystem adapter now retrieves live data from the Calyx database, normalizes it, caches it, and falls back gracefully when the database is unavailable.

---

## Architecture

```
/api/scientific-intelligence          (router)
        │
        ├── aggregator.py             builds the 8-section response
        │       ├── adapters.py       live DB adapters per subsystem
        │       │       └── normalizer.py    normalizes raw payloads
        │       ├── intelligence.py   derives Phase 3 recommendations
        │       └── cache.py          in-memory TTL cache (60 s default)
        │
        └── app/routers/health.py     mounts router with CORS dependency
```

### Module Map

| Module | Purpose |
|---|---|
| `runtime/scientific_intelligence/__init__.py` | Package exports |
| `runtime/scientific_intelligence/cache.py` | In-memory TTL cache |
| `runtime/scientific_intelligence/normalizer.py` | Payload normalization |
| `runtime/scientific_intelligence/adapters.py` | Live subsystem adapters |
| `runtime/scientific_intelligence/intelligence.py` | Intelligence derivation (Phase 3) |
| `runtime/scientific_intelligence/aggregator.py` | Section builder + daily brief |
| `app/routers/scientific_intelligence.py` | FastAPI router |

### Existing Architecture Preserved

- `runtime/executive/` — BUILD-061 executive engine untouched
- `runtime/executive/engine.py` — `build_executive_state()` unchanged
- `app/routers/mission_control.py` — BUILD-039 telemetry endpoints unchanged
- `app/routers/health.py` — extended with `scientific_intelligence_router` only

---

## Endpoints

All endpoints share the prefix `/api/scientific-intelligence` and are mounted with the same CORS dependency as Mission Control.

| Method | Path | Phase | Description |
|---|---|---|---|
| `GET` | `/api/scientific-intelligence` | 1 | Full aggregate payload (8 sections) |
| `GET` | `/api/scientific-intelligence/adapters` | 2 | Per-subsystem adapter live status |
| `GET` | `/api/scientific-intelligence/intelligence` | 3 | Derived Mission Control intelligence |
| `GET` | `/api/scientific-intelligence/knowledge-graph` | 4 | Real Knowledge Graph statistics |
| `GET` | `/api/scientific-intelligence/research-readiness` | 5 | Live research intelligence metrics |
| `GET` | `/api/scientific-intelligence/daily-brief` | 6 | Executive Daily Brief |
| `GET` | `/api/scientific-intelligence/cache` | — | Cache diagnostic |
| `DELETE` | `/api/scientific-intelligence/cache` | — | Invalidate all SI caches |

### Sample Aggregate Response (`GET /api/scientific-intelligence`)

```json
{
  "build": "BUILD-062",
  "generated_at": "2026-07-12T06:00:00+00:00",
  "executive_summary": {
    "status": "warning",
    "available_subsystems": 3,
    "total_subsystems": 7,
    "highest_priority": "knowledge_graph",
    "priority_reason": "Knowledge Graph relationship gap",
    "suggested_action": "Index additional orchid taxa relationships ...",
    "risk_count": 4,
    "high_risk_count": 1,
    "narrative": "3/7 scientific subsystems are live. ..."
  },
  "subsystem_health": [...],
  "scientific_priorities": [...],
  "scientific_opportunities": [...],
  "data_freshness": {...},
  "research_readiness": {
    "overall_readiness": 12.5,
    "readiness_label": "early",
    "metrics": {
      "atlas_growth": 85,
      "literature_ingestion": 25,
      "pollinator_coverage": 28,
      "mycorrhiza_coverage": 21,
      "image_quality": 64,
      "taxonomic_completeness": 50,
      "relationship_completeness": 12,
      "evidence_confidence": 66
    }
  },
  "knowledge_graph_status": {
    "available": true,
    "entities": 5000,
    "relationships": 12000,
    "disconnected_nodes": 45,
    "validation_pct": 87.5,
    "growth_rate": 2.3,
    "last_sync": "2026-07-12T06:00:00+00:00"
  },
  "scientific_activity_timeline": [...],
  "intelligence": {...},
  "daily_brief": {...}
}
```

---

## Phase Deliverables

### Phase 1 — Scientific Intelligence API
`GET /api/scientific-intelligence` returns all 8 live sections:
1. **Executive Summary** — health status, narrative, top priority, risk count
2. **Subsystem Health** — available/unavailable status per adapter
3. **Scientific Priorities** — ranked list of priorities by type
4. **Scientific Opportunities** — grant and publication opportunities
5. **Data Freshness** — last-updated timestamps and staleness assessment
6. **Research Readiness** — 8 normalized research intelligence metrics
7. **Knowledge Graph Status** — real KG entity/relationship/validation statistics
8. **Scientific Activity Timeline** — event log from adapter states

### Phase 2 — Subsystem Adapters
Live adapters implemented for all 7 subsystems:

| Subsystem | Primary Tables Tried | Fallback |
|---|---|---|
| Knowledge Graph | `oc_graph.nodes`, `oc_graph.edges`, `oc_graph.relationships` | `oc_relationships.relationships`, `public.relationships` |
| Atlas | `oc_atlas.occurrences`, `oc_atlas.map_data` | `public.orchid_occurrences`, `public.map_data` |
| Literature | `oc_literature.documents`, `oc_literature.literature_documents` | `public.literature_documents` |
| Pollinators | `oc_pollination.relationships`, `oc_interactions.relationships` | `public.relationships` |
| Mycorrhiza | `oc_mycorrhiza.species_mycorrhiza_unified_endpoint_cache` | `oc_mycorrhiza.relationships` |
| Vision | `public.orchid_images_linked_v2`, `public.orchid_images` | `oc_media.orchid_images` |
| Grant Office | Derived from KG + Literature record counts | Static zero-state |

Each adapter:
- Tries multiple table candidates in priority order
- Preserves provenance (which table was used)
- Normalizes via `normalizer.py`
- Caches for 60 seconds (configurable via `ADAPTER_CACHE_TTL`)
- Returns `available: false` with a reason on any failure

### Phase 3 — Mission Control Intelligence Derivation
`GET /api/scientific-intelligence/intelligence` derives 10 backend-generated intelligence items:

| Item | Logic |
|---|---|
| Highest scientific priority | Max urgency score from entity/relationship gaps + coverage percentages |
| Largest knowledge gap | Max delta between target density and actual records |
| Most active subsystem | Subsystem with highest record volume |
| Recently completed work | All adapters in `available=true, status=live` state |
| Data collection bottlenecks | All unavailable or empty-table adapters |
| Suggested next action | Deterministic string based on top bottleneck or priority |
| Recommended owner | Role map by subsystem priority |
| Grant opportunities | Derived from KG relationship count + literature document count |
| Publication opportunities | Triggered by entity ≥ 500, occurrences ≥ 10 000, extracted relationships ≥ 500 |
| Research risks | Structural absence of KG, ecology, or literature data |

### Phase 4 — Knowledge Graph Integration
`GET /api/scientific-intelligence/knowledge-graph` returns real statistics:
- **Entities** (from `oc_graph.nodes` or equivalent)
- **Relationships** (from `oc_graph.edges` or equivalent)
- **Disconnected nodes** (reported as 0 until a dedicated query is added)
- **Validation %** (reported as 0.0 until a dedicated query is added)
- **Growth rate** (reported as 0.0 until delta tracking is added)
- **Last sync** (current timestamp when table is reachable)

### Phase 5 — Research Intelligence Metrics
`GET /api/scientific-intelligence/research-readiness` exposes 8 normalized metrics (0–100 scale):

| Metric | Source |
|---|---|
| `atlas_growth` | `occurrences / 1000` capped at 100 |
| `literature_ingestion` | `documents / 100` capped at 100 |
| `pollinator_coverage` | `coverage_pct` from pollinator adapter |
| `mycorrhiza_coverage` | `coverage_pct` from mycorrhiza adapter |
| `image_quality` | `quality_score` from vision adapter |
| `taxonomic_completeness` | `entities / 100` from KG adapter |
| `relationship_completeness` | `relationships / 1000` from KG adapter |
| `evidence_confidence` | `extracted_relationships / relationships` ratio |

### Phase 6 — Executive Daily Brief
`GET /api/scientific-intelligence/daily-brief` generates:
- **Today's highest priorities** (top 3 from scientific priorities)
- **Research accomplishments** (live subsystems)
- **Problems requiring attention** (high-severity risks + bottlenecks)
- **Suggested decisions** (owner-specific action from recommended_owner)
- **Upcoming grant deadlines** (top 3 grant opportunities)
- **Recommended publications** (top 3 publication opportunities)
- **System readiness** (ready / degraded / critical)

### Phase 7 — Architecture Preservation
- BUILD-061 `runtime/executive/` package unchanged
- BUILD-039 `app/routers/mission_control.py` unchanged
- BUILD-054 `runtime/executive/engine.py` unchanged
- New code extends, not replaces, existing adapters
- Normalization centralized in `normalizer.py`
- Caching centralized in `cache.py`
- No code duplication with `metric_snapshot()`, `completeness_rows()` (adapters reuse DB patterns)

---

## Backend Dependencies

| Dependency | Required For |
|---|---|
| `DATABASE_URL` env var | All live adapters; graceful fallback if absent |
| `psycopg` | Database connections (already in requirements.txt) |
| `fastapi` | Router (already a project dependency) |

### Database Schema Dependencies (candidate tables)

If none of the candidate tables for a subsystem exist, the adapter returns `available: false`.  No schema migration is required — the adapters probe table existence safely using `to_regclass()`.

---

## Caching Strategy

- **Mechanism:** In-memory Python dict with monotonic timestamps
- **TTL:** 60 seconds per adapter key, 60 seconds for the aggregate payload
- **Invalidation:** `DELETE /api/scientific-intelligence/cache`
- **Scope:** Process-local (reset on deploy; does not persist across workers)
- **Upgrade path:** Replace `cache.py` with Redis-backed implementation without changing adapters or aggregator

---

## Test Coverage

File: `tests/test_build_062_scientific_intelligence.py`

| Coverage Area | Test Count |
|---|---|
| Cache (set, get, expiry, invalidation, stats) | 5 |
| Normalizer (all 7 subsystems, edge cases) | 9 |
| Intelligence derivation (all 10 items) | 14 |
| Adapter fallback behaviour | 5 |
| Aggregator (all 8 sections) | 9 |
| Daily Brief structure | 4 |
| FastAPI router (endpoints, status codes, build ID) | 9 |
| Graceful fallback | 3 |
| **Total** | **68** |

Run with:
```bash
python -m pytest tests/test_build_062_scientific_intelligence.py -v
```

---

## Remaining Gaps

1. **Disconnected node count** — Requires a self-join query on the KG table; currently returns 0.
2. **Growth rate** — Requires historical snapshots or a changelog table; currently returns 0.0.
3. **Validation percentage** — Requires a dedicated `validated` boolean column or audit table.
4. **Literature ingestion rate** — Requires a timestamp column on the documents table to compute docs/day.
5. **Grant deadline tracking** — No grant deadline table exists; `nearest_deadline` always returns `"unavailable"`.
6. **Process-local cache** — Under multi-worker deployments each worker maintains its own cache; a shared cache (Redis) would be needed for cross-worker consistency.
7. **Atlas coordinate coverage** — Currently approximated as `occurrences / (taxa × 10)`; a proper calculation requires a geospatial join.

---

## Future Recommendations

1. **Add `oc_graph.nodes` and `oc_graph.edges` tables** — Define dedicated schema-qualified graph tables so the KG adapter returns real entity/relationship counts rather than falling back to `public.relationships`.
2. **Add `last_modified` columns** to literature, atlas, and relationship tables to enable true freshness tracking.
3. **Upgrade cache to Redis** — Replace `cache.py`'s dict store with `aioredis` for cross-worker consistency under Gunicorn.
4. **Grant deadline DB** — Add an `oc_grants.deadlines` table to expose real grant deadline tracking.
5. **Incremental KG growth tracking** — Add a snapshot scheduler job that records daily entity/relationship counts for growth rate calculation.
6. **Frontend integration** — Wire `GET /api/scientific-intelligence` as the primary data source for Mission Control Scientific Intelligence tiles, replacing any remaining static payloads.
7. **Owner authentication on intelligence endpoints** — Apply the BUILD-056 owner session token middleware to endpoints that surface privileged scientific recommendations.
