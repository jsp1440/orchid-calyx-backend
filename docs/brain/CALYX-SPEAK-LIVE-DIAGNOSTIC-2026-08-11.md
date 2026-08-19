# CALYX Speak Live Diagnostic — 2026-08-11

## Observed live behavior

The deployed Speak with Calyx interface successfully authenticates, persists conversations in PostgreSQL, creates governed Brain missions, restores prior threads, and returns server-authored replies.

Live operator tests included:

- `Tell me about Laelia anceps?`
- `What do you know about Laelia anceps?`
- a detailed peer-reviewed-literature request concerning biologically meaningful foliar nutrient uptake in orchids.

For these scientific turns the deployed server returned `deterministic-governed / calyx-governed-summary-v1` and reported that the governed mission surfaced no supporting evidence sufficient for a conclusion.

## Interpretation

This is not a frontend rendering failure. The conversation substrate, PostgreSQL persistence, server-owned turn handling, and Brain mission dispatch are functioning far enough to produce and persist governed mission replies.

Two independent runtime limitations remain visible:

1. **Reply-provider limitation.** `deterministic-governed` is the explicit fallback provider used when the configured generative provider is absent or unavailable. It must never be mistaken for full conversational-model acceptance.
2. **Evidence-path limitation.** A completed mission with no supporting evidence is not evidence that the scientific literature is absent. It means the current governed mission/retrieval path did not surface eligible evidence for that turn. The UI and backend must distinguish `zero eligible records`, `retrieval unavailable/degraded`, and `mission synthesis produced no conclusion`.

The current canonical Speak implementation uses `_safe_retrieval()` plus the Brain mission service and intentionally fails closed rather than inventing facts. The evidence retrieval layer is backed by the semantic-index repository, whose runtime status includes backend type, durability/degraded state, indexed-document count, display-authorized count, active model count, and index error. Those diagnostics should be exposed through the active Speak integration contract rather than collapsing every empty scientific response into a generic no-evidence sentence.

## Integration priority

PR #893 remains the active Speak/Matrix/provider integration authority. The next implementation slice should make runtime evidence/provider readiness explicit in the Speak response/status contract and preserve these distinctions:

- generative provider configured vs deterministic fallback;
- retrieval backend available vs unavailable/degraded;
- indexed and display-authorized corpus counts;
- zero eligible results for this query vs zero corpus records;
- Brain mission completed with evidence vs completed without supporting evidence;
- no evidence surfaced must never be phrased as evidence of absence.

## Governance boundary

This diagnostic authorizes no provider-secret change, deployment, production database mutation, publication, Candidate Knowledge promotion, taxonomy activation, or Knowledge Graph mutation. Provider configuration and production deployment remain governed release actions.
