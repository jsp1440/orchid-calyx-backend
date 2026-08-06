# BUILD-BRAIN-109 — Execution Leases, Heartbeats, Timeout, and Recovery

## Purpose
Prevent duplicate workers, abandoned assignments, and indefinite candidate execution.

## Implemented
- durable execution lease contract;
- stable lease identifiers;
- active-worker exclusivity;
- owner-validated heartbeats;
- deterministic expiration classification;
- retry-candidate decisions bounded by a maximum-attempt policy;
- manual-review escalation after the retry limit;
- deterministic cancellation receipts;
- timezone-aware timestamp enforcement;
- ordered Mission Control projections for leases and cancellations.

## Recovery boundary
Recovery may classify expired candidate work and indicate whether another candidate attempt is eligible. It does not itself reschedule work, launch a worker, merge code, deploy, publish, or mutate production scientific data.

## Validation
Focused tests cover idempotent acquisition, duplicate-worker rejection, heartbeat extension, owner validation, timeout recovery, retry exhaustion, cancellation receipts, and naive-timestamp rejection.

## Status
Candidate implementation on draft PR #425. Production activation remains disabled.
