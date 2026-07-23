# KERNEL-009 — Scientific Runtime

KERNEL-009 introduces transaction-scoped runtime orchestration for the Orchid Continuum Scientific Kernel.

## Purpose

The Scientific Runtime coordinates Kernel operations without binding applications to a specific database, queue, or service implementation. It provides a stable execution boundary for evidence, assertions, relationships, publications, knowledge objects, queries, and events.

## Runtime context

Every execution carries an immutable `RuntimeContext` with:

- a correlation identifier;
- optional actor identity;
- optional publication scope;
- optional causation event;
- a timezone-aware start time normalized to UTC;
- read-only execution attributes.

## Runtime requests

`RuntimeRequest` identifies one canonical `RuntimeOperation` and supplies at least one of:

- a scientific object;
- a target OCID;
- operation parameters.

Requests and parameters are immutable after construction.

## Runtime results

`RuntimeResult` records:

- operation and lifecycle status;
- correlation identifier;
- optional resulting scientific object;
- optional output value;
- emitted event OCIDs;
- normalized completion time;
- structured failure details.

Succeeded, failed, and cancelled results require a completion timestamp. Failed results additionally require an error code and message.

## Runtime service

The `ScientificRuntime` contract supports execution, result retrieval, and cancellation. Concrete adapters may coordinate the existing Kernel services and Event Bus while preserving publication transaction boundaries.

## Validation

```bash
python -m pytest -q \
  tests/kernel/test_foundation.py \
  tests/kernel/test_evidence.py \
  tests/kernel/test_assertions.py \
  tests/kernel/test_relationships.py \
  tests/kernel/test_publications.py \
  tests/kernel/test_queries.py \
  tests/kernel/test_knowledge.py \
  tests/kernel/test_events.py \
  tests/kernel/test_runtime.py
```

Persistence-backed orchestration, dependency injection, transaction adapters, retry policies, authorization, distributed locking, and asynchronous execution remain deferred to later milestones.
