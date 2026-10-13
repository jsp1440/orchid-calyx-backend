# ORCHID CONTINUUM — CAPABILITY REGISTRY A3: IMPLEMENTATION REPORT

Contract: `oc-capability-registry-v1` · Observation date: 2026-10-13 · Author: Kimi (A3 assignment)

This document accompanies the populated registry at `registry/capability_registry.json`
and the engine at `runtime/oc_capability_registry.py`. Verified findings are
separated from assumptions and inaccessible information throughout.

---

## 1. Verified GitHub inventory (Phase 1)

Authenticated as `jsp1440`. Two priority repositories confirmed, plus ~28 further
`orchid-*` repositories.

| Repository | Default branch | Main HEAD observed | Open issues | Open PRs observed |
|---|---|---|---|---|
| `jsp1440/orchid-calyx-backend` | main | `6444eb696f46ed57daf5c45b6abed8c19e3ee471` (2026-10-10) | 281 | 50 listed (majority draft) |
| `jsp1440/Orchid-Continuum-Brain` | main | `b6833c056dceb6678b586cbbaddb96d4a26a9e85` (2026-10-03) | 118 | 49 listed (majority draft) |

Other repositories discovered (selection, all under `jsp1440`):
`OrchidContinuum`, `OrchidContinuumHarvester`, `orchid-continuum-frontend`
(140 open issues), `orchid-continuum-core`, `orchid-conservatory`,
`orchid-research-station(+frontend)`, `orchid-lexicon-botany`,
`orchid-continuum-control-panel`, `orchid-continuum-backend`,
`orchid-continuum-unified-backend`, `Orchid_Continiuum_Backend` (sic),
`-orchid-continuum-backend-clean`, `Orchid-continuum-clean`, `Orchid_harvester`,
`Orchid_Continuum_Online`, `orchid-continuum(-site/-frontend-v2/-website)` —
see Section 6 for the duplication audit.

### Key open PR chains (evidence for dependency graph)

- **Autonomy loop (Claude-owned — untouched):** Calyx `#1815 → #1817 → #1818`
  (stacked drafts), Brain `#253 → #255`; release candidate `#1806` (base
  `oc-autonomous-integration`); Brain `#244`.
- **Scientific convergence:** Brain `#230 → #232 → (#234, #236) → #247`
  (OAO → Lexicon → Matrix → KG → TraitBank → Literature evidence), Calyx
  `#1793 → #1794 → #1796 → #1812`, `#1811` (TraitBank backend), `#1813`.
- **Atlas:** Calyx `#1802`, Brain `#240` (ATLAS-EXPLORER-001).
- **Vision:** Brain `#235` (VISION-AI-001), Calyx `#1801` (IMAGE-INTEL-001).
- **Field Journal:** Calyx `#1785`, Brain `#132`.

### Existing architectural records located

- `runtime/brain_capability_registry.py` — evidence-pinned seed registry,
  contract `calyx-brain-capability-registry-v1`, 6 OPERATIONAL capabilities,
  fail-closed eligibility with cycle detection (blob SHA `5a878c4f`).
