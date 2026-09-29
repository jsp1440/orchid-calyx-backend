# Exact Locality: Scientific Use vs Disclosure

Date: 2026-08-21

## Core rule

Orchid Continuum must not confuse **using exact locality internally for science** with **disclosing exact locality to a user, client, export, model, or public interface**.

The canonical flow is:

> store exact → authorize use → compute at full precision → authorize disclosure → transform/redact for the audience → separately authorize export

Exact coordinates are scientifically valuable inputs for mapping, climate/elevation analysis, range modeling, phenology, conservation planning, gap analysis, and other Orchid Continuum functions. Removing exact coordinates from the internal scientific system would materially degrade those capabilities.

Security therefore belongs at the access and disclosure boundaries, not by destroying or blanket-disabling the underlying scientific information.

## Distinct operations

### 1. Storage

The canonical record may retain the most precise lawful locality available, together with provenance and source-specific policy.

Storage of exact locality does not imply permission to display, export, publish, send to an external model, or expose it through an unauthenticated API.

### 2. Internal scientific computation

Authorized Orchid Continuum services and trusted operators may use exact coordinates when the source policy, research purpose, project authorization, and principal entitlement allow that use.

Examples include:

- exact-point internal Atlas visualization;
- distance and range calculations;
- elevation and climate joins;
- environmental-envelope analysis;
- pollinator/mycorrhizal spatial association analysis;
- conservation gap analysis;
- duplicate/record-quality checks.

A result can be computed from exact coordinates without returning the exact coordinates to the viewer.

### 3. Interactive disclosure

The response sent to a browser or API caller is determined independently from the precision used in the computation.

Possible disclosure modes include:

- exact/full;
- generalized;
- grid/cell;
- jittered where scientifically appropriate;
- aggregate/density only;
- existence only;
- denied.

Public interfaces should normally receive generalized or aggregated locality for conservation-sensitive records. An authenticated owner or specifically entitled researcher may receive exact locality when policy allows.

### 4. Export

Bulk export is a separate privilege from viewing or computing.

A principal may be allowed to run an internal analysis at exact precision while still being prohibited from downloading a raw coordinate table or Darwin Core archive containing exact localities.

### 5. External AI/model processing

Permission to use a record internally does not automatically permit sending exact locality to an external model provider. Model-processing authorization remains independently governed by source policy and provider allowlists.

## Owner and administrator semantics

The Orchid Continuum owner must retain practical access to exact coordinates for lawful internal scientific work on data the system is entitled to use.

However, neither `owner` nor `administrator` is a universal override for partner-controlled restrictions. If a partner agreement states that only a named project or entitled researcher may view/export exact localities, that rule still applies.

This protects partner trust without crippling the scientific system.

## Browser/client rule

Do not send exact coordinates to an unauthorized browser and merely hide them in the UI. If the browser receives the coordinates, a technically capable user can recover them from network traffic or application state.

For non-exact audiences, the backend should return only the permitted representation: generalized points, aggregate cells, density surfaces, server-rendered tiles, or another disclosure-approved form.

## Legacy exact-coordinate utilities

Two older utilities require special treatment:

- `api_occurrence_points.py`: exact coordinates remain available to authenticated owner/backend access; the response is marked internal and uses no-store/no-cache headers.
- `oc_orchid_atlas.py`: an operator/local analysis utility may use exact coordinates when the server-side database credential is present. The generated file is explicitly marked restricted and should never be treated as the public Atlas product.

These utilities must not be used as delivery paths for future partner-restricted records until record-level policy filtering is wired end to end.

## Public Atlas target

The long-term Atlas should support at least two server-governed locality products from the same canonical record set:

1. **Authorized scientific view** — exact precision where policy and entitlement permit it.
2. **Public/general view** — generalized or aggregated location, with provenance retained but protected locality withheld.

No duplicate destructive database is required; the distinction is produced by policy-aware query and disclosure layers.

## Acceptance tests

The location architecture is not complete until tests prove all of the following:

- the owner can perform authorized exact-coordinate analysis;
- an unauthorized caller cannot retrieve exact coordinates;
- public map responses never contain hidden exact coordinates in JSON/network payloads;
- exact-coordinate computation can produce generalized output without leakage;
- export permissions are independent from analysis/view permissions;
- partner/project restrictions can override broad administrative status;
- caches, logs, traces, embeddings, graph edges, and generated text do not silently re-disclose protected exact localities;
- audit records identify exact-locality reads/exports where required.
