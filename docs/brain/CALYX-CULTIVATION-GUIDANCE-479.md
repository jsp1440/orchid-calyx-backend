# CALYX-479 — Cultivation evidence, cultural guidance, and provenance engine

Status: IMPLEMENTED / VALIDATION PENDING / DECISION-SUPPORT ONLY

## Delivered

- Immutable versioned cultivation-guidance records for canonical taxon or hybrid identity.
- Structured guidance fields for temperature, light, water, humidity, ventilation, rest, media, mounting, fertilization, and repotting.
- Explicit provenance classes: `literature_evidence`, `grower_observation`, and `local_adaptation`.
- Literature evidence requires a source URI; grower observation and local adaptation remain visibly separate from evidence-backed guidance.
- Locality/context, confidence, contradictions, and review state are first-class fields.
- Profile assembly preserves evidence/anecdote/local-adaptation separation and flags contradictory guidance fields for human review.
- Review decisions are stored separately from immutable source versions and bind to the source record digest.
- Conservatory/OASIS handoff is decision-support only and cannot actuate greenhouse equipment.
- Protected Mission Control APIs, deterministic tests, CI, and readiness.

## Governance boundaries

This build does not provide pesticide recommendations or medical advice. It does not autonomously change irrigation, lighting, temperature, humidity, fans, fertilizer dosing, or any other greenhouse control. It does not scientifically publish, mutate the production Knowledge Graph, deploy, or merge.

## Validation

Focused fixtures prove literature evidence remains distinct from grower anecdote, local adaptations are scoped rather than generalized, conflicting watering guidance enters contradiction review, versioned source records are immutable, review decisions bind to source digests, and the Conservatory/OASIS handoff remains decision-support only. Hosted GitHub Actions are currently affected by the repository-wide pre-step runner provisioning failure.
