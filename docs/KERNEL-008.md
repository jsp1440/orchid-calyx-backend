# KERNEL-008 — Scientific Event Bus

KERNEL-008 introduces immutable domain events and a stable event-bus contract for the Orchid Continuum Scientific Kernel.

## Purpose

Scientific state changes must be observable without coupling Evidence, Assertion, Relationship, Publication, Knowledge, and downstream application code to one transport or persistence technology.

A `ScientificEvent` is a permanent, globally identified record of a completed Kernel transition. It may be stored, replayed, audited, correlated with a publication, or delivered to subscribers.

## Event contract

Every event includes:

- an `EVENT` OCID;
- a canonical event type;
- the subject OCID affected by the transition;
- optional actor attribution;
- a timezone-aware occurrence timestamp normalized to UTC;
- optional publication scope;
- optional correlation and causation references;
- a positive sequence number;
- immutable structured payload data.

## Initial event types

The initial vocabulary covers evidence registration, assertion publication, relationship creation, publication preparation/commit/rejection, knowledge publication, supersession, dispute, and rejection.

## Event-bus contract

`ScientificEventBus` defines:

- durable event publication;
- direct retrieval by event OCID;
- subject-centric event history;
- subscription and unsubscription by canonical event type.

The contract deliberately does not prescribe an in-process dispatcher, database outbox, message broker, webhook, or cloud event service.

## Validation invariants

- Event objects require `EVENT` OCIDs.
- Publication scope requires a `PUBLICATION` OCID.
- Causation references require `EVENT` OCIDs.
- Events cannot cause themselves.
- Sequence numbers begin at one.
- Occurrence timestamps must be timezone-aware and are normalized to UTC.
- Payload mappings are copied into read-only views.

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
  tests/kernel/test_events.py
```

Persistence-backed event logs, transactional outbox integration, delivery guarantees, retry policies, dead-letter handling, asynchronous adapters, and replay checkpoints remain deferred to later Kernel and infrastructure milestones.
