# CALYX-478 — Climate, habitat, elevation, and environmental-envelope intelligence

Status: IMPLEMENTED / VALIDATION PENDING / NON-CAUSAL

## Delivered

- Governed environmental records for climate variables, elevation, substrate, habitat, temporal coverage, spatial resolution, source/license, canonical taxon linkage, observed-versus-modeled state, uncertainty, provenance, and review status.
- Human review transitions with append-style review history.
- Bounded environmental-envelope assembly that keeps observed and modeled record counts explicit and summarizes numeric climate/elevation ranges without converting association into causation.
- Deterministic sampling-bias warnings for low sample count, spatial clustering, modeled-only envelopes, and use of unreviewed candidate records.
- Provenance-bearing Atlas handoff using the existing immutable artifact registry and the Atlas `earth_systems.environmental_envelope` layer family.
- Protected Mission Control record, review, envelope, Atlas-handoff, and readiness routes.

## Atlas integration

The handoff preserves canonical taxon identity, source URIs, uncertainty state, review basis, sampling-bias warnings, and a deterministic envelope digest. It is a candidate layer payload, not a published map. This follows the Atlas program requirement that climate, terrain, habitat, uncertainty, source/license, temporal extent, spatial resolution, and review state remain first-class governed records.

## Scientific boundaries

Environmental association is not represented as causation. Every envelope returns `causal_interpretation=not_authorized`; modeled records remain distinguishable from observations; candidate records are explicitly flagged if used because reviewed evidence is unavailable. No live production import, scientific publication, Knowledge Graph mutation, deployment, or merge authority exists.

## Validation

Focused fixtures cover source/license preservation, observed-versus-modeled separation, sampling-bias warnings, unreviewed evidence warnings, Atlas handoff provenance, and permanent no-import/no-publication/no-graph-write boundaries. Hosted GitHub Actions remain affected by the repository-wide pre-step runner provisioning failure.
