# Scientific Memory MVP

`SCIENTIFIC-MEMORY-MVP-001` is the bounded, review-governed bridge among
Oasis research discovery, Calyx recall, and Research Station project scope.

## Flow

1. Oasis, Calyx, or Research Station submits a bounded capture to a Research
   Station project.
2. The search is saved through the existing `saved_searches` contract.
3. Source evidence, Candidate Knowledge, Calyx inference, and research context
   are stored as different authority classes with source and rights metadata.
4. Calyx recalls a structured packet in which those classes remain separate.
5. Review, rejection, invalidation, and correction are append-only decisions.

Calyx Speak performs project-scoped recall through this service and receives
the same separated packet. A recall failure contributes no scientific-memory
context; it never converts conversation history into evidence. Owner sessions
remain owner-scoped, while backend API-key access follows the existing
privileged Research Station project-access contract.

The MVP accepts only open-access, explicitly authorized, user-provided, or
metadata-only source material. It does not fetch or store arbitrary publisher
PDFs and does not infer that API access grants redistribution rights.
Structured protected-locality fields fail closed before persistence.

## API

- `POST /api/research/projects/{project_id}/scientific-memory/captures`
- `GET /api/research/projects/{project_id}/scientific-memory`
- `POST /api/research/projects/{project_id}/scientific-memory/items/{item_id}/decisions`

## Hard boundaries

- Scientific Memory is separate from Engineering Memory.
- Conversation history and prior Calyx inference are never source evidence.
- Review acceptance permits governed research reuse; it does not create
  canonical scientific truth.
- There is no automatic Knowledge Graph publication or mutation.
- Migration application, production activation, and canonical promotion are
  separate owner checkpoints.
