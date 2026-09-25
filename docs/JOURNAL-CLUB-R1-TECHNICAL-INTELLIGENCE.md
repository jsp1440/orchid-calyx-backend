# R1 Journal Club Technical-Intelligence Blueprint

Status: implementation slice for issue #1521.

## Purpose

Use owner-authorized JournalClub.io transcripts as a source of engineering/AI
intelligence for Orchid Continuum without treating subscription content as
scientific evidence and without creating a parallel scientific literature
store.

The implementation is deliberately provider-free. It performs deterministic
concept detection and mapping only. It does not log in to JournalClub.io,
circumvent access controls, call an LLM, deploy production, change taxonomy, or
publish to the scientific Knowledge Graph.

## End-to-end path

1. **Acquisition boundary**
   - Input is transcript text the owner is authorized to use, plus optional
     JournalClub.io URL, episode id, and DOI.
   - Acquisition/login/export remains outside this provider-free repository
     slice. The API never accepts or stores JournalClub.io credentials.

2. **Canonical source preservation**
   - `POST /api/intake/journal-club` creates the source through the existing
     `oc_intake` source pipeline.
   - The canonical text includes source system, title, episode id, DOI, and URL
     before hashing/extraction.

3. **Deterministic technical extraction**
   - `app/intake/journal_club.py` recognizes a bounded vocabulary of
     Graph RAG, hybrid/query-adaptive retrieval, dynamic knowledge graphs,
     reranking, embeddings, model routing, context engineering, agent
     orchestration, evaluation, fine-tuning, distillation, and memory.
   - Every detected technique carries exact transcript character spans.
   - Unknown/irrelevant text emits no candidate rather than an inferred guess.

4. **Orchid Continuum capability mapping**
   - Each candidate maps to explicit OC targets such as `knowledge_graph`,
     `calyx_retrieval`, `calyx_model_router`, `autonomous_engine`,
     `scientific_memory`, `engineering_memory`, and `evaluation_engine`.
   - Each candidate includes a bounded implementation recommendation.

5. **Existing intelligence ledger**
   - Candidates are persisted with `record_intelligence_items`.
   - The existing ledger keeps canonical promotion prohibited, external contact
     prohibited, immutable observations, dedupe, verification, comparison, and
     review state.
   - The complete `technology_scout` assessment is preserved in the
     observation snapshot.

6. **Review and improvement loop**
   - New items begin `DISCOVERED / UNASSESSED`.
   - Follow-up tasks are:
     `VERIFY_PRIMARY_SOURCE`,
     `COMPARE_EXISTING_KNOWLEDGE`,
     `EVALUATE_OC_IMPLEMENTATION`.
   - Production implementation, model-provider spending, scientific
     publication, and canonical graph mutation remain approval-gated.

## How this improves ML/LLM integration

Journal Club becomes an engineering-intelligence feed rather than a passive
reading list. A transcript can produce candidate improvements for:

- retrieval architecture and Graph RAG;
- model routing and deterministic/provider-free fallbacks;
- context construction and compression;
- agent orchestration and replay-safe execution;
- evaluation/ablation/calibration;
- embeddings/reranking;
- fine-tuning/distillation;
- separation of scientific memory, engineering memory, and conversation
  context.

The critical rule is **evidence before adoption**. A detected technique is not
automatically installed. It becomes a provenance-bound candidate that must be
compared with current OC behavior and verified on fixed evaluation fixtures.

## Verification

Focused tests in `tests/test_journal_club_intelligence.py` prove:

- representative Journal Club-style text produces the expected mappings;
- each evidence span points exactly into the original transcript;
- irrelevant text fails closed;
- source canonicalization is stable;
- the authenticated API uses the existing source and intelligence ledgers;
- provider calls and provider cost remain zero;
- no publication, canonical graph mutation, or automatic implementation occurs.

## Remaining acquisition gate

The repository slice is complete for **authorized transcript text supplied to
the intake API**. Bulk acquisition of the user's private JournalClub.io library
still requires a permitted source mechanism (for example an account export,
feed/email content, or browser/session access explicitly authorized by the
owner). That acquisition step must not scrape around authentication or store
account credentials in GitHub.
