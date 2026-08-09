# CALYX-478 — Climate, habitat, elevation, and environmental-envelope intelligence

Status: IMPLEMENTED / STATIC REVIEW HARDENED / EXECUTABLE VALIDATION BLOCKED / NON-CAUSAL

## Delivered

- Governed environmental records for climate variables, elevation, substrate, habitat, temporal coverage, spatial resolution, source/license, canonical taxon linkage, observed-versus-modeled state, uncertainty, provenance, and review status.
- Human review transitions with append-style review history.
- Bounded environmental-envelope assembly that keeps observed and modeled record counts explicit and summarizes numeric climate/elevation ranges without converting association into causation.
- Deterministic sampling-bias warnings for low sample count, spatial clustering, modeled-only envelopes, use of unreviewed candidate records, and accepted-name conflicts.
- Provenance-bearing Atlas handoff using the existing immutable artifact registry and the Atlas `earth_systems.environmental_envelope` layer family.
- Protected Mission Control record, review, envelope, Atlas-handoff, and readiness routes.

## Static-review hardening

A post-implementation audit found and corrected three scientific-integrity defects before executable CI becomes available:

1. Reusing an existing `record_id` could overwrite prior scientific evidence. Registration now uses a deterministic scientific-content digest: exact replay is idempotent and conflicting replay fails closed with `ENV_IMMUTABLE_RECORD_CONFLICT`.
2. When no record had been accepted, envelope assembly previously fell back to every record, including records explicitly marked `rejected`. Rejected records are now excluded from scientific assembly and counted separately.
3. Multiple accepted names attached to the same canonical taxon key were silently collapsed to the first record. The envelope now exposes `accepted_names`, sets singular `accepted_name` only when unambiguous, and emits `ACCEPTED_NAME_CONFLICT` otherwise.

The immutable scientific `record_digest` is now distinct from the mutable review `state_digest`, so review transitions do not invalidate evidence identity.

## Atlas integration

The handoff preserves canonical taxon identity, source URIs, uncertainty state, review basis, sampling-bias warnings, and a deterministic envelope digest. It is a candidate layer payload, not a published map. This follows the Atlas program requirement that climate, terrain, habitat, uncertainty, source/license, temporal extent, spatial resolution, and review state remain first-class governed records.

## Scientific boundaries

Environmental association is not represented as causation. Every envelope returns `causal_interpretation=not_authorized`; modeled records remain distinguishable from observations; candidate records are explicitly flagged if used because reviewed evidence is unavailable. No live production import, scientific publication, Knowledge Graph mutation, deployment, or merge authority exists.

## Validation

Focused fixtures now also cover immutable replay/conflict behavior, rejected-record exclusion, and accepted-name ambiguity. Hosted GitHub Actions remain affected by canonical incident #481: private-repository hosted jobs terminate before step 1 with `steps=null`, so these regressions have not yet received an executable exact-head verdict.
