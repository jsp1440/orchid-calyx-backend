# BUILD-085B hybrid evidence retrieval

BUILD-085B provides read-only lexical, semantic, and transparent hybrid fusion over active BUILD-085A records. Queries are normalized and bounded; filters, pagination, per-source limits, active/historical selection, and expansion modes are explicit. Lexical title weighting and deterministic local semantic vectors feed versioned score fusion. Results expose lexical, semantic, reliability, temporal, verification, and diversity contributions rather than an unexplained truth score.

Exact/content/source deduplication and parent grouping improve diversity without collapsing distinct canonical findings. Protocol, result-package, treatment, and identification-key matches retain their canonical parent and exact anchors. Authorized expansion returns the complete canonical object; a chunk is never labeled complete.

Display policy is applied after ranking and before assembly. Metadata-only and unknown-policy results expose no excerpt, preview limits are honored, and internal content requires both the internal path and stored permission. Ranking explanations never contain restricted text. Citations preserve real locators or state `EXACT_LOCATOR_UNAVAILABLE`.

The evaluation harness reports precision/recall@K, MRR, NDCG, diversity, duplicate rate, citation completeness, parent correctness, and copyright correctness without implying scientific truth.

“BUILD-085B retrieves and ranks preserved evidence. It does not generate final scientific answers, extract or publish Knowledge Graph facts, design experiments, recommend conservation actions, or generate adapted protocols.”

BUILD-085C is deferred for independent end-to-end validation, a larger corpus, ranking calibration and thresholds, performance/concurrency testing, refresh validation, and final BUILD-085 review readiness.
