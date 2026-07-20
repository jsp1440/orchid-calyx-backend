# BUILD-084C core foundation

BUILD-084C adds the additive `oc_document_intelligence` evidence store, versioned and idempotent extraction runs, safe lifecycle boundaries, cancellation/resume support, a source-anchored intermediate representation, and PDF, DOCX, and imported Google Docs adapters.

The implementation consumes immutable BUILD-082/083 revisions. It performs no Drive writes, protected-schema mutations, embeddings, or Knowledge Graph publication. Scientific object derivation, reliability/review workflows, copyright handling, and operator APIs remain explicitly deferred to BUILD-084D.