- `runtime/kernel_registry.py` — authoritative executor registry (28 KB).
- `docs/architecture/CALYX_SUPERSTRUCTURE_CAPABILITY_REGISTRY.md` —
  capability-memory contract ("performance can change routing preference,
  never privilege").
- `Orchid-Continuum-Brain/contracts/` — `autonomy_context_v1.json`,
  `cognitive_integration_capabilities_v1.json`, `decision_fabric_v1.json`,
  `federation_records_v1.json`, `homepage_readiness_v1.json`, `oc-parallel-v1.json`.
- Brain `14_ENGINEERING/GRAPH-001*` — Knowledge Graph blueprint and directive.

## 2. Neon access (Phase 1) — ACCESS LIMITATION

**The Neon connector returned zero accessible projects** (`list_projects` →
`[]`), and the connection is not scoped to a project, so no metadata
operations could be targeted. Per the assignment's read-only and access
discipline, **no Neon schema, table, or row-count inspection was possible**.

Consequences, recorded honestly in the registry:

- All `deployment` statuses are `unverified` or `not_deployed`; all
  `operational` statuses are `unverified`. None were inferred from the
  existence of migration files or code.
- `db_objects` fields reference migration files and runtime modules observed
  in GitHub only — they are *declared* persistence, not *confirmed* live schema.
- Repository-side migration inventory (Calyx) shows ~90 migration files
  including `migrations/knowledge_graph/0001_edge_temporal_supersession.sql`,
  `612/613` Matrix sessions/registry, `102a/102b` Lexicon, `103` Reasoning
  Ledger, `710` scientific language, `116` literature binding — none verified
  as applied to any live database.

## 3. Registry design (Phase 3)

Extends the existing capability-memory mechanism rather than replacing it.

- **Store:** `registry/capability_registry.json` — version-controlled,
  validated JSON. No Neon tables created.
- **Hierarchy:** Platform → Division → Module → Capability → (Subcapability →
  Implementation supported by schema). Single platform root; kind-ordering and
  cycle rules enforced at load.
- **Graph:** typed edges — `depends_on`, `implements`, `verified_by`,
  `consumes_data_from`, `produces_data_for`, `integrated_with`, `blocked_by`,
  `duplicates`.
- **Per-capability independent status axes:** `implementation`, `test`,
  `merge`, `deployment`, `operational` — each from a controlled vocabulary
  with first-class `unknown`/`unverified`; plus repositories, PRs, db_objects,
  evidence (source/ref/observed_at), resource requirements, blockers,
  next actions.
- **Engine:** `runtime/oc_capability_registry.py` — validation, deterministic
  idempotent `import_records` (never downgrades an informed status), hierarchy
  tree export, relationship graph export, fail-closed eligibility (compatible
  in spirit with `calyx-brain-capability-registry-v1`), and `autonomy_brief()`.
- **Determinism:** no wall-clock anywhere; exports are byte-identical for
  identical input (proven by tests).

## 4. Population (Phase 4)

49 nodes (1 platform, 4 divisions, 15 modules, 29 capabilities) and 15 typed
edges, populated from observed GitHub evidence only, covering Brain, Calyx,
the autonomy engine, Knowledge Graph, and scientific modules (Atlas, Matrix,
Vision AI, Literature, Lexicon, TraitBank, plus Harvesters, Conservatory,
Field Journal). Every status-bearing node carries evidence with source, ref
(path/PR/commit SHA), and observation timestamp.

Notable evidence-pinned findings:

- `calyx.capability-memory` is the only capability graded `test: passing` from
  direct artifact inspection (pinned test file SHA `34b39255`); the new
  registry engine's own tests pass (26/26, offline runner).
- The **implemented-but-unintegrated** set is large: autonomy loop, TraitBank
  v1, Vision AI slice, Literature evidence slice, OAO resolution, KG bridge,
  Atlas explorer API, Matrix contributor intake, Field Journal MVP — all open
  drafts, several in 3–5-deep stacked chains.
- **Repeatedly recreated code:** Brain-side `calyx_brain/` and `calyx/` dirs
  coexist with the entire Calyx backend repo; a `duplicates` edge records the
  overlap. Root-level `install_oc_graph_*.sh` (9 versions v1–v5 + canon +
  fixes) suggests repeated KG installer recreation.

## 5. Research → capability mapping (Phase 5)

Scope note: no journal-club corpus was reachable (Neon inaccessible; Brain
`13_LITERATURE_KNOWLEDGE_SYSTEM/` not enumerated this run). Entries below are
mapped to *existing* registry records — none is a new initiative. Verification
level is marked per entry; treat unverified rows as leads, not decisions.

| Finding | Maps to | Already exists? | Open source / license | Integration effort | Priority |
|---|---|---|---|---|---|
| PR #1775 assesses DeepSeek-Lattice-KG; PR #1819 builds a graph-grounded reasoning pilot | `oc.capability.knowledge-graph.oao-lexicon-matrix-kg-bridge`, `brain.reasoning-planning` | Partially (GRAPH-001 blueprint; pilot in draft) | Unverified — confirm license before any adoption | Medium | High — finish in-flight pilot first |
| PO/PATO/FLOPO ontology accession resolution | `lexicon.oao-accession-resolution` | Yes — PR #230 open draft | Public ontologies (open) | Low (merge existing PR) | High — unblock, don't rebuild |
| GloBI interaction data | `harvesters.globi-interactions` | Yes — merged harvesters | Open (GloBI) | — | Maintain; dedupe spend via #1716 |
| POWO/WFO taxonomy backbone | `harvesters.world-plants-intake` | Yes — 12 modules merged | Open | — | Maintain |
| Reference-image library + leakage-safe partitions (IMAGE-INTEL-001) | `vision-ai.vertical-slice` | In draft (#1801/#235) | n/a (internal) | Low (merge path) | High |
| RecurseML-style static analysis | autonomy CI | Decommissioned per Calyx #1816 / Brain #254 | n/a | — | Do not resurrect |

Rule applied: map to existing registry records first; nothing above creates a
new engineering initiative.

## 6. Resource & technical-debt audit (Phase 6)

No billing data was available; **no financial expenditure is claimed**. All
findings are from GitHub configuration and repo metadata.

**Verified:**

1. **~250 workflow files** in `orchid-calyx-backend/.github/workflows/`;
   `orchid-swarm-controller.yml` is 42.5 KB and `orchid-completion-lane.yml`
   43.6 KB.
2. **Excessive schedules:** Brain homeostatic replenisher runs
   `cron: '8,23,38,53 * * * *'` (every 15 min = 96 runs/day) *plus* on every
   issue event; Portfolio Steward runs hourly (`0 * * * *`); multiple
   continuous-completion/continuation workflows overlap in purpose. Brain
   PR #251 ("event-driven first — sparse safety-net schedules to fit the
   included Actions minutes") confirms minutes pressure.
3. **Unmerged PR accumulation:** ~99 open PRs across the two core repos, the
   large majority drafts, in deep stacked chains (up to 5 deep).
4. **Redundant/repeated development:** ≥8 backend-ish repos and ≥5
   frontend/site repos with overlapping scope; typo duplicate
   `Orchid_Continiuum_Backend`; `Orchid-continuum-clean`,
   `-orchid-continuum-backend-clean` as rebuild artifacts.
5. **Repo hygiene:** accidental committed artifacts — file named
   `app → main.py` (0 B), file named `python oc_system_check_v2.py` (28 KB),
   duplicate `ecuador_orchids.geojson` + `.geojson.json` (206 KB each),
   9.4 MB `orchid_atlas.html`, 1.8 MB `runtime/discovery_registry.json`,
   0-byte `orchid_schema.sql` / `orchid_dump.dump` / `orchid_atlas_light.html`.
6. **Missing execution limits (partially mitigated):** portfolio steward has
   fail-closed pipefail handling; replenisher has `timeout-minutes: 10` and a
   concurrency group — but swarm controller cadence and retry ceilings could
   not be fully enumerated in this pass.

**Recommendations (enforceable, no paid services):**

- Consolidate Brain replenisher to event-driven + a sparse (e.g. 6-hour)
  safety net, per the direction of Brain PR #251; set explicit
  `timeout-minutes` and `concurrency.cancel-in-progress` on all autonomy
  workflows.
- Merge-or-close review for the ~50 open drafts per repo, oldest first
  (Calyx #1445 dates to 2026-09-15); stacked chains merge base-up or close.
- Adopt the registry's `duplicates` edges as the canonical dedup tracker;
  archive redundant repos with a README pointer.
- Remove accidental artifacts and move large static data out of git history.
- Retain NO-API enforcement (`NO_API_MODE: "true"`, seen in portfolio steward)
  as a hard budget control; add retry ceilings to harvester workflows.
- Restore Neon read access to complete the database growth/retention audit.

## 7. Safe interface for autonomy (Phase 7)

Read-only consumption path, no new scheduler/queue/executor:

- `CapabilityRegistry.from_json("registry/capability_registry.json")` — load.
- `autonomy_brief()` → autonomy-engine export — surfaces unmet/blocked/
  untested/unmerged/missing-data/duplicated/integration-ready sets. Declares
  `read_only: true`, `execution_authority: false`, `publication_authority:
  false`, `compatible_with: calyx-brain-capability-registry-v1` so Brain's
  existing registry consumers can adopt it without contract breakage.
- `hierarchy_tree()` — accordion export for Mission Control.
- `relationship_graph()` — typed cross-module graph export.
- Refresh path: `scripts/export_capability_registry.py` is deterministic and
  offline; evidence imports go through `import_records` (idempotent,
  never-downgrading).

## 8. Verification (Phase 8)

- Branch: `kimi/capability-registry-a3` on `jsp1440/orchid-calyx-backend`
  (Kimi-prefixed branches already exist in this repo, e.g. PR #1800).
- Tests: `tests/test_oc_capability_registry.py` — 26 tests covering schema
  correctness, stable identities, parent-child rules, dependency integrity,
  deduplication, idempotent imports, provenance, unknown-state honesty, and
  no-credential hygiene. **26/26 passing** (offline runner; repo CI will run
  them under pytest).
- Draft PR opened against `main`; not merged. Claude's active branches
  (`claude/sharp-pasteur-e6c4r1*`, Calyx #1815/#1817/#1818, Brain #255) were
  not touched. No Neon mutation, no deployment, no costly CI triggered.
