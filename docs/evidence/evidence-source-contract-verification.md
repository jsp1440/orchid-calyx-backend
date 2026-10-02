# Evidence Source Contract Verification

**Date**: 2026-09-15  
**Issue**: #1729  
**Domain**: evidence  
**Query ID**: evidence_unverified_v1  
**Status**: BLOCKED (pending verification)

## Current Registration State

```python
_EVIDENCE = _blocked(
    "evidence", 
    "evidence_unverified_v1", 
    "oc_claims.evidence_item"
)
```

Registry location: `runtime/knowledge_graph/source_registry.py:362`

Blocked reason:
> Source table is known from the adapter contract, but its production projection and backbone taxon mapping have not been verified for a publication build. Registered explicitly and disabled fail-closed.

## Source Table Contract

**Primary source**: `oc_claims.evidence_item`  
**Link table**: `oc_claims.claim_evidence_link` (optional)  
**Domain source reference**: `runtime/knowledge_graph/domain_sources.py:50-53`

```python
DomainSource(
    "evidence", 
    "production",
    "oc_claims.evidence_item + claim_evidence_link",
    "evidence", 
    "supported_by_evidence",
    "Model claims as assertion/evidence nodes, not raw edges."
)
```

## Graph Adapter Requirements

Adapter location: `runtime/knowledge_graph/adapters.py:134-139`

### Required Schema

```python
EVIDENCE_ADAPTER = _make_adapter(
    domain="evidence", 
    node_type="evidence", 
    edge_type="supported_by_evidence",
    source_table="oc_claims.evidence_item",
    label_fields=("title", "evidence_type", "claim_label"),
    payload_fields=("claim_id", "evidence_type", "citation", "source_uri", "excerpt", "review_state"),
)
```

### Contract Columns (Required)

The adapter requires at minimum:
- `source_pk` — unique identifier for each evidence record
- `taxon_pk` — reference to taxon node in the Knowledge Graph backbone (`oc_graph.kg_nodes`)

### Contract Columns (Optional but Used)

- `title` — evidence title (label field)
- `evidence_type` — type of evidence (label and payload)
- `claim_label` — claim description (label field)
- `claim_id` — reference to associated claim (payload)
- `citation` — bibliographic citation (payload)
- `source_uri` — URI to evidence source (payload)
- `excerpt` — relevant text excerpt (payload)
- `review_state` — review/publication state (payload)

## Verification Requirements

Before enabling this source, the following must be verified and recorded:

### 1. Source Table Existence and Schema

**Required verification**: Confirm `oc_claims.evidence_item` exists in production with:
- Exact column names and types matching the adapter contract
- Non-null `source_pk` uniqueness constraint
- Referential integrity or existence check for `taxon_pk` values

**Evidence location**: Run read-only catalog probe (e.g., `information_schema.columns`)  
**Success criteria**: All required columns present with compatible types

### 2. Taxon Identifier Mapping Strategy

**Current assumption**: "direct" taxon mapping
- Registry setting: `taxon_mapping="direct"` (inherited from `_blocked()` default)
- Meaning: `taxon_pk` in `oc_claims.evidence_item` directly references `oc_graph.kg_nodes.source_pk` with `node_type='taxon'`

**Required verification**: Confirm that `taxon_pk` values in `oc_claims.evidence_item`:
- Match existing taxon nodes in `oc_graph.kg_nodes` where `node_type='taxon'`
- Use the same identifier scheme (integer taxonomy_id)
- Have no orphan records (all taxon_pk values resolve)

**Evidence location**: SQL join query against production database  
**Success criteria**: >95% or 100% of evidence records resolve to valid taxon nodes

### 3. Source Record Uniqueness

**Required verification**: Confirm that `source_pk` values are:
- Unique within `oc_claims.evidence_item`
- Stable across builds (deterministic, not generated at ingest time)
- Not composite/multi-part identifiers requiring special parsing

