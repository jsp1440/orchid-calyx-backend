# CI-BASELINE-001F — Runtime, science, and Knowledge Graph contract repair

Date: 2026-08-07
Issue: #524
PR: #597
Base: `bb33941b5a53390bfc6cf40fb33e9ddaa5a1613a`

## Purpose

Continue CI-BASELINE-001 from the current mainline without restoring retired APIs or weakening governance. The prior exact broad diagnostic after #595/#597 contract cleanup had three remaining failures, all caused by the Knowledge Graph having expanded from eight to fifteen adapters while the source registry still described only the original eight.

## Repairs

### Current runtime and executive contracts

Historical node-level assertions for retired `/api/runner/*` and unauthenticated executive routes are no longer treated as the current API contract. Their replacements remain blocking:

- `tests/test_calyx_runtime_001n_authenticated_runtime_api.py`
- `tests/test_mission_control_telemetry_001a_executive_state.py`

No legacy write route was restored and no authentication requirement was weakened.

### Scientific audit contract

`tests/test_build_046_scientific_priorities.py` now validates the authoritative provenance-first science registry contract via `runtime.science_registry.audit_result`. Audit findings remain `audit_only`, `unreviewed`, and `promoted_claims=false`.

### Live graph audit test determinism

The fake cursor in `tests/test_calyx_live_graph_audit.py` now matches the specific broken-target LEFT JOIN before generic image-count SQL, removing an order-dependent negative linked-image result without changing production graph-audit logic.

### Fifteen-domain Knowledge Graph registry

`runtime/knowledge_graph/source_registry.py` now registers every current adapter domain:

- occurrences
- geography
- habitat
- climate
- elevation
- traits
- glossary
- literature
- evidence
- pollinators
- mycorrhiza
- conservation
- molecular
- education
- media

The eight already verified source projections remain enabled: occurrences, traits, pollinators, mycorrhiza, conservation, climate, literature, and media.

The seven expanded domains are explicit fail-closed registrations until their production projection, provenance, and taxonomy mapping are verified:

- geography — `oc_geo.taxon_places`
- habitat — `oc_habitat.taxon_habitats`
- elevation — `oc_env.taxon_elevation_profiles`
- glossary — `oc_glossary.taxon_terms`
- evidence — `oc_claims.evidence_item`
- molecular — `oc_phylogeny.taxon_molecular_records`
- education — `ocu.taxon_learning_objects`

For these seven domains: `enabled=false`, `sql=null`, BUILD-064 metadata status is `BLOCKED`, and `blocked_reason` is mandatory. This prevents silent omission while also preventing an unverified production query from becoming executable.

## Validation evidence before final exact-head run

On earlier #597 head `591273b3a7241390e8670310a03bd036e2a08895`, BUILD-087B run `31235890178` passed the strict current contracts and measured the broad suite at:

- 3 failed
- 1,943 passed
- 16 skipped
- 10 deselected
- 3 subtests passed

All three failures were the Knowledge Graph domain/source-registry mismatch addressed here.

On implementation head `155b6ba147c2e1a6057f49a0ff0ff8438b77e235`, BUILD-087B run `31236182603` passed:

- BUILD-087B focused PostgreSQL validation: 18 passed
- BUILD-082 through BUILD-087 regression matrix: 108 passed
- Journalism non-HTTP contract: 28 passed, 11 deselected
- canonical Journalism Brain routes: 4 passed
- canonical runtime/executive contract: 7 passed
- focused science/live-graph repair: 5 passed

The KG-focused step then reported one remaining assertion that still compared all adapters to only the enabled-domain set. The subsequent branch commit `f5f959073ce10dd974a79e6811ec940924dbd931` corrected that distinction: all fifteen adapters must be registered, while `enabled_queries()` remains the verified eight.

Workflows created automatically for the Copilot-authored `f5f959...` commit returned `action_required`; they are not counted as executable validation evidence.

## Governance / non-authority

This work does **not** authorize or perform:

- taxonomy activation or promotion;
- scientific publication;
- production database migration;
- production Knowledge Graph mutation;
- Azure provisioning;
- enabling the seven unverified source domains;
- restoration of retired runtime write routes;
- weakening of owner/API-key authentication;
- bypass of the external trusted-supervisor boundary for executable repository code.

Final exact-head CI evidence and the final broad-suite result must be appended before merge.