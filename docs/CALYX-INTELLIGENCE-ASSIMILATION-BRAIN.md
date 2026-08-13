# Calyx Intelligence Assimilation — Brain Record

Status: implemented through CALYX-INTEL-006A in production; CALYX-INTEL-007 adds autonomous internal execution.
Last updated: 2026-08-13.

## Purpose

Calyx Intelligence Assimilation converts externally discovered information into durable, provenance-preserving internal knowledge work without confusing source discovery with scientific truth. The subsystem is designed to let Calyx remember, compare, verify source identity, and route discoveries autonomously while keeping canonical scientific mutation and external actions behind explicit governance boundaries.

## Implemented flow

1. External intelligence enters the knowledge-intake boundary as preserved source material.
2. Deterministic parsing creates durable intelligence items and observations.
3. Repeated observations deduplicate onto a stable knowledge fingerprint while preserving provenance and observation history.
4. Knowledge-delta comparison checks current Continuum stores and records whether the item appears already known or requires review.
5. Primary-source verification records source identity, resolved URL, DOI/title/date metadata when available, authority metadata, evidence hash, and verifier version.
6. Source confirmation does not mark the scientific claim as verified.
7. Confirmed-source items can be routed to governed internal destinations such as OREP, Atlas, taxonomy reconciliation, pollinator network, mycorrhizal network, TraitBank, Conservation Platform, Orchid Connect, grant intelligence, and Source Registry.
8. CALYX-INTEL-007 connects comparison and post-verification routing to the existing autonomous runtime queue so eligible internal work advances without operator button-pushing.

## Production state

Migrations 108 and 109 have been applied successfully to the production database through the protected GitHub production environment. Production validation confirmed the intelligence ledger and verification/routing tables exist and retain fail-closed governance defaults.

The durable intelligence data model now includes:

- `oc_intake.intelligence_items`
- `oc_intake.intelligence_observations`
- `oc_intake.intelligence_events`
- `oc_intake.intelligence_verifications`
- `oc_intake.intelligence_routes`
- `oc_intake.intelligence_actions`

## Autonomous execution

The autonomous runtime now has a dedicated intelligence execution boundary. It discovers due intelligence states and creates idempotent runtime jobs for:

- `calyx_intelligence_compare_<item_id>`
- `calyx_intelligence_route_<item_id>`

These jobs invoke the real knowledge-delta comparison and governed internal routing services instead of falling through the legacy unknown-job acknowledgement path.

External retrieval is intentionally excluded from this runtime executor. Retrieval remains the responsibility of governed harvesters/retrievers, which can hand retrieved evidence snapshots into the verification layer. This separation prevents the autonomous queue from becoming an unrestricted network client.

Runtime job results are normalized to JSON-compatible values before persistence so database-returned datetimes, dates, decimals, UUIDs, enums, and nested collections do not cause successful scientific work to be misclassified as failed merely because its audit result cannot be serialized.

## Scientific governance invariants

The following invariants are deliberate and must remain fail-closed:

- A reachable or authoritative primary source is not equivalent to a verified scientific claim.
- `claim_verified` remains false unless a later evidence/review layer explicitly establishes otherwise.
- Canonical Knowledge Graph mutation is not performed by intelligence intake, comparison, source verification, or routing.
- Canonical taxonomy change is not performed by this subsystem.
- External contact, partner outreach, grant submission, or scientific publication is not performed by this subsystem.
- Sensitive-location disclosure remains outside autonomous intelligence routing.
- Source provenance and evidence hashes must be preserved even when a claim is rejected or already known.

## Gmail / Twin boundary

The Twin Gmail collector exists as a read-only intake adapter, but unattended production activation remains outside the completed core for two reasons:

1. Live Gmail collection requires a read-only OAuth credential that is not stored in this repository.
2. Twin briefing source links may be encoded only as HTML anchor targets; the collector must preserve those `href` values rather than reducing the message to link-less plain text.

The mailbox adapter must remain read-only: no send, reply, forward, delete, archive, label, mark-read, or other mailbox mutation permissions are required for intelligence ingestion.

Until the credential and HTML-link-preservation boundary are resolved safely, Calyx Intelligence Assimilation is complete from preserved intake onward but does not claim unattended Twin-mail acquisition.

## Validation history

CALYX-INTEL-006 dedicated PostgreSQL validation exercised a synthetic authoritative source and confirmed that a source-confirmed Earth Engine-style item produced READY routes to Atlas and Source Registry while retaining `claim_verified=false`, no canonical graph mutation, and no external contact.

CALYX-INTEL-006A production activation applied migrations 108 and 109 transactionally and verified all six durable intelligence tables and governance defaults.

CALYX-INTEL-007 dedicated PostgreSQL validation exercises state-driven job enqueueing, knowledge comparison, confirmed-source routing, runtime persistence, and governance invariants. Failures discovered during validation were treated as implementation defects and corrected before merge rather than bypassed.

## Architectural rule for future work

New intelligence domains should plug into this same staged contract:

`preserve -> deduplicate -> compare -> retrieve under governed source layer -> record source evidence -> scientific review/reasoning -> internal route -> governed canonical promotion`

Do not create one-off pipelines that bypass provenance, evidence review, or publication control. The intelligence subsystem is intended to become a general discovery-assimilation layer for Calyx, not a special-case Twin parser.
