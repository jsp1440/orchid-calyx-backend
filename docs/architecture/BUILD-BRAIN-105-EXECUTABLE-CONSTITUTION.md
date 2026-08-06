# BUILD-BRAIN-105 — Executable Orchid Continuum Constitution

## Purpose

Convert the Orchid Continuum's standing governance rules into deterministic build-admission checks that can be used by Calyx, Mission Control, and autonomous engineering agents.

## Constitutional rules

- `OC-CONST-001` — Builds must preserve provenance.
- `OC-CONST-002` — Evidence and inference must remain explicitly separated.
- `OC-CONST-003` — Repeatable builds require deterministic outputs.
- `OC-CONST-004` — Autonomous publication is not authorized at build admission.
- `OC-CONST-005` — Autonomous deployment is not authorized at build admission.
- `OC-CONST-006` — Autonomous merge is not authorized at build admission.
- `OC-CONST-007` — Production Knowledge Graph mutation requires a separate governed publication path.

## Admission contract

A build request must identify:

- build ID;
- target architecture;
- supporting intent records;
- supporting decision records;
- source documentation;
- validation plans;
- reproducibility and scientific-integrity safeguards;
- any requested elevated authority.

The result is either `admitted` or `blocked`, with stable rule IDs and human-readable findings.

## API boundary

`POST /brain/canonical/admission/evaluate` evaluates a proposed build but does not mutate the Brain, create work, merge code, deploy services, publish scientific content, or modify the production Knowledge Graph.

## Safety boundary

This build does not grant autonomous authority. It only evaluates whether a proposal satisfies the current Constitution. Human approval and existing publication, deployment, and merge controls remain unchanged.
