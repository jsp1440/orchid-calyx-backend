# BUILD-OCB-010 — Knowledge Graph, Reasoning Engine, and Integration Layer

## Outcome

BUILD-OCB-010 adds an authenticated, modular Brain facade over the existing Orchid Continuum scientific graph. It does not replace `oc_graph`, the controlled publication lifecycle, the Concept Registry, Literature Intelligence, or Research Station. Scientific graph reads remain PostgreSQL-backed. Inference results are candidates and are never automatically promoted to canonical knowledge.

## Architecture

```text
Atlas / OREP / Calyx / Research Station / future clients
                         |
                  authenticated /brain API
                         |
       +-----------------+------------------+
       |                 |                  |
 structured graph   deterministic      connector registry
 reads/queries       rule engine        + provider boundary
       |                 |                  |
 canonical oc_graph nodes/edges       declared external adapters
       |                 |
 controlled publication gate     candidate inference only
```

The scientific graph is the canonical existing `oc_graph.kg_nodes` and `oc_graph.kg_edges` property graph. Every scientific relationship is an edge. Stable canonical keys preserve identity across PostgreSQL and Neo4j projections. The outreach graph is deliberately separate under `oc_brain.outreach_nodes` and `oc_brain.outreach_edges`; social engagement history cannot acquire scientific authority by sharing a table with scientific evidence.

## Directory structure

```text
app/brain/
  connectors.py   BrainConnector protocol, registry, entry-point discovery
  providers.py    abstract AI-provider protocol and supported descriptors
  reasoning.py    deterministic rules and evidence-bearing results
  routes.py       authenticated Brain API
  schemas.py      strict request contracts
migrations/
  104_orchid_continuum_brain.sql
  104_orchid_continuum_brain_rollback.sql
tests/
  test_build_ocb_010_brain.py
  test_build_ocb_010_migration.py
```

## Graph model

Scientific node types already supported by the canonical graph vocabulary and source adapters include taxonomy, genus/taxon, habitat/geography, traits, climate, phenology, pollinators, mycorrhizae, literature/evidence, images, observations, cultivation, conservation, and provenance objects. Additional types such as DNA sequences, collectors, vouchers, and protected areas use the same node contract and must enter through the existing controlled publication process.

Scientific edge examples:

```text
(taxon: Phragmipedium kovachii)-[:HAS_POLLINATOR]->(pollinator: Bombus sp.)
(taxon: Masdevallia veitchiana)-[:OCCURS_IN]->(habitat: Cloud forest)
(assertion)-[:SUPPORTED_BY]->(literature record)
```

All inference evidence contains graph edge IDs, source table and primary key, evidence class, available DOI/citation, and confidence. `reasoning_chain` is a compact, reviewable rule trace—not private model chain-of-thought.

## Reasoning model

The engine provides explicit rule entries for habitat similarity, pollinator similarity, cultivation similarity, conservation risk, evolutionary relationship, probable mycorrhizal partners, missing ecological interactions, climate compatibility, restoration suitability, hybrid compatibility, likely flowering period, geographic expansion, and likely undiscovered populations.

Rules use either direct asserted relationships or shared-target graph patterns. Confidence is deterministic: rule weight multiplied by the minimum supporting edge confidence. Inputs are sorted by graph edge ID, results by descending confidence then candidate ID. Identical graph snapshots and requests therefore produce identical responses.

This first engine is intentionally conservative:

- results have `candidate_inference` status;
- every response says human review is required;
- no inference route writes to `oc_graph`;
- no inference bypasses the existing publication authorization and provenance gates;
- absence of supporting edges returns an empty result, never an invented fact.

## Connector framework

Python protocol:

```python
class BrainConnector(Protocol):
    id: str
    name: str
    version: str
    capabilities: tuple[str, ...]
    def execute(self, action: str, payload: dict) -> dict: ...
    def health(self) -> dict: ...
```

Modules can be discovered from the `orchid_continuum.brain_connectors` Python entry-point group. Identity collisions fail closed. Crossref, OpenAlex, Semantic Scholar, PubMed, GBIF, BHL, and JSTOR are registered as non-operational manifests. This makes integration capability visible without performing surprise network calls or pretending credentials are configured. JSTOR is metadata-only. Operational adapters are a later credentialed deployment slice.

Equivalent TypeScript consumer contract:

