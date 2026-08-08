# CALYX OASIS greenhouse decision-support and care-event engine — issue #452

Date: 2026-08-07
Depends on: Conservatory plant/location contracts #451
Status: bounded advisory implementation delivered pending exact-head validation; no autonomous control, deployment, publication, merge, or graph mutation performed.

## Goal

Provide an owner-scoped greenhouse decision-support workflow that connects private Conservatory plants to measured microclimates and produces deterministic, evidence-labeled cultural recommendations without controlling equipment.

Lifecycle:

`Conservatory plant/location → growing-space assignment → sensors → observations → configured thresholds → deterministic rule evaluation → recommendation → acknowledgement/suppression → human intervention → outcome → Conservatory care-event handoff`

## Contracts

OASIS defines explicit records for:

- growing spaces bound to existing private Conservatory locations;
- sensors with metric, unit, source, and growing-space identity;
- plant-specific thresholds;
- timestamped sensor observations and quality state;
- advisory recommendations;
- human interventions;
- recorded outcomes.

Supported environmental metrics are temperature, relative humidity, photosynthetic light (PPFD), substrate moisture, and ventilation state.

## Plant-to-microclimate assignment

A plant can be assigned to an OASIS growing space only when the space is bound to the plant's current owner-scoped Conservatory location. Mismatches fail closed rather than silently moving the plant.

Physical movement remains a Conservatory operation and therefore retains its private location history.

## Deterministic rules

The engine evaluates five bounded rule families:

- temperature;
- humidity;
- light;
- watering/substrate moisture;
- ventilation.

Rules compare the latest accepted observations against configured minimum, maximum, target, and tolerance values. Missing measurements produce an explicit `insufficient` evidence state and high uncertainty instead of an invented environmental conclusion.

Temperature, humidity, light, and watering recommendations use deterministic range comparisons. Ventilation evaluation combines configured temperature/humidity triggers with observed ventilation state when available.

The recommendations are cultural decision support only. They do not prescribe pesticides, medications, or other regulated treatments.

## Evidence and uncertainty

Every emitted recommendation records:

- plant and growing-space identity;
- rule family;
- severity (`info`, `watch`, or `action`);
- advisory action text and rationale;
- evidence state (`measured`, `derived`, or `insufficient`);
- uncertainty in the closed interval 0–1;
- exact observation IDs used as evidence;
- deterministic repeat key;
- evaluation timestamp.

No recommendation is represented as an autonomous command.

## Alerts, acknowledgement, suppression, and repeat controls

Recommendations have deterministic repeat keys. An authenticated operator can acknowledge a recommendation and optionally:

- suppress repeats through a specified timestamp;
- disable repeat emission after acknowledgement;
- keep repeat emission enabled when continued alerting is desired.

Suppressed evaluations remain visible in `all_results` with explicit suppression state/reason but are omitted from the active recommendation list.

## Intervention and outcome records

An operator can record a human intervention as watering, ventilation, shading, relocation, monitoring, or other cultural action. OASIS never invokes actuators.

When Conservatory handoff is enabled, the intervention is written through the existing owner-scoped Conservatory care-event boundary as a `treatment` history event whose details preserve:

- OASIS source;
- OASIS intervention ID;
- originating recommendation ID;
- intervention type;
- operator notes.

This maintains one plant history rather than creating a competing collection log.

Outcomes can subsequently be recorded as improved, unchanged, worsened, or unknown.

## Protected Mission Control API

Owner/API-key protected routes are mounted under:

`/brain/mission-control/oasis`

Endpoints include:

- `POST /spaces` — bind an OASIS growing space to a private Conservatory location;
- `POST /sensors` — register a sensor;
- `PUT /plants/{plant_id}/thresholds` — configure advisory thresholds;
- `PUT /plants/{plant_id}/assignment` — assign a plant to its matching microclimate;
- `POST /observations` — append a deterministic sensor observation;
- `POST /plants/{plant_id}/evaluate` — evaluate environmental rules;
- `POST /recommendations/{recommendation_id}/acknowledge` — acknowledgement/suppression/repeat controls;
- `POST /recommendations/{recommendation_id}/interventions` — record a human intervention and optional Conservatory handoff;
- `POST /interventions/{intervention_id}/outcomes` — record observed outcome;
- `GET /status` — private operational counts and permanent governance state.

## Fixture demonstration

Focused tests construct a private `Cattleya labiata` fixture in Conservatory, bind it to a greenhouse space, register temperature/humidity/light/substrate-moisture/ventilation sensors, and evaluate out-of-range observations.

The fixture validates:

- all five deterministic rule families;
- evidence observation binding and uncertainty;
- explicit missing-evidence behavior;
- acknowledgement, timed suppression, and repeat controls;
- private plant/location assignment integrity;
- human watering intervention handoff into Conservatory history;
- intervention outcome recording;
- protected status API.

## Validation

Dedicated workflow:

`.github/workflows/calyx-oasis-452.yml`

Validation covers compilation, OASIS focused tests, Conservatory dependency regressions, permanent advisory-only assertions, forbidden graph mutation checks, Ruff, and diff hygiene.

## Permanent non-authority

OASIS status/evaluation contracts permanently report:

- `advisory_only=true`;
- `autonomous_equipment_control=false`;
- `medical_or_pesticide_prescribing=false`;
- `production_deployment_authorized=false`;
- `scientific_publication_authorized=false`;
- `knowledge_graph_mutation_authorized=false`.

## Explicit non-actions

No medical or pesticide prescribing, actuator/equipment control, public exposure of private locations, production deployment, scientific publication, merge, or production Knowledge Graph mutation is authorized by this build.
