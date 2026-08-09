# CALYX-476 — Performance, caching, indexing, and capacity observability

Status: IMPLEMENTED / VALIDATION PENDING / NON-BENCHMARKING

## Delivered

- Deterministic timing contract with configurable slow-path threshold and structured timing records.
- Small bounded TTL cache with deterministic eviction and explicit per-key or full invalidation.
- Pagination safeguards with hard maximum limit and offset bounds.
- Database-index recommendations grounded in the executable mission queue and due-mission SQL contracts already used by `PostgresMissionRepository`; recommendations never apply migrations.
- Read-only queue/worker capacity adapter reusing existing `oc_missions` telemetry rather than creating competing worker state.
- Slow-path, retry-pressure, queue-without-worker, and cache-memory-risk findings with exact remediation.
- Deterministic synthetic load fixture that reports operation and byte counts only and explicitly states that it is not a benchmark or production load test.
- Protected Mission Control readiness endpoint at `/brain/mission-control/performance/readiness`.

## Governance boundaries

This build does not run production load tests, fabricate throughput or latency benchmarks, create database indexes, alter migrations, deploy, merge, or increase worker concurrency. Index recommendations are advisory query contracts only. Live capacity telemetry is read-only and degrades to an explicit `CAPACITY_PROVIDER_NOT_CONFIGURED` finding when the mission database is unavailable.

## Validation

Focused tests cover deterministic slow-path timing, TTL eviction/invalidation, pagination rejection, query-grounded non-migrating index recommendations, capacity pressure findings, and bounded non-benchmark load fixtures. Dedicated CI compiles the surface, runs focused tests, and enforces the permanent no-production-load-test/no-index-migration boundary. Exact-head hosted-runner results are recorded separately because GitHub-hosted runners are currently failing before job steps across the repository.
