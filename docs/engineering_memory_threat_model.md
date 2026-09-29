# Threat model — Continuum Engineering Memory v1

Scope: the `app/engineering_memory` service, its API routes, and its three
tables. This is engineering memory only; it holds no scientific evidence and
exposes no public endpoint.

## Assets

- Sanitized run outcomes and distilled lessons.
- Retrieval/usage telemetry.
- The trust boundary that keeps engineering memory out of scientific state.

## Trust boundaries

- **Callers** are already-privileged operators/agents (owner session or API
  key). There is no anonymous access.
- **Workspace scope** is the tenant boundary. Every read/write is confined to a
  single `workspace_scope`.
- **Evidence boundary** separates engineering memory from scientific
  evidence/Knowledge Graph state.

## Threats, mitigations, residual risk

### 1. Trace capture leaks sensitive material

- *Threat:* a captured run summary or lesson embeds secrets or personal/site
  data.
- *Mitigations:* deterministic, idempotent redaction of secrets and precise
  coordinates before persistence; a residual-secret guard that **fails closed**
  right before write; request schemas reject raw prompts/conversations
  (`extra="forbid"`); only a bounded `sanitized_summary` is stored, never full
  conversations.
- *Residual risk:* novel secret formats not covered by the pattern set. Mitigate
  by extending `_SECRET_RULES` and repository-configured patterns; redaction is
  conservative and over-redacts by preference.

### 2. Secret exposure downstream (logs, errors, fixtures)

- *Threat:* a redacted value re-surfaces in a log line, error, or test artifact.
- *Mitigations:* redaction **reports carry labels and counts only** — never raw
  values; errors never include the offending value; tests assert raw values are
  absent from stored rows and reports.
- *Residual risk:* callers logging their own pre-redaction payloads outside this
  service. Out of scope; document the contract: redact at the boundary.

### 3. Poisoned or stale memory

- *Threat:* an incorrect or outdated lesson is retrieved and trusted.
- *Mitigations:* lifecycle states (`candidate`/`verified`/`invalidated`/
  `expired`); invalidated/expired lessons are excluded from retrieval; verified
  lessons outrank candidates; deterministic fingerprint-based invalidation on
  dependency/schema/file drift; `expires_at` honored at retrieval time; trust
  band recorded per lesson.
- *Residual risk:* a verified lesson that becomes wrong without a fingerprint
  change. Mitigate via explicit invalidation and feedback signals.

### 4. Tenant / cross-repository leakage

- *Threat:* one workspace retrieves another's memory.
- *Mitigations:* mandatory `workspace_scope` on every row and query; a
  cross-scope `source_run_id` reference is rejected; retrieval filters strictly
  by scope; tested by `test_scope_isolation_*`.
- *Residual risk:* mis-scoped writes by a caller. Scope is required and
  validated; callers must pass the correct scope.

### 5. Scientific-evidence contamination

- *Threat:* engineering memory is presented or ingested as scientific evidence.
- *Mitigations:* `evidence_class` is fixed to `non_scientific_evidence` in the
  service, enforced by a DB CHECK constraint, and echoed with
  `is_scientific_evidence: false` and a disclaimer in every retrieval response;
  attempts to relabel fail closed; no public scientific endpoint exists; nothing
  here writes to the Knowledge Graph or taxonomy.
- *Residual risk:* a downstream consumer ignoring the marker. The marker,
  disclaimer, and absence of any scientific route make correct handling the
  default; misuse requires deliberately discarding explicit signals.

### 6. Denial of service / unbounded growth

- *Threat:* oversized payloads or unbounded retrieval cost.
- *Mitigations:* field length caps in schemas; retrieval capped at 5 with a
  character budget; bounded, in-process BM25 over scope-filtered candidates.
- *Residual risk:* very large candidate sets per scope. A Postgres GIN full-text
  index is provisioned for scale; pagination/pre-filtering is a follow-up.

## Out of scope for v1

Semantic/embedding retrieval at scale, a Mission Control UI, and cross-repo
knowledge sharing. These are follow-ups after the backend contract is verified.
