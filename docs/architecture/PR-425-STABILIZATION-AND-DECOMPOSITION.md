# PR #425 Stabilization and Decomposition

## Status

- PR role: integration umbrella only
- Merge authority: disabled pending decomposition and validation
- Deployment authority: disabled
- Publication authority: disabled
- Production Knowledge Graph mutation: disabled
- CI blocker: issue #481
- Stabilization tracker: issue #486

## Why decomposition is required

PR #425 now combines the canonical Brain foundation, governance, orchestration, portable validation, and many candidate domain contracts. Reviewing or merging the entire branch as one unit would make regression isolation, scientific review, and rollback unnecessarily difficult.

The branch therefore becomes a source integration branch. Smaller dependency-ordered slices must be prepared and validated before any merge is considered.

## Proposed stacked slices

### Slice 1 — Canonical Brain Core

Includes:

- `models.py`
- `registry.py`
- `fixtures.py`
- deterministic snapshots and checksums
- search, aliases, tags, relationships, supersession
- read-only canonical Brain API
- registry, API, and fixture tests

Gate:

- compile
- Ruff
- registry/API pytest
- deterministic snapshot receipt

### Slice 2 — Governance and Persistence

Depends on Slice 1.

Includes:

- Intent Graph fixtures and alignments
- governance coverage audit
- executable Constitution and admission evaluation
- atomic Brain capture handoff
- storage interface and JSON snapshot repository
- Mission Control Brain status projection

Gate:

- governance coverage = 100% for registered major architectures
- persistence round trip and tamper detection
- failed capture leaves no partial records

### Slice 3 — Governed Orchestration

Depends on Slices 1–2.

Includes:

- governed build queue
- deterministic agent assignment
- executor adapter and dry-run boundary
- execution leases, heartbeats, timeout, recovery, and cancellation
- execution receipts and evidence requirements

Gate:

- blocked work cannot run
- terminal states cannot reopen silently
- deterministic assignment
- receipt requires evidence URI and checksum

### Slice 4 — Scheduling, Evidence, Review, and Integration Contracts

Depends on Slices 1–3.

Includes:

- dependency scheduler
- evidence and artifact registry
- human review gates and release eligibility
- automatic execution-receipt-to-Brain capture
- cross-system event envelopes, routing, replay protection, compatibility, retry, observability, and dead-letter contracts
- Mission Control portfolio, risk, SLA, approval, dependency, and readiness projections

Gate:

- cycles and missing dependencies fail closed
- artifacts retain provenance, licensing, and checksums
- self-approval is prohibited
- publication and external delivery remain disabled

### Slice 5 — Knowledge Explorer and Figure Intelligence

Depends on Slices 1–4.

Includes candidate-only foundations for:

- integrated multimedia glossary cards
- contextual terminology and popovers
- concept graph and learning paths
- accessibility and editorial coverage audits
- FigureLabs assisted briefs
- Living Figures and scientific figure validation
- semantic discovery manifests

Gate:

- all media carry evidence, licensing, and alt text where applicable
- FigureLabs credentials and autonomous submission remain disabled
- glossary publication requires editorial review

### Slice 6 — Atlas and Earth Systems

Depends on Slices 1–4.

Includes candidate-only foundations for:

- layer registry and lineage
- Earth Systems adapters
- thematic map manifests and render boundaries
- habitat suitability, temporal change, sampling gaps, expedition planning, restoration planning, conservation prioritization, and threat overlays

Gate:

- deterministic layer and render manifests
- evidence and licensing required
- no live harvesting or map publication
- scientific findings remain candidates

### Slice 7 — Scientific Workbenches

Depends on Slices 1–6 as applicable.

Includes candidate-only foundations for:

- Research Station
- Conservatory
- Matrix
- AI.Vision
- Publishing

Gate:

- evidence remains separate from inference
- no final identification, diagnosis, treatment recommendation, manuscript submission, grant submission, or publication
- production writes remain disabled

### Slice 8 — Validation and Release Engineering

Cross-cutting; required before any slice merge.

Includes:

- canonical Brain validation workflow
- cross-platform Python validator
- compatibility shell wrapper
- machine-readable validation receipts
- CI recovery and administrative blocker records

Gate:

- GitHub Actions produces a run and attached status, or a separately approved trusted runner produces equivalent receipts
- every proposed merge slice has its own validation evidence

## Decomposition procedure

1. Keep PR #425 in draft as the source integration umbrella.
2. Do not merge PR #425 directly.
3. Create dependency-ordered slice branches from reviewed boundaries.
4. Remove unrelated files from each slice rather than relying on reviewers to mentally separate them.
5. Run the shared validator and attach the receipt to each slice.
6. Review and merge one slice at a time only after its dependency is accepted.
7. Rebase later slices after each accepted merge and rerun validation.
8. Close PR #425 only after all retained work has moved to validated slices or has been explicitly rejected.

## Current blocker

GitHub currently creates no workflow run or commit status for the integration branch. Issue #481 records the required repository-administration checks. This is a release-engineering blocker, not evidence that the code passes or fails.

## Standing invariant

Implementation count is not a completion metric. A build is complete only when its code, integration boundary, validation evidence, Brain record, and governance status agree.
