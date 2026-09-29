# Scientific Observability (SCI-OBS-001)

Append-only, vendor-neutral observability for the Orchid Continuum scientific
pipeline. Implements the smallest foundation required by the *Laelia anceps*
vertical proof. Canonical contracts live in Orchid-Continuum-Brain
(`contracts/scientific_observation_event_v1.schema.json`,
`contracts/scientific_observability_vocabulary_v1.json`,
`contracts/scientific_observability_readiness_v1.json`) and the blueprint
`14_ENGINEERING/SCI-OBS-001-scientific-observability-foundation-blueprint.md`.

## Authority boundary

Observation events are **non-authoritative**. Recording one never publishes,
mutates the Knowledge Graph, promotes evidence, or activates taxonomy. All
query endpoints are read-only and advisory.

## Reuse (no parallel systems)

| Concern | Canonical component reused |
|---|---|
| Identity / lineage | `app.kernel.identity` (`OCID`, `OCIDKind.EVENT`), mirrors `app.kernel.events.ScientificEvent` correlation/causation |
| Protected-locality redaction | `app.data_governance.disclosure` key-sets (`_EXACT_LOCATION_KEYS`, `_IMAGE_KEYS`) |
| Locality classification enums | `app.data_governance.models` (`DataSensitivity`, `DisclosureMode`) |
| Readiness metric shape | `app.homepage_readiness.contracts.ReadinessMetric` (numerator/denominator, unavailable≠zero) |
| Review boundary (Verification Workbench) | `app.review_tasks.models.ReviewTaskInput` |

## Files

- `models.py` — `ScientificObservationEvent` envelope + vocabulary enums.
- `redaction.py` — defense-in-depth redaction reusing governance key-sets.
- `store.py` — append-only, idempotent, queryable store (`event_id` = idempotency key).
- `anomalies.py` — deterministic fail-closed rules → `ReviewTaskInput` bindings.
- `readiness.py` — six explainable readiness dimensions.
- `exporter.py` — OTel-concept-compatible exporter, **disabled by default** (`SCI_OBS_EXPORT_ENABLED`).
- `service.py` — `record()` (validate→redact→append→detect) + trace reconstruction.
- `routes.py` — read-only query boundary (`/api/scientific-observability/...`).
- `proof_laelia_anceps.py` — runnable vertical proof (`python -m app.scientific_observability.proof_laelia_anceps`).

Durable store shape: `migrations/SCI-OBS-001-observation-store.sql` (**draft, not applied**).

## Tests

`tests/scientific_observability/` — envelope validation, append-only + replay
idempotency, redaction/secret-scanning, protected-locality non-disclosure,
missing-provenance & conflicting-evidence anomalies, AI-metadata-without-raw-prompt,
readiness numerator/denominator (unknown≠zero), Workbench handoff idempotency,
no-authoritative-mutation, and the end-to-end vertical proof. `22 passed`.
