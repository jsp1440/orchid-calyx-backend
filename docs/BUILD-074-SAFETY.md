# BUILD-074 safety boundary

- Recommendation generation is deterministic and does not call an external AI provider.
- No plaintext API credential is stored in `oc_ai` tables.
- No recommendation directly changes canonical taxonomy, `oc_graph`, or production scientific records.
- Provider routing returns a plan only; real provider execution is deferred.
- Hard budget limits block provider routing before execution.
- Recommendation decisions remain owner/API-key protected and approval-gated.
