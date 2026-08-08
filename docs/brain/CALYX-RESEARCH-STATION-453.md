# CALYX Research Station project, notebook, and evidence workspace — issue #453

Date: 2026-08-07
Depends on: Literature evidence binding #448 and Brain/artifact registry
Status: bounded private implementation delivered pending exact-head validation; no public sharing, scientific publication, laboratory control, deployment, merge, or graph mutation performed.

## Goal

Provide an owner/project-scoped research workspace that can preserve questions, methods, notebook history, research objects, claims, evidence, decisions, tasks, blockers, and reproducibility provenance while reusing existing Literature Intelligence and Candidate Knowledge boundaries.

Lifecycle:

`private project → research question/protocol → immutable notebook revisions → samples/datasets → evidence attachments → claims/evidence/decisions → tasks/blockers → reproducibility manifest → readiness`

## Owner and project scope

Research Station paths are derived from the authenticated owner identity and project ID. Projects are private by default. The service does not expose a public-sharing route.

Each project permanently records:

- `private_by_default=true`;
- `public_sharing_enabled=false`;
- `scientific_publication_authorized=false`;
- `live_laboratory_control=false`;
- `production_deployment_authorized=false`;
- `knowledge_graph_mutation_authorized=false`.

## Research contracts

The bounded workspace provides explicit contracts for:

- research projects;
- research questions;
- versioned protocols;
- notebook entries and immutable revisions;
- samples;
- datasets;
- attachments;
- claims;
- evidence links;
- project decisions;
- tasks, milestones, and blockers.

Project claims remain internal project assertions unless another governed publication process separately authorizes them.

## Immutable notebook revisions

Each notebook revision preserves:

- project and entry identity;
- monotonically increasing revision number;
- revision ID;
- parent revision ID;
- full revision body;
- SHA-256 of revision content;
- author;
- authored timestamp;
- immutable flag.

A new edit creates a new revision rather than overwriting prior scientific notes. A small `latest.json` pointer identifies the current revision without altering revision history.

## Samples and datasets

Samples preserve type, label, optional collection time, and caller-supplied provenance. Datasets require a SHA-256 content identity plus provenance and may include a schema reference.

Research Station does not operate laboratory instruments or infer sample results.

## Literature Intelligence attachments

A project can attach an existing #448 Literature Intelligence extraction run. The attachment resolves the run through the canonical Literature service and preserves:

- run ID;
- source SHA-256;
- extraction SHA-256;
- evidence-span count;
- review-readiness state.

The source literature is not copied into a new scientific authority.

## Candidate Knowledge attachments

A Candidate Knowledge attachment must identify the originating Literature Intelligence run. Research Station resolves the requested candidate/handoff against the preserved `candidate_handoffs.json` artifact for that run and stores the handoff provenance in the private project attachment.

Candidate Knowledge remains review-required and unpublished.

## Artifact-registry attachments

Existing immutable artifact-registry records can also be attached by artifact ID. The project preserves artifact checksum, source URI, and evidence URIs.

External references are supported only when a URI and SHA-256 are supplied.

## Claims, evidence, and decisions

Project claims preserve statement, optional bounded confidence, project review state, and provenance.

Evidence records link an attachment to an optional claim using an explicit relation:

- supports;
- contradicts;
- context;
- method.

Project decisions preserve subject, decision, rationale, reviewer identity, and timestamp. Supported decisions are internal project states only: accepted for project, rejected, deferred, or needs review.

## Tasks, milestones, and blockers

Tasks support todo, in-progress, blocked, and done states. A blocked task must include at least one explicit blocker. Tasks may carry milestone and due-time metadata.

Project readiness reports all blockers rather than hiding them. A project with blockers returns `BLOCKED`; otherwise the bounded workspace reports `PROJECT_REVIEW_READY`.

## Reproducibility manifest

The exportable manifest contains:

- project record;
- questions, protocols, samples, datasets, attachments, claims, evidence, decisions, and tasks;
- every immutable notebook revision;
- SHA-256 for each manifest-tracked project record;
- explicit blockers;
- deterministic manifest SHA-256;
- reproducibility state.

The manifest is suitable for review/export but does not authorize scientific publication.

## Protected Mission Control API

Owner/API-key protected endpoints under:

`/brain/mission-control/research`

include project creation; question/protocol/sample/dataset/attachment/claim/evidence/decision creation; notebook revision creation; task updates; reproducibility manifest export; and project readiness.

## Deterministic tests

Focused validation covers:

- private project scope and core research contracts;
- immutable, linked notebook revisions and hashes;
- Literature Intelligence attachment provenance;
- Candidate Knowledge attachment provenance;
- artifact-registry attachment;
- claims, evidence, and decisions;
- tasks/milestones/blockers;
- reproducibility-manifest checksum/state;
- protected project/readiness API;
- Literature Intelligence dependency regressions.

## Validation workflow

Dedicated workflow:

`.github/workflows/calyx-research-station-453.yml`

It runs compilation, Research Station tests, Literature #448 regressions, artifact-registry regressions, permanent non-authority assertions, Ruff, and diff hygiene.

## Explicit non-actions

No public sharing by default, autonomous scientific publication, live laboratory control, production deployment, merge, or production Knowledge Graph mutation is authorized by this build.
