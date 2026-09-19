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

## Mission authority

Every regulatory decision carries the canonical `oc-mission-v1` context.
The machine-readable mission is derived from, and subordinate to:

- `brain/philosophy/FOUNDING_CHARTER.md`
- `brain/philosophy/CONSTITUTION.md`

The operational mission is:

> Orchid Continuum exists to build an evolving, trustworthy intelligence system
> for Orchidaceae that gathers and connects scientific knowledge, preserves
> evidence and uncertainty, discovers relationships and gaps, supports research
> and conservation, and transforms that knowledge into accurate, accessible,
> and inspiring experiences that help people understand, explore, and value orchids.

The Founding Charter's North Star remains:

> Does this help someone discover a meaningful relationship they could not see before?

Component names are intentionally excluded from the mission so implementations
can evolve without changing system identity.

## Safety boundaries

The regulator is provider-free and deterministic. It does not grant production
publication authority, spend approval, credential access, or scientific review
authority. Existing human scientific-review and governed production-write rules
remain unchanged.

## Next integration increment

Feed the regulator from executive telemetry, completion state, provider intent,
repair/backoff state, and mission acceptance criteria so activation/repression
is driven by durable system state rather than a caller-supplied callback.


## Mission-aligned queue admission

The runtime planner now performs a second admission check in addition to normal
technical executability. A module must be both executable and explicitly mapped
to one or more canonical OC mission objectives before it can enter the queue.

The mapping is deterministic and provider-free:

- Engineering -> continuous improvement with scientific integrity
- Mission Control -> provenance/uncertainty + continuous improvement
- Cognitive -> relationship/gap discovery + understandable experiences
- Scientific -> connected scientific knowledge + provenance/uncertainty
- Exploration -> relationship/gap discovery + research/conservation
- Narrative -> accurate, accessible, inspiring understanding

Unknown domains, missing domains, and work without a concrete next action are
not admitted. They remain visible as skipped work with a machine-readable
mission-alignment reason.

This intentionally avoids using an LLM to decide whether work "sounds aligned."
New categories must be deliberately mapped to the mission before autonomous
execution can select them.
