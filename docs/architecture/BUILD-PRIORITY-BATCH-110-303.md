# Priority Implementation Batch — BUILD-BRAIN-110 through BUILD-FIG-303

Status: candidate implementation on draft PR #425. No production activation.

## Implemented vertical slices

### BUILD-BRAIN-110 — Dependency-aware scheduler
- deterministic topological ordering;
- priority ordering among simultaneously runnable builds;
- missing dependency rejection;
- cycle detection.

### BUILD-BRAIN-111 — Evidence and artifact registry
- immutable artifact identity;
- media type, source, license, producer, and checksum metadata;
- duplicate-content detection;
- supersession validation.

### BUILD-BRAIN-112 — Review and release eligibility
- scientific, licensing, security, and operational review classes;
- approve, reject, and changes-requested decisions;
- no producer self-approval;
- release eligibility requires all configured approvals and no blockers.

### BUILD-BRAIN-113 — Automatic Brain capture
- deterministic execution-output-to-build-record transformation;
- stable checksum;
- publication remains disabled.

### BUILD-MC-200 — Portfolio projection
- deterministic multi-architecture operational summary;
- build status counts;
- blocked reasons and next actions;
- read-only status.

### BUILD-KE-300 — Knowledge Explorer velamen slice
- candidate concepts for velamen, exodermis, and passage cells;
- concise and detailed definitions;
- synonyms, evidence URIs, and concept relationships;
- no autonomous scientific approval.

### BUILD-FIG-301 — FigureLabs assisted gateway
- provider-neutral structured brief contract;
- orchid root and velamen plate fixture;
- SVG, PPTX, and PNG requested outputs;
- required anatomical labels and evidence sources;
- assisted workflow only; no credential scraping or private API use.

### BUILD-ATLAS-400 — Atlas thematic-map execution slice
- deterministic four-layer manifest;
- biodiversity, Earth science, conservation, and sampling requirements;
- stable artifact checksum;
- publication remains disabled.

### BUILD-KE-302 — Contextual terminology recognition
- case-insensitive preferred-term and synonym matching;
- stable text offsets;
- deterministic overlap ordering for future popovers.

### BUILD-FIG-303 — Living Figures
- sequential figure versions;
- explicit evidence, concepts, and assets;
- immediate-prior-version supersession requirement;
- candidate and approved review states.

## Validation

Focused tests cover deterministic scheduling, dependency cycles, duplicate artifacts, self-review prevention, release eligibility, repeatable Brain capture, read-only portfolio output, glossary recognition, FigureLabs brief safeguards, Atlas layer completeness, and Living Figure lineage.

## Safety boundary

This batch does not:
- execute shell commands or external network jobs;
- merge pull requests;
- deploy services;
- publish scientific content or maps;
- store FigureLabs credentials;
- import production spatial data;
- mutate the production Knowledge Graph.

## Remaining integration work

The slices require later integration with persistent repositories, authenticated operator APIs, real review identities, Mission Control UI components, official FigureLabs automation if documented and authorized, Atlas rendering infrastructure, and production deployment approval.
