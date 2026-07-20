# BUILD-086B — Cross-Document Evidence Aggregation and Reconciliation

## Architecture and schema

BUILD-086B adds an isolated aggregation layer inside `oc_candidate_knowledge`. Additive tables persist reconciliation rulesets/models, planned runs and items, clusters and immutable candidate-version memberships, versioned aggregate assertions, exact evidence-anchor links, source-independence assessments, temporal/geographic/taxonomic contexts, measurement summaries, multidimensional confidence assessments, first-class conflicts, reviews, warnings, events, tombstones, and quality metrics. Protected taxonomy and production graph schemas are not referenced or changed.

The supported aggregate registry covers taxon identity and name usage, traits, morphology, glossary concepts, pollinators, mycorrhizae, habitat, geography, phenology, measurements, environmental tolerance, conservation threats/actions, cultivation, DNA markers, molecular results, ecological interactions, specimens, and occurrences. Future types remain additive.

## Clustering, independence, and evidence networks

Deterministic local clustering uses candidate type, normalized assertion identity, taxon concepts, and scientifically material scope. Regional phenology/occurrence evidence remains in regional clusters. Method differences stay visible inside measurement and tolerance topics. Similar wording alone is insufficient.

Every member retains its candidate ID/version, revision, and exact anchors. Source lineage, document hashes, citation lineage, primary/derivative class, duplicate copies, reviews, AI syntheses, and uncertainty determine independent-source counts. Repeated reporting never becomes an independent confirmation.

Versioned relationships include support, partial support, contradiction, qualification, refinement, duplication, supersession, correction, derivation, temporal replacement, geographic limitation, method/taxon dependence, and unresolved relationships. Differences in method, population, geography, time, taxon concept, or compatible units are not automatically classified as contradictions. Dissent remains visible in first-class conflict groups with anchors and resolution history.

## Reconciliation and summaries

Taxonomic reconciliation preserves each source name and zero, one, or multiple match candidates; it never rewrites source evidence or canonical taxonomy. Temporal summaries expose earliest/latest dates and superseded evidence without inventing trends. Geographic summaries retain country, region, locality, and unresolved scope without universalizing local evidence.

Measurement reconciliation preserves original values, units, sample sizes, methods, and contexts. Versioned deterministic conversions support compatible units. Min/max, unweighted mean, and independent sample totals are produced only for compatible observations. Pooled estimates remain prohibited without an explicit valid future rule.

Evidence summaries expose source/independence classes, directness, experiments, statistical results, reviews, AI syntheses, support, contradiction, unresolved evidence, anchor completeness, taxon certainty, compatibility dimensions, and review completeness. The visible composite is only a versioned prioritization aid and is never a truth probability.

Consensus candidates use `STRONGLY_SUPPORTED`, `SUPPORTED`, `MIXED_EVIDENCE`, `CONFLICTING`, `LIMITED_EVIDENCE`, `SINGLE_SOURCE`, `METHOD_DEPENDENT`, `GEOGRAPHICALLY_LIMITED`, `TEMPORALLY_LIMITED`, `TAXONOMICALLY_AMBIGUOUS`, `SUPERSEDED`, `WITHDRAWN`, and `NEEDS_REVIEW`. Majority vote alone is never sufficient; every aggregate remains unpublished and review-required.

## Planning, lifecycle, versioning, and review

Preview persists population, candidate versions, filters, type/source/review/confidence counts, rules/model, policies, and plan items without creating clusters or aggregates. Runs support planning, execution, cancellation, resume, retry, partial completion, item status, warnings, safe completed boundaries, metrics, and history. A failed cluster does not roll back completed clusters.

Aggregate identity includes assertion/topic identity, sorted candidate-version membership, clustering ruleset, reconciliation model, normalization, and taxon/temporal/geographic/measurement/source/copyright policies. Identical reruns reuse a version; changed membership, candidate version, rules, model, normalization, or policy creates a retained superseding version. Tombstones preserve inactive history.

Review actions cover cluster approval/split/merge, relationship verification, source dependence/independence, taxon ambiguity, measurement compatibility, consensus assignment, unresolved conflicts, supersession, withdrawal, and deferral. Every action records rationale, reviewer, and time without mutating source evidence.

## Copyright, API, and observability

Aggregate records contain no restricted verbatim text. Metadata-only and unknown policies are conservative, internal evidence remains access-controlled, limited previews are not expanded, exact anchors remain referenceable, and safe exports omit source-text fields. Credentials do not override stored copyright policy.

Authenticated APIs cover plans/runs, cancellation/resume/retry/history, clusters/members, aggregates/versions/summaries, support and contradiction networks, source independence, taxonomic/temporal/geographic/measurement reconciliation, conflicts/reviews, split/merge and source decisions, supersession/withdrawal, review-safe export, registries, and tombstones. There is no publication, final-answer, experiment-design, conservation-recommendation, adapted-protocol, or frontend surface.

Metrics report candidates, clusters, aggregate versions/reuse, relationships, dependence, conflicts, reviews, tombstones, failures, retries, elapsed time, and rules/model versions without logging source text or secrets.

“BUILD-086B creates provenance-preserving cross-document evidence aggregates from BUILD-086A candidates. It does not publish Knowledge Graph nodes or edges, declare scientific truth, generate final scientific conclusions, design experiments, recommend conservation actions, publish candidate events, or generate adapted protocols.”

## Known limitations and deferred BUILD-086C

Core clustering is intentionally deterministic and conservative; uncertain semantic equivalence, source lineage, taxonomy, and scientific compatibility require review. Controlled fixtures validate mechanics rather than production scientific accuracy.

BUILD-086C is deferred for final integration validation, a quality-evaluation corpus, aggregation-accuracy thresholds, conflict-recall validation, duplicate-source inflation testing, performance/concurrency, penetration testing, complete API contract validation, and BUILD-086 review readiness.
