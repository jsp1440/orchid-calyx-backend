# BUILD-016 — Knowledge Gap Discovery

BUILD-016 turns Calyx's runtime self-discovery memory into a first-pass Orchid Continuum knowledge-gap discovery layer.

## Purpose

BUILD-014 lets Calyx discover its runtime modules and capabilities. BUILD-015 lets Calyx remember those discoveries over time. BUILD-016 uses that memory to identify thin or missing scientific and governance coverage areas that should become research or engineering tasks.

## Added

- `runtime/knowledge_gap_discovery.py`
- Knowledge-gap endpoints on the existing `/api/runner` router
- File-backed latest knowledge-gap report under `runtime/knowledge_gaps/latest.json`
- Tests for gap discovery, domain coverage, queue generation, and dashboard output

## API endpoints

- `POST /api/runner/knowledge-gaps/discover`
- `GET /api/runner/knowledge-gaps`
- `GET /api/runner/knowledge-gaps/latest`
- `GET /api/runner/knowledge-gaps/domains`
- `GET /api/runner/knowledge-gaps/priorities`
- `GET /api/runner/knowledge-gaps/queue`
- `GET /api/runner/knowledge-gaps/dashboard`

## Behavior

The knowledge-gap engine reads the latest discovery snapshot, checks runtime/module/capability coverage against Orchid Continuum domains, ranks weak coverage areas, and emits a queue of proposed actions.

Initial tracked domains:

- Taxonomy
- Images
- Occurrences
- Pollination
- Mycorrhiza
- Conservation
- Literature
- Traits
- Governance

## Acceptance check after deploy

1. Run `POST /api/runner/knowledge-gaps/discover`.
2. Run `GET /api/runner/knowledge-gaps/dashboard`.
3. Run `GET /api/runner/knowledge-gaps/queue`.
4. Confirm responses report `BUILD-016`.
5. Confirm at least one ranked gap or action exists.

## Next build

BUILD-017 should begin connecting these knowledge gaps to real Brain tables, row counts, source provenance, and missing-field diagnostics instead of relying only on runtime/module coverage signals.