```typescript
export interface BrainConnector {
  readonly id: string;
  readonly name: string;
  readonly version: string;
  readonly capabilities: readonly string[];
  execute(action: string, payload: Readonly<Record<string, unknown>>): Promise<Record<string, unknown>>;
  health(): Promise<{ status: string; operational: boolean }>;
}

export interface InferenceResult {
  candidate_node_id: number;
  confidence: number;
  evidence: readonly GraphEdge[];
  supporting_citations: readonly Citation[];
  reasoning_chain: readonly RuleTraceStep[];
}
```

## AI provider boundary

`AIProvider` supplies `complete()` and `health()` without binding the Brain to an SDK. OpenAI, Anthropic, Gemini, Llama, and local execution are declared provider families. No provider is enabled and no model output becomes knowledge automatically. A future provider adapter must preserve evidence and pass results through governance.

## Database schema

Migration 104 creates only the new `oc_brain` schema:

- `connector_registrations`: versions, capabilities, enablement and secret-reference names (never secret values);
- `inference_runs` and `inference_results`: optional governed persistence for candidates and review state;
- `literature_records` and `literature_graph_links`: normalized provider metadata with source hashes and explicit graph links;
- `outreach_nodes` and `outreach_edges`: organizations, universities, gardens, zoos, societies, labs, educators, learners, citizen scientists, volunteers, funders and channels with expertise, audiences, interests, collaboration and engagement edges.

Foreign keys from scientific inference/literature links point to canonical `oc_graph.kg_nodes`. Migration 104 is additive and idempotent. The rollback is separate and intended only for disposable validation or an explicitly approved rollback.

## PostgreSQL and Neo4j compatibility

PostgreSQL is authoritative. A Neo4j projection maps each active `kg_nodes` row to a node labeled by `node_type`, using `canonical_key` as the unique identity, and each active `kg_edges` row to a relationship typed by `edge_type`. `source_table`, `source_pk`, evidence class, confidence, rule name, and JSON payload remain relationship properties. Outreach uses a distinct database or `OutreachEntity` label namespace.

Neo4j is a derived read/index projection only. Writes must return through PostgreSQL's controlled publication workflow. A Neo4j node ID must never replace `canonical_key` or PostgreSQL identity.

## API

All endpoints require the existing owner-session or API-key authentication:

- `GET /brain/node/{id}`
- `GET /brain/relationships/{id}`
- `GET /brain/reason`
- `POST /brain/infer`
- `POST /brain/query`
- `POST /brain/connect`

`/brain/query` accepts bounded structured filters rather than caller-supplied SQL or Cypher. `/brain/connect` permits only `describe` and `health` in this slice. Connector manifests cannot make network calls.

## Example inference queries

```http
GET /brain/reason?subject_node_id=42&inference_type=habitat_similarity&limit=10
```

```json
POST /brain/infer
{
  "subject_node_id": 42,
  "inference_type": "probable_mycorrhizal_partner",
  "limit": 10
}
```

```json
POST /brain/query
{
  "node_type": "taxon",
  "edge_type": "has_pollinator",
  "limit": 50
}
```

## Migration and rollout plan

1. Apply all existing graph/publication migrations and verify `oc_graph.kg_nodes` exists.
2. Back up the target database and apply migration 104 through the normal release process.
3. Deploy the authenticated Brain routes with connector manifests disabled.
4. Validate structured reads and deterministic inference against a non-production graph snapshot.
5. Add provider-specific literature adapters one at a time with rate limiting, source hashing, licensing review, and credential references.
6. Add governed inference persistence and review workflows before any candidate can reach controlled publication.
7. Build a read-only Neo4j projection only if PostgreSQL traversal performance justifies it.
8. Add outreach recommendation rules only after consent, privacy, retention, and engagement-governance policy is approved.

## Known limitations

- External literature connectors are contracts/manifests, not live network clients.
- Candidate inference persistence tables are created, but current inference endpoints remain read-only.
- The deterministic rules demonstrate auditable graph-pattern inference; domain experts must calibrate and approve rule weights and vocabulary aliases.
- Outreach recommendation engines are schema-ready but intentionally not operational until privacy and consent governance exists.
- PostgreSQL `all_nodes`/`all_edges` queries are suitable for the bounded initial slice, not very large graph workloads; indexed repository query methods are the next performance step.
- No frontend, Lovable page, frontend route, styling, production environment, or existing API was changed.
