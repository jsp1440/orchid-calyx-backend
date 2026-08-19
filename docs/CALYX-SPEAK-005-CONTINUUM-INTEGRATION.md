# CALYX-SPEAK-005 — Continuum Integration

## Purpose

Connect the live **Speak with Calyx** conversation path to the Orchid Continuum intelligence fabric instead of treating evidence retrieval and Brain mission output as the only governed context.

## Implemented in this release

For every non-casual Speak-with-Calyx turn, the server now:

1. runs governed evidence retrieval;
2. extracts genus-like taxon candidates from the operator question;
3. resolves candidates against the canonical PostgreSQL Knowledge Graph;
4. traverses read-only Knowledge Graph context for resolved genera;
5. queries the read-only Brain graph for those resolved genera;
6. runs the governed Brain mission when research mode requires it;
7. sends retrieval + Continuum graph context + mission output to the configured reply provider;
8. records resolved genera and diagnostics in conversation metadata.

No step automatically publishes claims, promotes Candidate Knowledge, or mutates the Knowledge Graph.

## Generative provider contract

`Speak with Calyx` supports an OpenAI-compatible chat-completions provider when the runtime supplies:

- `CALYX_CHAT_COMPLETIONS_URL`
- `CALYX_CHAT_MODEL`
- `CALYX_CHAT_API_KEY` when the provider requires authentication

Optional:

- `CALYX_CHAT_TIMEOUT_SECONDS`
- `CALYX_CHAT_MAX_TOKENS`

If the URL/model are absent, Calyx deliberately uses `deterministic-governed / calyx-governed-summary-v1`. The `/api/calyx/speak/status` endpoint now reports the active provider and whether it is generative, so provider fallback can no longer be mistaken for a live LLM.

The generative model is not permitted to treat provider memory as scientific evidence. It may synthesize only the governed context supplied by the Continuum and must distinguish graph facts, direct evidence, inference, and missing evidence.

## Climate boundary

Historical/environmental climate facts already represented in the Knowledge Graph can now flow into the conversation through automatic graph traversal. A dedicated current-climate/forecast provider is **not yet connected** and is reported as `climate_provider: false` in status. Current NOAA/CPC or meteorological forecast integration therefore remains a separate implementation gate.

## Literature boundary

This release does not replace or bypass the evidence-retrieval corpus. If literature harvesting/indexing returns zero eligible evidence records, Calyx must continue to disclose that limitation. The important change is that lack of literature hits no longer makes Calyx blind to canonical taxonomic/graph context.

## Acceptance question

Use the same end-to-end question that exposed the integration gap:

> How should outdoor-grown orchids in a Mediterranean coastal climate be managed during an unusually cool, wet El Niño winter? Evaluate prolonged root-zone saturation, low temperature, reduced light, persistent leaf/crown wetness, rain protection, drainage/aeration, Physan 20, silicon, vitamin B1, and differences among Cymbidium, Laelia, Epidendrum, Sobralia, Masdevallia, Lycaste, Paphiopedilum, and Phalaenopsis. Distinguish peer-reviewed evidence from horticultural practice and identify uncertainty.

Minimum pass criteria after deployment:

- Calyx reports a generative provider if the external LLM runtime is configured.
- Mentioned canonical orchid genera are resolved and exposed in `research.continuum.resolved_genera`.
- Graph context is non-empty for taxa present in the canonical Knowledge Graph.
- Literature evidence is cited when retrieval supplies eligible records.
- Lack of literature evidence is explicitly disclosed rather than replaced with hallucinated citations.
- No automatic publication or graph mutation occurs.

## Remaining P1 follow-ons

1. connect a governed current climate/forecast adapter (NOAA/CPC and/or approved meteorological source);
2. repair/expand literature harvesting and indexing until known orchid-science benchmark questions return evidence;
3. add occurrence-to-environment joins so Calyx can summarize climate envelopes from georeferenced orchid occurrences;
4. expose source-level graph provenance in the conversation UI rather than only counts/diagnostics.
