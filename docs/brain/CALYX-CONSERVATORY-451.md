# CALYX Conservatory collection intake, QR labels, and plant dossier — issue #451

Date: 2026-08-07
Program: #421; related product program #414
Status: bounded private operational implementation delivered pending exact-head validation; no deployment, merge, taxonomy activation, public location exposure, or production graph mutation performed.

## Goal

Provide the first production-shaped private Conservatory workflow for collection management:

`owner-authenticated intake → accession/plant/clone/location/media records → stable private QR label → scan-to-dossier → care/movement history → readiness`

The implementation is deliberately owner-scoped and review-oriented. It is not a public collection portal and is not a taxonomic authority.

## Owner scope and privacy

Every Conservatory record is stored beneath a deterministic one-way owner key derived from the authenticated actor. Collections, accessions, plants, clones, locations, labels, media references, events, and import receipts never use a caller-selectable owner path.

All location contracts are required to remain `privacy=private`. The service permanently reports:

- `private_collection=true`;
- `public_location_exposure=false`;
- `autonomous_taxonomic_acceptance=false`;
- `production_deployment_authorized=false`;
- `knowledge_graph_mutation_authorized=false`.

A label created under one owner scope cannot be resolved under another owner scope.

## Collection and accession contracts

A bounded intake creates or binds:

- collection ID, title, description, and owner scope;
- stable accession ID and accession number;
- acquisition timestamp, source, optional price, and notes;
- plant ID and display name;
- clone ID/name and optional clone origin;
- current private location;
- media/evidence references;
- stable label and QR target;
- initial acquisition event.

Collection and accession conflicts fail closed rather than silently rewriting prior identity.

## Photo/tag-assisted plant intake

The intake accepts evidence metadata for plant, flower, tag, roots, habit, or other media. Each media record preserves:

- SHA-256;
- source URI;
- license;
- attribution;
- capture time;
- role;
- owner and plant binding.

Media metadata are registered through the existing immutable artifact registry with an evidence URI. The service does not perform live image analysis or infer a taxonomic name from the image or tag.

Tag transcription is preserved independently as `tag_text` and may participate in duplicate review.

## Taxonomic identity state

Plant identity is explicit:

- `matched` — requires a canonical taxon ID supplied through a governed upstream process;
- `ambiguous` — unresolved alternatives remain for human review;
- `unresolved` — no accepted identity is asserted.

An intake marked `matched` without a canonical taxon ID fails closed. The Conservatory never accepts taxonomy on its own.

## Stable QR label and printable payload

Each plant receives a deterministic version-1 label ID derived from owner scope plus plant ID.

The label stores:

- stable `label_id`;
- `plant_id`;
- version;
- private QR target;
- QR payload;
- printable primary text, accession text, optional clone text, and QR target.

The target is:

`/brain/mission-control/conservatory/scan/{label_id}`

Because the scan route remains behind owner/API-key authentication, possession of the QR value alone does not expose the private collection or location.

## Plant dossier

The private dossier resolves:

- plant core record;
- accession;
- clone;
- collection;
- current private location;
- registered media references;
- complete event history;
- labels.

The dossier is available both by plant ID and by authenticated QR scan.

## Care and history events

Supported governed event types:

- acquisition;
- repotting;
- flowering;
- treatment;
- movement.

Events have deterministic IDs derived from owner, plant, type, timestamp, and details. Replaying the same event is idempotent. Movement events require an existing private target location and update the plant's current location while preserving from/to location IDs in history.

## Duplicate detection and import replay

Each intake has a deterministic request hash plus an external or derived import ID.

- exact replay under the same import ID returns the prior receipt;
- changed content under the same import ID fails with `CONSERVATORY_IMPORT_REPLAY_CONFLICT`;
- near-duplicate candidates are surfaced for review when accession number, tag text, or media checksum matches an existing plant;
- duplicate candidates do not cause autonomous merging.

## Protected Mission Control API

Routes are mounted under:

`/brain/mission-control/conservatory`

Protected endpoints:

- `POST /locations` — create one private owner-scoped location;
- `POST /intake` — collection/accession/plant/clone/media/location intake;
- `POST /plants/{plant_id}/events` — append care/history events;
- `GET /plants/{plant_id}` — private plant dossier;
- `GET /scan/{label_id}` — authenticated QR-to-dossier resolution;
- `GET /labels/{label_id}/printable` — printable label contract;
- `GET /readiness` — owner-scoped operational counts and governance state.

## Validation

Dedicated workflow:

`.github/workflows/calyx-conservatory-451.yml`

Validation covers:

- Python compilation;
- unresolved identity and canonical-ID enforcement;
- deterministic intake replay and replay-conflict rejection;
- QR target and printable label stability;
- scan-to-dossier behavior;
- repotting, flowering, treatment, acquisition, and movement history;
- duplicate detection;
- owner isolation;
- protected API/readiness behavior;
- artifact-registry regressions;
- permanent privacy/non-authority assertions;
- Ruff and `git diff --check`.

## Explicit non-actions

No public exposure of private collection locations, autonomous taxonomic acceptance, live image inference, production deployment, merge, scientific publication, or production Knowledge Graph mutation is authorized by this build.
