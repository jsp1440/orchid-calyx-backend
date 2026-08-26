# BUILD-1184 — Continuum Engineering Memory v1 (completion record)

- **Issue:** #1184 — P0: Continuum Engineering Memory v1 — shared verified memory for coding agents
- **Classification:** `NEW` (no existing engineering-memory table/service; the
  existing `runtime/brain_integration.py:engineering_memory_harvester` is a
  read-only BUILD-report summarizer, not a storage/retrieval layer, so this
  extends the substrate rather than duplicating it).
- **Lane:** Lane 1 (Brain mission / reasoning + engineering substrate).
- **Integration target:** draft PR against `main` (no merge; owner-gated).

## Acceptance criteria → evidence

| Requirement (#1184) | Status | Evidence |
| --- | --- | --- |
| Data model: runs, lessons, retrievals | ✅ | `app/engineering_memory/models.py`, `migrations/082_engineering_memory.sql` |
| Lexical retrieval first; pgvector optional | ✅ | in-process BM25 in `retrieval.py`; optional `EmbeddingAdapter`; no pgvector dependency |
| No raw prompts/conversations by default | ✅ | schemas `extra="forbid"`; `test_raw_prompt_*` |
| Secret redaction before persistence | ✅ | `redaction.py`; `test_secrets_are_redacted_before_persistence` |
| Protected-locality reject/reduce | ✅ | `test_protected_locality_reduced_by_default_and_rejected_when_strict` |
| Explicitly non-scientific | ✅ | fixed `evidence_class`, DB CHECK; `test_engineering_memory_cannot_be_relabeled_as_scientific`, `test_returned_lesson_marked_non_scientific_with_provenance` |
| Fail closed on malformed writes | ✅ | `test_malformed_classification_fails_closed`, `test_lesson_requires_provenance` |
| Scope isolation | ✅ | `test_scope_isolation_prevents_cross_repository_retrieval`, `test_source_run_from_other_scope_is_rejected` |
| Invalidated/expired excluded | ✅ | `test_invalidated_and_expired_lessons_are_not_returned` |
| Verified ranks above candidate | ✅ | `test_verified_lesson_outranks_comparable_candidate` |
| Cap at 5 + context budget | ✅ | `test_retrieval_capped_at_five`, `test_retrieval_respects_character_budget` |
| Provenance on every result | ✅ | `test_returned_lesson_marked_non_scientific_with_provenance` |
| Deterministic fingerprint invalidation | ✅ | `test_fingerprint_divergence_invalidates_deterministically` |
| Metrics: measured zero vs unavailable | ✅ | `test_metrics_distinguish_measured_zero_from_unavailable` |
| Migration upgrade + rollback convention | ✅ | `082_*.sql` + downgrade; `test_migration_files_present_and_rollback_defined`, `test_orm_metadata_round_trips` |
| API surface (7 routes, owner auth) | ✅ | `routes.py`; `tests/test_engineering_memory_api.py` |
| Deterministic end-to-end proof | ✅ | `test_end_to_end_vertical_slice` (capture → verify → retrieve differently-phrased → feedback → metrics) |
| Cost-control eval fixture/command | ✅ | `scripts/eval_engineering_memory_savings.py`, `app/engineering_memory/evaluation.py`; `test_evaluation_*` |
| Docs + threat model | ✅ | `docs/engineering_memory.md`, `docs/engineering_memory_threat_model.md` |

## Validation commands & results

```
DATABASE_URL="sqlite://" python -m pytest \
  tests/test_engineering_memory.py tests/test_engineering_memory_api.py -q
# => 25 passed

python scripts/eval_engineering_memory_savings.py
# => baseline hit_rate=0.0 ; enabled hit_rate=1.0 mrr=1.0 ; token/turn savings=unavailable (no measured telemetry)

ruff check app/engineering_memory/ tests/test_engineering_memory*.py scripts/eval_engineering_memory_savings.py
# => All checks passed
```

Environment note: the app's runtime dependencies (fastapi, sqlalchemy, pydantic)
are not present in the base image and were installed into a virtualenv to run the
focused suite; required GitHub Actions checks perform the authoritative run.

## Governance boundaries honored

No merge to `main`; no production deploy; no production migration applied; no
production DB/Knowledge Graph/taxonomy mutation; no secret or precise
protected-locality exposure; no auto-merge; no purchased services.

## Known limitations / follow-ups

- Semantic (pgvector) retrieval is stubbed behind an optional adapter, not
  enabled, per the "lexical first" directive.
- Token/turn savings require measured paired runs; the harness reports them as
  `unavailable` until a telemetry fixture is supplied.
- Mission Control UI and cross-repo sharing are explicitly out of scope for v1.
