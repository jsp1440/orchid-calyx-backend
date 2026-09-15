# KALIX-ADR-001: Kalix as Named Persona Layer on Calyx Infrastructure

**Status:** ACCEPTED  
**Date:** 2026-09-15  
**Author:** Orchid Continuum Autonomous Session (owner-authorized)  
**Classification:** ARCHITECTURE DECISION RECORD — NOT SCIENTIFIC EVIDENCE

---

## Context

The owner directive required empirical determination of the relationship between Kalix and Calyx. The question was whether Kalix is:

- (A) A named persona/agent layer ON TOP of Calyx  
- (B) A specialized Calyx configuration  
- (C) A separate shell that delegates to Calyx  
- (D) Other

Empirical inspection of `app/calyx_conversation/`, `app/calyx_agent/`, and `app/calyx_orchestrator/` resolved this question.

---

## Decision

**Kalix = Option A: a named persona layer built ON TOP of existing Calyx infrastructure.**

Kalix is not a separate backend, not a fork of Calyx, and not a competing system. It is a new persona definition and route namespace that reuses the entire Calyx conversation stack.

---

## Existing Calyx Components Reusable by Kalix

| Component | Path | Reuse role |
|-----------|------|------------|
| Calyx conversational engine | `app/calyx_conversation/` | Core reasoning pipeline — full reuse |
| Persona definition system | `app/calyx_conversation/persona.py` (CALYX-PERSONA-005) | Kalix = new persona file in this same system |
| Evidence-provenance rules | `app/calyx_conversation/speak_routes.py` | Reused unchanged |
| Botanical terminology enforcement | `app/calyx_conversation/persona.py` lines 1–80 | Reused; Kalix inherits |
| Conversation session state | `app/calyx_conversation/` session objects | Full reuse |
| FCOS outreach mode | `app/calyx_conversation/persona.py` | Reused; Kalix may add consumer mode |
| Governance planning agent | `app/calyx_agent/` | Reused for task orchestration |
| Durable job queue | `app/calyx_orchestrator/` | Reused for async work |
| Intelligence ledger | `app/intake/` + `app/intake/intelligence_bridge.py` | Reused — evidence gates apply to Kalix tasks too |
| Authentication | `app/security.py` | Reused; Kalix adds consumer-grade auth on top |

---

## Missing Kalix-Specific Capabilities

These do not exist in the current Calyx codebase and must be built for Kalix:

| Capability | Gap | Priority |
|------------|-----|----------|
| Kalix persona definition file | No `kalix_persona.py` or equivalent exists | P0 — required to instantiate Kalix |
| `/kalix/*` route namespace | No route prefix; current routes are `/api/calyx/*` | P0 — required to serve Kalix separately |
| Consumer-grade auth | Current auth is owner/API-key only (`verify_owner_or_api_key`); Kalix needs member/subscriber auth | P1 |
| Lexicon context injection | `app/lexicon` entries are never loaded into `app/calyx_conversation/` context assembly | P1 — see P0-C gap below |
| Literature context injection | `app/literature_extraction` papers are never queried during conversation | P1 — see P0-C gap below |
| Multi-modal input (voice/image) | No voice or image input path in current Calyx | P2 |
| Push notifications | No push path for Kalix-initiated updates to users | P2 |
| Autonomous tool calling | Calyx converses; it does not autonomously invoke external tools | P2 |

---

## Lexicon/Literature → Calyx Context Gap (P0-C Finding)

Empirical inspection confirms **zero import paths** from `app.lexicon` or `app.literature_extraction` into `app/calyx_conversation/`. Specifically:

- `app/calyx_conversation/speak_routes.py` performs live Europe PMC fetches but never queries stored papers from the literature extraction ledger
- Lexicon entries (canonical botanical terminology) are stored in `app/lexicon/` but never injected into conversation context assembly
- Both modules exist as standalone HTTP APIs; neither feeds the Calyx reasoning context

This gap means Kalix (and current Calyx) cannot ground responses in:
1. OC's canonical botanical lexicon
2. Previously ingested, provenance-tracked literature findings

---

## Recommended Relationship

```
┌─────────────────────────────────────────────────────────┐
│                      KALIX LAYER                        │
│  kalix_persona.py  │  /kalix/* routes  │  consumer auth │
├─────────────────────────────────────────────────────────┤
│                    CONTEXT BRIDGE (NEW)                  │
│  lexicon_context_provider.py                            │
│  literature_context_provider.py                         │
├─────────────────────────────────────────────────────────┤
│              CALYX CONVERSATION ENGINE                   │
│  app/calyx_conversation/  (unchanged)                   │
├───────────────────┬─────────────────────────────────────┤
│  app/calyx_agent/ │  app/calyx_orchestrator/            │
├───────────────────┴─────────────────────────────────────┤
│  app/intake/  │  app/lexicon/  │  app/literature_*      │
└─────────────────────────────────────────────────────────┘
```

---

## Smallest Useful Kalix Core Slice

Minimum viable Kalix requires exactly three new artifacts, in order:

1. **`app/kalix/persona.py`** — Kalix persona definition (name, voice, scope); wraps or extends CALYX-PERSONA-005 rather than duplicating it
2. **`app/kalix/routes.py`** — `/kalix/speak` endpoint wired to the existing Calyx conversational engine with the Kalix persona injected
3. **`app/kalix/context_bridge.py`** — Pulls top-N lexicon entries and literature findings relevant to the current query and injects them as grounding context before the Calyx reasoning step

This three-file slice delivers a differentiated Kalix persona served through the full Calyx stack with lexicon/literature grounding, at zero duplication of existing infrastructure.

---

## Explicit Non-Duplication Boundaries

These MUST NOT be reimplemented for Kalix:

- Do NOT create a second conversational engine — reuse `app/calyx_conversation/`
- Do NOT create a second persona system — add a new persona file to the existing system
- Do NOT create a second orchestrator — reuse `app/calyx_orchestrator/`
- Do NOT create a second intelligence bridge — the 5-gate evidence system in `app/intake/intelligence_bridge.py` applies to Kalix task proposals as well
- Do NOT create a second authentication layer from scratch — extend `app/security.py` with a new consumer verifier

---

## Dependency Graph

```
app/kalix/routes.py
  └── app/kalix/persona.py
  └── app/kalix/context_bridge.py
        ├── app/lexicon/ (read-only query)
        └── app/literature_extraction/ (read-only query)
  └── app/calyx_conversation/ (unchanged)
        └── app/calyx_agent/ (unchanged)
        └── app/calyx_orchestrator/ (unchanged)
        └── app/intake/ (unchanged — evidence gates still apply)
```

---

## Next Executable Build

**KALIX-BUILD-001**: Create `app/kalix/` package with `persona.py`, `routes.py`, and `context_bridge.py`. Wire lexicon and literature queries into context assembly. Add `/kalix/speak` to the FastAPI app. 74-test baseline from LIT-INTEL-001/002 gates remain in force.

Governed by OC-AUTO-HOLD until owner authorizes integration.
