# OC-GENOME-001 — Regulatory Control Plane

This build adds the first executable regulatory layer to the existing autonomous
runtime. It does not replace the Queue Bridge, planner, executive engine, or
workers.

## Cycle

The runtime cycle is now:

1. heartbeat / sensing
2. regulatory checkpoint
3. enqueue existing work only when the decision is `activate`
4. execute existing work only when the decision is `activate`
5. record regulation, execution, and queue telemetry

Regulatory actions:

- `activate`: existing queue and execution behavior proceeds
- `repress`: no enqueue or execute call is made
- `escalate`: no enqueue or execute call is made and the reason is surfaced
  for an authority-bearing workflow

Invalid regulator output fails closed to `escalate`.

## Safety boundaries

The regulator is provider-free and deterministic. It does not grant production
publication authority, spend approval, credential access, or scientific review
authority. Existing human scientific-review and governed production-write rules
remain unchanged.

## Next integration increment

Feed the regulator from executive telemetry, completion state, provider intent,
repair/backoff state, and mission acceptance criteria so activation/repression
is driven by durable system state rather than a caller-supplied callback.
