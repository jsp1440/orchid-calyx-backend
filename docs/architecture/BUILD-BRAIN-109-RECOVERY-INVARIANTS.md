# BUILD-BRAIN-109 Recovery Invariants

1. An assignment may have only one unexpired active worker lease.
2. Heartbeats are accepted only from the lease owner.
3. All lease timestamps must be timezone-aware and normalized to UTC.
4. Expiration is deterministic from `expires_at` and the supplied observation time.
5. Recovery returns a candidate retry decision only while the configured attempt budget remains.
6. Exhausted retries require manual review.
7. Recovery never launches execution, merges, deploys, publishes, or mutates production scientific data.
8. Cancellation produces a durable receipt and terminal lease state.
