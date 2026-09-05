# Continuum Engineering Memory v1

Repository-scoped, **non-scientific** shared engineering memory for coding agents
(Claude, Codex, Gemini, GitHub agents). It captures sanitized run outcomes,
distills verified lessons, retrieves relevant memory via lexical search, records
feedback, and measures usage/savings — so agents stop repeatedly rediscovering
and re-solving the same repository problems.

> **This is engineering memory, not scientific evidence.** Every stored record is
> `evidence_class = non_scientific_evidence`. It is never published to the
> Knowledge Graph, never activates taxonomy, and must never be presented as
> scientific evidence, provenance, or fact. A repeated agent statement never
> becomes authoritative.

Implements issue **#1184**.

## Vertical slice

```
agent/task outcome
  -> bounded, redacted trace/lesson capture
  -> secret + protected-locality redaction
  -> durable storage (Postgres; SQLite dev/test fallback)
  -> hybrid lexical (BM25) / semantic-ready retrieval
  -> provenance + verification filtering
  -> retrieval/use/cost telemetry
```

v1 ships **lexical retrieval first**. There is no hard dependency on pgvector.
Semantic scoring is available through an optional adapter and is blended in only
when the deployed stack can support embeddings safely.

## Data model

Three tables (`migrations/082_engineering_memory.sql`,
`app/engineering_memory/models.py`):

| Table | Purpose |
| --- | --- |
| `engineering_memory_runs` | A sanitized agent/task run outcome. Raw prompts/conversations are **not** stored — only a bounded, redacted `sanitized_summary`. |
| `engineering_memory_lessons` | A distilled lesson: problem, cause, solution, applicability; provenance; verification + trust; lifecycle (`candidate`/`verified`/`invalidated`/`expired`); dependency/schema/file fingerprints; lexical representation; optional embedding. |
| `engineering_memory_retrievals` | A retrieval event: query, ranked lesson ids, whether injected/used, feedback, latency, and bounded cost/savings. |

Nullable numeric telemetry columns deliberately distinguish **measured zero**
(`0`) from **unavailable** (`NULL`). Aggregates never coalesce unavailable to
zero.

## API

All routes require the repository's existing privileged/operator authorization
(`verify_owner_or_api_key`). There is **no public scientific endpoint**.

| Method & path | Description |
| --- | --- |
| `POST /api/engineering-memory/runs` | Capture a sanitized run outcome. |
| `POST /api/engineering-memory/lessons` | Create a candidate lesson (provenance required). |
| `POST /api/engineering-memory/lessons/{id}/verify` | Promote a lesson to `verified` (evidence required). |
| `POST /api/engineering-memory/lessons/{id}/invalidate` | Invalidate a lesson. |
| `POST /api/engineering-memory/retrieve` | Retrieve up to 5 relevant lessons for a scope/module/task. |
| `POST /api/engineering-memory/retrievals/{id}/feedback` | Record feedback and measured savings. |
| `GET  /api/engineering-memory/metrics?workspace_scope=...` | Usage/savings telemetry for a scope. |

### Retrieval semantics

- **Scope isolation** — every read/write is confined to one `workspace_scope`.
- **Exclusion** — `invalidated` and `expired` lessons are never returned.
- **Ranking** — a `verified` lesson always outranks an otherwise-comparable
  `candidate` (BM25 score plus a fixed verified-dominance offset).
- **Caps** — at most **5** lessons; an injected character budget bounds context.
- **Provenance** — every returned lesson carries `source_run_id` and/or GitHub
  provenance, verification state, applicability, and invalidation metadata, plus
  an explicit `is_scientific_evidence: false` marker and a disclaimer.

### Deterministic invalidation

Lessons store `dependency_fingerprint`, `schema_fingerprint`, and per-file
`file_fingerprints`. `invalidate_by_fingerprints(...)` deterministically
invalidates any live lesson whose observed environment diverged. Time-based
`expires_at` is also honored at retrieval time even before a sweep runs.

## Safeguards

- **Secret redaction** before persistence: API tokens, keys, credentials,
  connection strings, `Authorization` headers, private-key blocks, JWTs, and
  common dotenv-style assignments → `[REDACTED_SECRET_<label>]`. Redaction is
  idempotent, and a residual-secret guard fails closed right before write.
- **Protected locality**: precise decimal coordinates are reduced to
  `[REDACTED_COORDINATES]` by default, or rejected under `strict_locality`.
- **No raw prompts/conversations**: request schemas set `extra="forbid"`, so
  unmodelled fields such as `raw_prompt`/`conversation` are rejected (422).
- **Fail closed** on malformed classification, missing provenance, or an
  unresolved redaction state.
- **Value-free reports**: redaction reports record labels/counts only — never a
  raw secret value, in DB, logs, errors, fixtures, or test output.
- **DB-level defense**: a CHECK constraint pins `evidence_class` to
  `non_scientific_evidence`.

## Validation

```bash
# focused suite (unit + HTTP surface + e2e + eval)
DATABASE_URL="sqlite://" python -m pytest \
  tests/test_engineering_memory.py tests/test_engineering_memory_api.py -q

# reproducible cost-control evaluation
python scripts/eval_engineering_memory_savings.py            # human-readable
python scripts/eval_engineering_memory_savings.py --json     # machine-readable
python scripts/eval_engineering_memory_savings.py --telemetry measured.json
```

The evaluation compares a memory-disabled baseline against memory-enabled on a
fixed task set and reports relevance (hit rate, MRR) and elapsed time. Token and
turn savings are computed **only** from a supplied measured-telemetry fixture;
absent that, they are reported as `unavailable` and never fabricated.

## Migration

`migrations/082_engineering_memory.sql` (forward, idempotent, Postgres) and
`migrations/082_engineering_memory_downgrade.sql` (rollback, child-before-parent
drops). The ORM metadata mirrors the SQL and round-trips create/drop on the
SQLite dev/test fallback. **Do not apply production migrations without owner
authorization.**

## Threat model

See [`docs/engineering_memory_threat_model.md`](engineering_memory_threat_model.md).
