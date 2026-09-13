# Orchid Continuum Durable Agent Operating Memory

This file records repeated engineering corrections that must survive individual Claude/Codex/Copilot/Gemini sessions.

It is operational memory, not scientific evidence. Current repository code, schemas, tests, pull requests, workflow results, and explicit owner decisions outrank stale memory.

## Canonical repository identity

- Canonical backend: `jsp1440/orchid-calyx-backend`.
- Canonical frontend: `jsp1440/orchid-continuum-frontend`.
- Do not substitute similarly named legacy repositories when a mission refers to current backend/frontend work.
- `oc-autonomous-integration` is the normal autonomous integration boundary. `main` remains owner-governed unless an explicit owner-approved promotion path says otherwise.

## Repeated correction -> durable rule

When an owner, review, failing test, or verified production observation corrects an agent assumption more than once, do not rely on chat memory. Encode the correction in the smallest durable repository mechanism that will prevent recurrence: this file, `AGENTS.md`, `CLAUDE.md`, a focused test, a contract, or a workflow guard.

Do not create one memory file per trivial edit. Persist only rules that materially prevent repeated cost, scientific error, privacy leakage, branch drift, or governance mistakes.

## CI truthfulness

- A red GitHub Actions badge is not automatically a code failure.
- If a job has no runner and executes zero steps (`runner_id=0`, empty runner name, `steps:null`, or equivalent), classify it as `CI_INFRASTRUCTURE_BLOCKED` / `HOSTED_VALIDATION_UNAVAILABLE`.
- Do not modify working product code in response to a workflow that never executed repository steps.
- Conversely, once a runner is assigned and repository steps execute, treat a deterministic failing step as a real validation failure until reproduced or explained.
- Never claim hosted green evidence when no hosted steps ran.

## Stuck-repair protection

After three unsuccessful attempts on the same deterministic failure class, stop speculative repair commits. Read the exact failing output, run the exact formatter/linter/test command locally where possible, compare it with workflow behavior, and make one deliberate correction. If accumulated branch churn obscures intent, reconstruct cleanly from current integration and preserve only intentional changes.

## Convergence before expansion

- Reuse the authoritative open PR for an acceptance criterion instead of starting a parallel lineage.
- If a producer/consumer pair is being converged, stabilize and validate the producer contract before expanding the consumer.
- Waiting for CI on one lane is not permission to open an unrelated foundation initiative when another existing executable convergence task is available.
- A blocked task parks that task, not the whole program.

## Scientific and privacy trust boundaries

- Generic genus navigation context is identity/navigation context, not evidence.
- For governed generic-genus arrivals, scientific evidence, confidence, conclusion, provenance, locality, coordinates, occurrence IDs, project IDs, exact-taxon IDs, or similar contaminating fields must fail closed when the governing contract says they are forbidden; do not silently broaden or reinterpret the scientific subject.
- Protected locality and private Conservatory information must never leak into public route/query context.
- Grower observations, photographs, measurements, collection locations, and cultivation history are not scientific evidence merely because they are attached to a taxon.
- `UNKNOWN`, `UNAVAILABLE`, `WITHHELD`, `ABSENT`, `CONTRADICTORY`, `REJECTED`, `SUPERSEDED`, `PROVISIONAL`, and `VERIFIED` are distinct states. Do not collapse them to simplify UI or scoring.

## Orchid naming / partnership language

- Do not imply a formal NAOCC/Smithsonian partnership unless the owner explicitly confirms and authorizes that claim.
- Neutral continuity/demo/test naming is preferred unless a partner relationship is actually established.

## Owner interaction

The owner is not a prompt relay, branch coordinator, or CI monitor. Agents should inspect GitHub state directly and leave durable comments/PR evidence.

Ask the owner only for genuine authority, credentials/private inputs, scientific policy, spending, production deployment/publication, or another decision that cannot be derived from repository truth.

## Engineering Memory boundary

Engineering Memory and this operating-memory file are non-scientific operational context. They may guide coding work but may never be cited or promoted as scientific evidence, taxonomic authority, occurrence evidence, or cultivation evidence.

## Autonomous continuation

Completing one bounded PR or test suite is not the same as completing a multi-step mission. If the linked acceptance criterion still has safe executable work, record the completed slice and continue to the next missing slice or let the coordinator immediately dispatch it. Do not voluntarily stop merely because the narrative for one subtask feels complete.

Owner/security/production gates remain hard stop points for the gated action only.
