# KALIX-DEPS-001/002 — Knowledge bridge production hardening

## Status

Implementation candidate on `fix/kalix-deps-001-002`, targeting
`oc-autonomous-integration`.

## Problem

The KALIX-CONTEXT-001 bridge had two avoidable implementation couplings:

1. Literature retrieval discovered paper IDs by scanning `repository.root`
   directly instead of using the repository abstraction.
2. Lexicon retrieval imported private `_load_entries` from the route module.

Both paths were functional, but neither represented a stable production
interface.

## Resolution

- `LiteratureResultRepository.list_paper_ids()` is now the bridge boundary for
  literature enumeration. The method already existed; the bridge now uses it
  directly and fails closed if repository enumeration is unavailable.
- Lexicon exposes public `search_concepts(q=..., limit=...)`, preserving the
  existing ACTIVE + APPROVED filtering and bounded query semantics.
- `app.calyx_conversation.knowledge_context` now imports only the public
  Lexicon search function for production retrieval.
- Tests prove repository abstraction use, public Lexicon search use, and
  graceful failure when repository enumeration is unavailable.

## Governance

- Read-only.
- No provider calls.
- No canonical Knowledge Graph mutation.
- No publication.
- No schema or production data mutation.
- This is interface hardening only; scientific filtering semantics are
  unchanged.

## Dependency closure

This implementation is intended to close:

- #1451 — KALIX-DEPS-001
- #1452 — KALIX-DEPS-002

Independent validation is required before integration.
