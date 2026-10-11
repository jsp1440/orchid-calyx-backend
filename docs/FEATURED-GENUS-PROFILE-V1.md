# Featured Genus Profile & Selection Contracts (v1)

Status: implemented on `agent/featured-genus-profile-v1`.
Contracts: `featured-genus-profile/v1`, `featured-genus-selection/v1`.

## Purpose

This build turns the Featured Genus from a media panel into a composed,
evidence-stated scientific exhibit, per the Brain design contract
(`docs/design-book/03-featured-genus-contract.md` in Orchid-Continuum-Brain):
one coherent genus payload composed from canonical sources, with missing
evidence visibly distinguished from confirmed absence.

It deliberately introduces **no new scheduler, no new media pipeline, and no
second knowledge graph**. Everything is composed from existing proven sources:

| Block | Source | Failure semantics |
| --- | --- | --- |
| `taxonomy` | `public.orchid_taxonomy` | Acceptance gate; failure fails closed with 503 |
| `media` | `public.orchid_images` via the shared approved-selection policy in `app.routers.orchid_widgets` | `unavailable`, profile otherwise intact |
| `habitat` | `oc_widget.v_genus_of_day_cards` | `unknown` (no card) or `unavailable` (query failed); never zero elevation |
| `knowledge_graph` + `domains` | `oc_graph` via `runtime.knowledge_graph` traversal (same service as `/api/knowledge-graph/genus/{genus}`) | `unknown` (no focal node) or `unavailable` |

## Endpoints

### `GET /api/featured-genus/v1/selection?at=<epoch-seconds>`

Reproducible Featured Genus selection.

- Deterministic 12-hour UTC rotation, identical math to the frontend
  `featuredGenus.ts` contract (`floor(epoch / 43200) % len(candidates)`), so
  backend selection and frontend identity agree without any coordination.
- `at` makes any window reproducible for review and tests.
- An editorial override lives in
  `runtime/requirements/featured_genus_selection_policy.json` (versioned,
  reviewed, committed). It requires `genus`, `reason`, `reviewer`,
  `expires_at`; genera outside the curated rotation additionally require
  `evidence_reviewed: true` so under-evidenced genera are not repeatedly
  featured. Expired/malformed overrides are reported and ignored, never
  silently applied.
- The response always reports `source` (`editorial_override` |
  `deterministic_rotation`), the full override status record, and the
  deterministic identity for auditability.

### `GET /api/featured-genus/v1/profile/{genus}?media_limit=12`

Composed genus scientific profile. `status` is `ok` or `invalid_genus`
(malformed input is HTTP 400, as with `/api/media/genus`).

Every evidence block carries an explicit state:

- `known` — a canonical source returned linked evidence;
- `unknown` — the source answered and holds nothing linked here yet
  (**a knowledge gap, never biological absence, never a zero**);
- `unavailable` — the source did not answer; no fallback claim is substituted.

`domains` covers taxonomy, media, occurrences, traits, literature,
pollinators, conservation, geography, habitat, climate, elevation, and
mycorrhiza from Knowledge Graph domain coverage. `gaps` lists domains whose
state is `unknown`; an unavailable graph yields no gap claims at all.
`provenance` names the source of every block, and `notes` restate the
evidence-state rules for downstream consumers.

## Media policy sharing

`select_approved_genus_media` / `query_approved_genus_media` in
`app/routers/orchid_widgets.py` are now the single selection policy for both
`/api/media/genus/{genus}` and the profile composer: one photograph per
species, no repeated URLs, herbarium/plate/document exclusion, mandatory
provenance fields. Endpoint behavior is unchanged (existing contract tests
pass unmodified).

## Tests

- `tests/test_featured_genus_selection.py` — rotation math vs. the frontend
  contract, reproducibility, canonical-genus boundary, override
  active/expired/rejected paths, malformed/missing policy degradation.
- `tests/test_featured_genus_profile.py` — composition with faked connections
  (no database opened), invalid genus, unknown-vs-unavailable discipline,
  media-policy sharing, 503 fail-closed taxonomy, route 400/CORS behavior.

Both suites run under `python -m pytest tests/` with no database connection.
