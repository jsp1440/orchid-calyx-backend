# TRAITBANK-002 — Integration stage: supersession, shared identifiers, Calyx and Matrix evidence, literature handoff

**Stacked on:** TRAITBANK-001 (jsp1440/orchid-calyx-backend#1811).
**Classification:** `CONTINUE`.
**Coordinates with:** #901 (KG materialization), #1819 (graph-grounded reasoning), #1810 (FIL-001B), #1824 (bridge confidence fix).

## 1. Superseding a record without touching the original

Superseding never runs an UPDATE or DELETE on a stored assertion; the v1 append-only trigger would refuse one anyway. Instead, a decision is one row in `oc_traitbank.assertion_supersessions`. That table is also append-only.

Each decision row records:
- the original;
- the successor (or none, for a retraction);
- the kind;
- a reason (at least 10 characters, privacy-screened);
- a review reference;
- who decided;
- a content hash.

| Kind | Successor | Rule |
|---|---|---|
| `corrected` | required | Same trait, same taxon. |
| `reidentified` | required | Same trait, **different** taxon. This is the only kind that may move evidence to another taxon. |
| `reanalysed` | required | Same trait, same taxon. |
| `duplicate_of` | required | Same trait, same taxon. |
| `retracted` | none | The record is withdrawn by its source or a reviewer. |

**Chain rules:**
- A record can be superseded once.
- A successor must be current when the decision is recorded.
- Chains are therefore linear and cannot loop.
- Replaying an identical decision is a no-op; a different decision for the same original is refused.

**Reads:**
- Current views (taxon, genus, conflicts, Calyx, Matrix, evidence, pairwise) use only current records.
- `GET /assertions/{id}` still returns the original byte-for-byte, with:
  - `supersession.effective_state = SUPERSEDED`;
  - `stored_evidence_state` unchanged;
  - the decision itself;
  - the full chain `history`.
- `/characters/{trait}` lists superseded records with flags.

A conflict is resolved this way. One side is retracted or superseded with a reason and a review reference. Both sides remain queryable.

**Write path:** CLI only, dry-run by default:

```
python -m app.traitbank.cli supersede ID --kind corrected --by SUCCESSOR --reason TEXT --review-reference REF --decided-by NAME [--apply]
```

## 2. Shared evidence identifiers and taxon mapping

`oc_traitbank.evidence_crosswalk` is written once per assertion at ingestion.

| TraitBank | Shared key | Consumer |
|---|---|---|
| `tb:lit:{paper}:{measurement}` | `measurement:{paper}:{measurement}` | #901 `measurement_of` source node (`canonical_key`) |
| `tb:lit:{paper}:{claim}` | `{CLAIM_TYPE_TO_NODE_TYPE[claim_type]}:{paper}:{claim}` | #901 claim node |
| `tb:eol:{eol_pk}` | none (no graph node exists to point to) | — |
| `source_id` (`doi:…`, `paper:…`, `eol-traitbank:resource:…`) | `source_document_id` | #1819 evidence packet |
| `taxon_id` (`taxonomy_id`) | `oc_graph.kg_nodes` with `node_type='taxon'`, `source_pk=taxonomy_id` | Existing governed Matrix/trait join; #1819 focal node |

`interop.KG_CLAIM_NODE_TYPES` mirrors #901's mapping. #1819's payload allow-list and `EvidenceItem` keys are pinned in `interop.py` as well.

`tests/test_traitbank_interop.py` compares these copies against the real modules once those are on the base. Before submitting, the comparison was run locally against #901 at `ecaecc9` and #1819 at `c9da136`, and passed.

A taxon id with no KG node, or with more than one active node, is left unmapped rather than guessed.

### Level, scope and confidence travel downstream

#1819 copies exactly six payload keys from a graph edge. TraitBank puts `assertion_level=…;scope_basis=…;confidence_state=…` into `qualifier`, the one free field among them. A specimen measurement therefore reaches graph-grounded reasoning labelled as specimen evidence.

**Proposal for #901:** `measurement_of` edges currently carry only `subject_entity_id`. They should carry `interop.graph_edge_payload(...)`; otherwise a single-specimen measurement materializes as an unqualified measurement of the species.

## 3. Calyx evidence retrieval

`GET /api/traitbank/taxa/{taxon_id}/evidence[?trait_id=]` returns `EvidenceItem`-shaped records (`interop.evidence_item`):

- `domain` is `traits`.
- `edge_type` is `has_trait` for taxon-level assertions and `has_trait_evidence_from_individuals` otherwise.
- `anchor_state` is `ANCHORED` when the stored verbatim excerpt is present. The citation carries the citation, locator, excerpt and license.
- Conflicts are named on both sides.
- The packet also returns explicit `gaps`: `NO_TAXON_LEVEL_ASSERTION`, `CONFIDENCE_NOT_REPORTED`, `MISSING_VALUES_RECORDED` and `NO_TRAITBANK_EVIDENCE`.
- `confidence_is_probability` is `false`.

## 4. Matrix individual-observation evidence and species comparison

`app/traitbank/matrix_adapter.TraitBankMorphologyAdapter` implements the existing `MatrixEvidenceAdapter` protocol for the `morphology` dimension (`GET /api/traitbank/pairwise`).

- Only current, uncontested, **taxon-level** assertions are scored.
- Specimen, population and observation records are counted in `limitations` and never contribute to a species-to-species score.
- `confidence` is the weakest reported value only when every compared assertion reported one. Otherwise it is `None`.

Individual evidence remains visible through the `trait_individual_evidence` dimension of `/api/traitbank/matrix` (from TRAITBANK-001).

## 5. Literature-extraction handoff

`app/traitbank/handoff.py` reads the extraction pipeline's own `LiteratureResultRepository` (`paper.json` bundles). It does not walk the directory itself.

```
python -m app.traitbank.cli ingest-literature-root ROOT [--limit N --after ID --apply --ingested-by NAME]
```

- **Bounded:** at most 200 papers per call.
- **Resumable:** `--after` plus `resume_after_paper_id`.
- **Idempotent:** one content-keyed batch per paper.
- **Fault-isolated:** a malformed paper is reported as `PAPER_INVALID` and does not stop the run.
- **Dry-run by default.**
- **Not scheduled.** A recurring run would be added to the existing scheduling under its own owner-approved change.

## Validation (local; PostgreSQL 16, Python 3.13, `ruff==0.16.8`)

- `tests/test_traitbank_interop.py`: 7 passed and 2 skipped. With #901 and #1819 modules present, all 9 passed.
- `tests/test_traitbank_002_postgres.py`: 10 passed.
- The TRAITBANK-001 suites, with the v2 migration applied: still passing.
- **Mutation sweep:** 8 of 8 guard mutants were killed, with a control run before and the restored tree green after. The guards:
  1. the current-only filter;
  2. the successor-must-be-current rule;
  3. the taxon-change rule;
  4. idempotent replay;
  5. exclusion of individual records from species scoring;
  6. no partial confidence;
  7. the level carried in `qualifier`;
  8. the v2 append-only trigger.

## Not yet done

- **EOL acquisition** is prepared but not executed. See `docs/TRAITBANK-PILOT-001.md`; it is approval-gated.
- **KG publication:** #901 publishes graph edges. TraitBank never writes `oc_graph`.
- **GGR reader:** wiring #1819's reader to call `/evidence` is #1819's change.
- **Supersession write route:** there is no HTTP route for supersession. A reviewed UI or route would be a separate, owner-approved change.