**Evidence location**: Production schema inspection; sample query  
**Success criteria**: `SELECT COUNT(DISTINCT source_pk) = SELECT COUNT(*)`

### 4. Provenance and Publication Readiness

**Required verification**: Understand the content and status of `review_state`:
- What states are present in production? (e.g., "draft", "published", "reviewed")
- Should all states be included in the graph projection, or only published/reviewed?
- Is there an approval or publication gate that prevents unreviewed evidence from reaching the graph?

**Evidence location**: `oc_claims.evidence_item` sample data; schema documentation  
**Success criteria**: Clear policy documented on inclusion criteria by review_state

### 5. Rights and Attribution

**Required verification**: Confirm sources are citable and rights-compatible:
- All evidence records carry proper source attribution in `citation` or `source_uri`
- Licenses permit Knowledge Graph republication
- No classified, private, or restricted-locality data below 10km resolution

**Evidence location**: Sample evidence records; data provenance policy  
**Success criteria**: No rights, license, or privacy violations identified

## SQL Projection (To Be Specified)

Once verification completes, an enabled source query must be defined following the pattern used by other verified sources:

```python
_EVIDENCE = _verified(
    domain="evidence",
    query_id="evidence_unverified_v1",
    expected_tables=("oc_claims.evidence_item", "oc_graph.kg_nodes"),
    taxon_mapping="direct",  # or "name_join" if mapping requires scientific-name join
    optional_columns=(
        "title", "evidence_type", "claim_label", "claim_id", 
        "citation", "source_uri", "excerpt", "review_state",
    ),
    provenance_columns=("citation", "source_uri"),  # How to track evidence sources
    quality_columns=("review_state", "evidence_type"),  # Confidence/status fields
    sql="""
        select e.evidence_id as source_pk,
               e.taxon_id as taxon_pk,
               e.title, e.evidence_type, e.claim_label, e.claim_id,
               e.citation, e.source_uri, e.excerpt, e.review_state
        from oc_claims.evidence_item e
        where e.taxon_id is not null
          and e.review_state in ('published', 'reviewed')  -- or appropriate filter
          and exists (select 1 from oc_graph.kg_nodes k
                      where k.node_type='taxon' and k.source_pk=e.taxon_id::text)
    """
)
```

## Blocking Justification

This source remains **disabled and fail-closed** until verification is complete because:

1. **No graph projection is safe without verification**: Enabling an unverified source could silently omit evidence or create orphan nodes linking to non-existent taxa.

2. **Taxon mapping must be proven**: A wrong taxon_pk-to-kg_nodes mapping would corrupt the graph and potentially create false scientific claims.

3. **Publication governance requires explicit inclusion**: The `review_state` field indicates this source has published and unpublished records; inclusion policy must be explicit, not assumed.

4. **Evidence is scientific authority**: Graph evidence edges are read by downstream scientific consumers; only vetted, properly attributed sources may contribute.

## Next Steps

1. **Read-only catalog probe**: Run deterministic schema inspection against production to confirm table and column existence.
2. **Sample validation query**: Count record types, check taxon_pk resolution rate, identify review_state distribution.
3. **Schema documentation review**: Confirm adapter expectations match actual production schema.
4. **Rights and attribution audit**: Verify licenses and attribution standards.
5. **Enable or document reason for continued blocking**: Once verified, enable by moving to `_verified()` and adding SQL. If blockers are found, update `blocked_reason` with specific findings.

## References

- Issue: https://github.com/conceited-ai/orchid-continuum/issues/1729
- Source registry: `runtime/knowledge_graph/source_registry.py`
- Domain sources: `runtime/knowledge_graph/domain_sources.py`
- Adapter contract: `runtime/knowledge_graph/adapters.py::EVIDENCE_ADAPTER`
- OC-BRAIN-PULSE: `scripts/oc_brain_pulse.py::source_registry_gap_candidates()`
