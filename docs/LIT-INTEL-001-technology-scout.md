# LIT-INTEL-001 — metadata scouting

Continues [issue #1360](https://github.com/jsp1440/orchid-calyx-backend/issues/1360)
on `oc-autonomous-integration`, inspected at
`87ceafe8f387d4d90d8914293e2634949f29f8df`.

The canonical blueprint is the existing Brain document
`13_LITERATURE_KNOWLEDGE_SYSTEM/Literature_Pipeline_Architecture.md`.

## Implemented boundary

`POST /api/intake/intelligence/scout` accepts up to 50 bibliographic leads under
the existing intake owner/API-key authentication. Leads may come from JournalClub,
scholarly indexes, OC harvesters or user input. The closed request accepts titles,
DOIs, reference URLs and bounded keywords. It accepts no transcript, abstract,
full text, score, instruction, or authority override.

Deterministic title/keyword rules identify candidate OC modules, including
cross-domain methods with no orchid keyword. No match remains unassessed rather
than rejected. All twelve triage dimensions are retained. Evidence-dependent
scores remain null, and potential OC benefits are hypotheses, not measured results.

Persistence reuses `oc_intake.sources`, `intelligence_items`, and append-only
`intelligence_observations`/`intelligence_events`. The complete versioned scout
assessment lives in each observation's `raw_snapshot.technology_scout`. Existing
item lifecycle and verification status are not reset by rediscovery. DOI identity
uses the current intelligence fingerprint function; observations hash the full
assessment, including discovery provenance and parser version. Without a DOI,
the primary URL is the conservative identity; unrelated URLs are not presumed
to represent the same work. The existing detail API returns observation history.

No scientific extraction, canonical publication, provider call or coding task
dispatch occurs from this metadata stage. The source and observation writes use
existing separate transactions: a failed batch may have persisted earlier items;
replay is the recovery mechanism, not an assertion of batch atomicity.

## Running

Preview the three bibliographically resolved initial leads without a database:

```sh
python -m scripts.oc_technology_scout --input data/technology_scout/priority_metadata.json
```

An already authorized caller can use the authenticated API or explicitly add
`--persist` with its existing intake `DATABASE_URL`. Production use still needs
normal integration/deployment and database readiness. No migration is added.

Only the Query-Adaptive Hybrid Search JournalClub episode has been directly
matched. TopoMAS and the event-stream paper were resolved from the owner's named
research leads. Graph RAG has multiple plausible identities; the dynamic/explainable
KG source remains unresolved, so neither is silently added to this exact-match seed.

## Next dependent work

[Issue #1361](https://github.com/jsp1440/orchid-calyx-backend/issues/1361) owns the
evidence-bound action/outcome and queue bridge. Reuse intelligence action/event
payloads, native `DeepOrchestrate.TaskLeaf`, `runtime/deep_orchestrate_queue_bridge.py`
and `oc.reserve-refill.v1`; do not create another scheduler. Native GitHub scheduler
dependencies use `OC-SWARM-DEPENDS-ON`, not prose alone.

JournalClub's public FAQs describe emails, written/audio/video episodes and DOI
links; no documented public API/feed/export was verified. Subscription transcript
rights and an automated access mechanism remain unverified. Source-paper licensing
must be evaluated separately from the discovery service's terms.

## Validation scope

Focused tests cover cross-domain relevance, uncertain scores, DOI/observation
identity, request bounds, rejected extra content, API authentication, existing
ledger SQL/payload behavior and intake regression behavior. SQL construction is
tested through a mocked connection boundary; this is not a live PostgreSQL or
production validation claim. Existing PostgreSQL integration tests remain useful
when an authorized test database is available.

The touched older intake files had pre-existing lint findings reproduced from
current `main`. Context-manager nesting, import order and formatting were cleaned
up; the multipart upload keeps the same required files field using `Annotated`.
Its existing per-file exception boundary is retained to withhold internal error
details. No authentication or scientific review policy changed.
