# BUILD-BRAIN-106 — Governed Mission Control Build Queue

## Purpose
Convert constitutional build admission into an operational queue boundary for autonomous engineering.

## Behavior

A proposed build is evaluated by the executable Orchid Continuum Constitution before entering the queue.

- compliant work enters `admitted`;
- prohibited work enters `blocked` and remains visible for correction;
- only admitted work can move to `scheduled`;
- the permitted execution path is `admitted -> scheduled -> running -> completed`;
- admitted or active work may be cancelled;
- blocked work may be cancelled but never scheduled;
- terminal states cannot be reopened through this candidate boundary.

## Determinism and identity

Build IDs are durable identities. Re-submitting the same build with the same admission inputs and priority is idempotent. Reusing an existing ID with conflicting inputs fails closed.

Queue snapshots are ordered by priority, submission time, and build ID, and expose admitted, blocked, and runnable counts for Mission Control.

## Safety boundary

This implementation does not launch agents, run code, merge pull requests, deploy services, publish scientific content, or mutate the production Knowledge Graph. It is an in-memory candidate orchestration boundary pending reviewed persistence and runtime integration.
