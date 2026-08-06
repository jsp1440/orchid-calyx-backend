# BUILD-BRAIN-107 — Governed Agent Assignment and Execution Receipts

## Purpose

Turn the constitutionally governed Mission Control queue into an auditable orchestration boundary without granting autonomous merge, deployment, publication, or production Knowledge Graph authority.

## Implemented

- capability-scoped agent descriptors;
- deterministic eligible-agent ordering;
- fail-closed assignment when a build is blocked, already transitioned, or has no enabled capable agent;
- stable assignment identifiers;
- queue transition from admitted to scheduled at assignment;
- explicit started and completed execution receipts;
- completion requirement for evidence URIs and a deterministic output checksum;
- terminal lifecycle enforcement through the governed queue;
- deterministic, read-only assignment and receipt listings.

## Important boundary

This build does not launch an agent or execute code. It defines the governed handoff and the evidence contract that a future executor must satisfy.

The orchestrator cannot:

- merge a pull request;
- deploy a service;
- publish scientific content;
- mutate the production Knowledge Graph;
- bypass constitutional admission;
- mark work complete without evidence and a checksum.

## Initial deterministic selection rule

When multiple enabled agents support an architecture, the lowest lexical `agent_id` is selected. This simple rule is deliberately deterministic and replaceable by a later policy engine that preserves reproducibility.

## Validation

Focused tests cover:

- deterministic architecture-capability assignment;
- rejection of blocked builds;
- rejection when no capable enabled agent exists;
- required scheduled → running → completed order;
- completion evidence and checksum requirements;
- rejection of completion before start.

## Status

Candidate implementation only. No production activation or executor connection.
