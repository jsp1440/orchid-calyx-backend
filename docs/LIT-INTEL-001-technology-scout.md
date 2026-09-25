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

## Recovery continuation, 2026-09-13

The authoritative producer remains draft PR #1362, maker head
`10652adbf81d5f19b6e609b53eed9d511d3b4ea2`; #1361 remains dependent on validated
producer completion. Recovery reused this branch and found no competing maker
head or claim before the continuation comment on #1360. Current integration
`f4eb5966f1133fd66f533737556e179ed7581c44` has no intervening changes to the
touched intake contracts.

Hosted BUILD-077 run `34665841358`, job `103477428597`, did execute and failed
inside its complete-backend pytest subprocess. Its wrapper discarded the child
failure output. The PR workflow had supplied its configured remote database,
so recovery did not rerun it. The repair routes PR-triggered validation to a
fixed localhost PostgreSQL service, bootstraps the existing migrations there,
and retains the configured-database path only for the existing non-PR events.
Bootstrap rejects every other target before connecting. No secret, credential,
authentication or publication policy was changed.
The service uses host port 55477 so the full suite's unconfigured
`localhost:5432` placeholder does not accidentally become a reachable database.

The complete-backend subprocess still runs unchanged and still fails closed.
Its failed stdout/stderr is now visible when the subprocess runs without the
database configuration. Database-enabled child diagnostics remain withheld.
No failing assertion, test selection or exit status was weakened.

The existing isolated intelligence-ledger workflow now includes actual scout
SQL acceptance for DOI identity, immutable assessment snapshots, exact replay,
reviewed/rejected lifecycle preservation, no scientific/task extraction and
recovery after a partial batch failure. These tests require the fixed ephemeral
ledger database; they refuse another configured target.

Local verification used Python 3.12 and the available cached dependency set:

- 82 focused deterministic tests passed across producer/intake, semantic,
  ontology and CI-isolation/diagnostic contracts.
- 13 database integration tests skipped, including the seven new scout tests:
  local PostgreSQL/psql is unavailable. This is not persistence validation PASS.
- The unchanged maker's full suite returned 5,947 passed, 89 skipped, four failed
  and 13 errors. All four failing cases and all 13 error cases reproduced on
  current `main` at `0fc7fc5bfbee3fb9cebde99eb45c6ba1b525d674` under the same
  environment. The cases are the intentional certification `assert 1 == 2`,
  two scientific-environment tests requiring SciPy 1.18.0 (local 1.18.1), one
  subprocess dependency-path failure, and missing-psql errors in dispatch tests.
  These findings do not establish which additional cases failed in the earlier
  hosted run, whose child output was unavailable.
- Ruff, compilation and diff hygiene passed for the changed code. Hosted checks
  and a real PostgreSQL run remain outstanding; no complete-suite waiver or
  integration approval is claimed.

Recovery did not publish this continuation because automatic approval review
rejected a public repository mutation elsewhere in the same coordinated task.
The local patch remains reviewable pending the owner's publication decision.
