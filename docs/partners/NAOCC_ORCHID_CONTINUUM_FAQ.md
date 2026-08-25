# Orchid Continuum — NAOCC Partner FAQ

**Prepared for:** North American Orchid Conservation Center (NAOCC) / Smithsonian technical and scientific review  
**Prepared:** 2026-08-25  
**Status:** Partner-facing working document. It describes current capabilities, current safeguards, known gaps, and proposed collaboration patterns. It is not a security certification, legal opinion, authorization to operate, or promise that restricted partner data may be ingested today.

---

## 1. What is the Orchid Continuum?

The Orchid Continuum is a research and biodiversity-intelligence platform designed to connect orchid taxonomy, occurrence records, traits, ecology, literature, images, conservation information, and biological relationships into one evidence-aware system.

Its goal is not merely to store records. It is intended to help researchers and conservation organizations ask questions across sources while preserving the lineage of the evidence used to answer them.

Examples include:

- Which accepted taxon does a historical or synonymized name resolve to?
- What do occurrence records show about geographic or elevational range?
- Which traits distinguish ecological or horticultural groups?
- What pollinator or mycorrhizal associations have been documented?
- Which publications support a relationship, and what evidence did they actually report?
- Where do datasets agree, conflict, or contain gaps?
- Which relationships become visible only when taxonomy, occurrences, traits, literature, and interactions are linked together?

---

## 2. Is this proposal mainly about obtaining NAOCC data?

**No.** The intended relationship is two-way.

NAOCC should be able to **use the Orchid Continuum** for taxonomy resolution, evidence synthesis, literature discovery, mapping, relationship exploration, dataset quality assessment, and conservation research whether or not NAOCC contributes restricted data.

A collaboration should answer two separate questions:

1. **What can NAOCC safely use from the Continuum?**
2. **What, if anything, does NAOCC choose to make available to the Continuum, under what restrictions?**

Those decisions do not have to be symmetrical.

---

## 3. Would the Orchid Continuum replace NAOCC's database or website?

No. The preferred architecture is complementary rather than replacement-oriented.

NAOCC can remain authoritative for its own records and services. Orchid Continuum can act as an analysis, federation, reconciliation, and synthesis layer around those authoritative sources.

A partner record should retain its source organization, source identifier, attribution, license/agreement reference, and governance policy. The Continuum is not intended to silently become the new authority for partner-owned data.

---

## 4. What could NAOCC use the Orchid Continuum for?

Potential partner-facing uses include:

- accepted-name and synonym reconciliation;
- cross-dataset taxon matching;
- occurrence and range analysis;
- elevation and environmental comparisons;
- literature discovery tied to taxa and claims;
- evidence-backed species dossiers;
- pollinator and mycorrhizal relationship exploration;
- trait comparison and pattern discovery;
- conservation evidence review;
- image-linked collection or specimen workflows where rights permit;
- graph-based exploration of relationships among taxa, places, traits, interactions, literature, and observations;
- data-quality diagnostics, duplicate detection, orphan-record detection, and provenance completeness checks;
- research question generation and evidence synthesis through Calyx;
- export or reporting in interoperable forms where policy permits.

Not every item above is equally production-complete today. The technical review accompanying this FAQ distinguishes implemented, partially integrated, and planned capabilities.

---

## 5. What is Calyx?

Calyx is the governed reasoning and synthesis layer of the Orchid Continuum.

It is designed to combine deterministic services, structured evidence retrieval, provenance, and optional language-model synthesis. The external language model is **not** intended to be the authority for scientific facts or access-control decisions.

The architecture is designed so that important scientific and governance functions can remain available even when no external generative model is used.

---

## 6. What is the Knowledge Graph?

The Knowledge Graph represents relationships among scientific entities rather than treating every dataset as an isolated table.

Examples of graph relationships include:

- taxon → accepted taxon;
- taxon → occurrence;
- taxon → trait;
- taxon → habitat;
- taxon → elevation evidence;
- taxon → pollinator;
- taxon → mycorrhizal associate;
- publication → taxon;
- publication → observation / hypothesis / method / result;
- claim → supporting evidence span;
- image → taxon or collection record.

The objective is for a researcher to move from a claim to the evidence that supports it, rather than receiving an unattributed AI-generated statement.

---

## 7. What kinds of orchid data are in scope?

The Continuum architecture is intended to integrate or reason over domains including:

- taxonomy and nomenclature;
- occurrence/specimen/citizen-science records;
- latitude, longitude, elevation, habitat, and climate context;
- morphological, ecological, and horticultural traits;
- pollination and other biotic interactions;
- mycorrhizal associations;
- conservation information;
- scientific literature and extracted scientific structure;
- images and media;
- cultivated collection records where appropriate;
- provenance, licenses, citations, and evidence quality.

---

## 8. How is taxonomy handled?

Taxonomy is treated as a governed backbone rather than a label column.

The system includes World Plants / Hassler-oriented taxonomy workflows and explicit name-resolution logic. Release updates are being moved toward manifest-driven, checksum-verified intake so a new taxonomy release can be validated without silently changing scientific state.

The Continuum is intended to preserve original names as supplied while resolving them to a canonical scientific identity for comparison and analysis.

---

## 9. Does the Continuum preserve provenance?

That is a core architectural requirement.

Scientific assertions should remain traceable to source records, publications, data providers, licenses/agreements, and—where literature is involved—specific evidence anchors or excerpts when available.

The system is deliberately designed to distinguish:

- a source record from an interpretation;
- a user question from evidence;
- navigational context from scientific evidence;
- a document-discovery result from a publication-backed scientific claim;
- unknown/unmeasured values from measured zeros;
- AI synthesis from underlying evidence.

---

## 10. Can the AI invent scientific evidence?

It is not supposed to.

The Continuum's governance model treats evidence admission, publication eligibility, provenance, and protected-data access as server-side rules rather than tasks delegated to a language model.

The development program includes explicit anti-fabrication and fail-closed tests. Where evidence is unavailable, the intended behavior is to say that it is unavailable rather than convert absence of evidence into a biological conclusion.

---

## 11. Would NAOCC need to give the Continuum all of its data?

No.

Possible collaboration modes range from **no restricted-data sharing at all** to highly controlled project-specific access. Examples include:

1. NAOCC uses only public Continuum data and tools.
2. Continuum reads a NAOCC-approved public API or public export.
3. A governed connector reads a specifically approved subset under a data-use agreement.
4. Analysis is performed against a protected partner dataset while only generalized or aggregate results may leave the protected boundary.
5. A future Smithsonian/NAOCC-controlled deployment or federated service performs selected computations without transferring the underlying dataset to a public Continuum store.

The technical architecture should be chosen by NAOCC/Smithsonian security and data stewards, not assumed by Orchid Continuum.

---

## 12. Who remains authoritative for NAOCC data?

NAOCC/Smithsonian can remain the authoritative source.

The Continuum security model separates **source authority** from **access rights**. A copied or indexed record should not lose its original source identity, ownership/authority, license, agreement, attribution, or restrictions.

---

## 13. Can NAOCC revoke access later?

That is a required partner-governance capability.

The security architecture includes partner agreements, project memberships, dataset policies, entitlements, record-to-policy bindings, embargo/review concepts, retention/deletion obligations, and audit events. Some of this foundation is already implemented in repository code; complete live enforcement remains an acceptance gate before restricted partner data is accepted.

---

## 14. How are sensitive orchid localities handled?

The governing principle is:

> **store exact → authorize use → compute exact → authorize disclosure → transform/redact for the audience → separately authorize export**

Exact coordinates may be scientifically necessary for range, habitat, elevation, climate, or conservation analysis. That does not mean they should be displayed or exported.

The system therefore distinguishes internal scientific use from disclosure. Current hardening also treats combinations of fields—such as county, elevation, date, habitat, landowner information, or imagery—as possible indirect locality leaks rather than assuming that removing latitude and longitude alone is sufficient.

---

## 15. Are restricted images treated differently from text or occurrence data?

Yes. Image/media permission is intended to be independent.

A partner may permit a record to be used scientifically while prohibiting display or export of the associated image. The security design therefore treats restricted media as protected data with its own authorization path.

Private object storage, short-lived authorized delivery, and prevention of restricted media from entering public caches/CDNs remain required before high-sensitivity partner media is accepted.

---

## 16. Does being an Orchid Continuum administrator automatically grant access to partner-sealed data?

No. The partner-data model explicitly rejects that approach.

For the highest sensitivity class (`SEALED_PARTNER`), administrative role alone is not sufficient. Access is intended to require the specific dataset/project capability granted by the partner agreement.

---

## 17. Can NAOCC data be sent to OpenAI, Anthropic, Google, or another AI provider automatically?

No. Model-processing permission is designed to be a separate policy decision.

A record can be viewable to an authorized researcher but still prohibited from being sent to any external model. Where a model is allowed, the requested provider/environment must also be approved by policy.

Public visibility is not treated as automatic permission for external-model processing.

---

## 18. Can NAOCC use Continuum functions without generative AI?

Yes—that is an explicit architectural goal.

Taxonomy resolution, structured retrieval, database queries, provenance, deterministic planning, policy decisions, and other core services should not depend on a language model being present.

---

## 19. Can the Continuum export NAOCC data without permission?

The design separates export permission from view/use permission.

For example, current Darwin Core export hardening redacts exact coordinates by default and requires explicit high-friction authorization to include them. Future partner datasets require policy enforcement at the record/project level rather than relying only on an exporter's default behavior.

---

## 20. Does the Continuum automatically publish scientific claims or submit partner data to outside networks?

No. External publication/submission and authoritative scientific mutation are governed boundaries.

Current Knowledge Graph and literature workflows include publication-eligibility rules, explicit execution flags, confirmation tokens, and dry-run paths. External submission—such as contributing a relationship dataset to another network—should require a separate, explicit authorization.

---

## 21. What security controls exist today?

Current repository foundations include:

- signed, expiring owner sessions;
- API-key authentication helpers;
- server-side role/capability resolution;
- scientific-review authority separated from ordinary administrative status;
- partner sensitivity classes and fail-closed policy evaluation;
- purpose and dataset capability restrictions;
- independent locality/image disclosure modes;
- independent export and model-processing permissions;
- model-provider allowlists;
- direct generated-output leak filtering for protected literal values;
- a persistent partner-governance schema with default-deny Row Level Security scaffolding on governance surfaces;
- tests showing administrator status alone does not grant sealed-partner access;
- hardening of legacy exact-coordinate APIs and exports.

These are foundations, not a claim that the entire deployed system is yet approved for restricted NAOCC data.

---

## 22. Is Orchid Continuum ready today for unpublished or highly restricted NAOCC/Smithsonian data?

**No—not yet, and the project should not claim otherwise.**

The current security acceptance gate requires additional implementation and independent evidence, including:

- live database role and Row Level Security verification on the actual scientific tables;
- policy-aware graph traversal, search, embeddings/vector indexes, caching, and export propagation;
- model-processing and output guards wired into every governed synthesis path;
- semantic tests against indirect locality reconstruction;
- restricted-media storage and delivery controls;
- complete audit/event logging;
- backup/restore security verification;
- network, rate-limit, and abuse-control review;
- continuing route/script/export review;
- independent security review or penetration testing appropriate to the data sensitivity.

Until those gates are passed, demonstrations with NAOCC should use public or otherwise explicitly permitted data.

---

## 23. Then what can we safely do with NAOCC now?

A useful first collaboration can begin **without ingesting restricted NAOCC data**.

Recommended first-stage pilot:

1. Pick a bounded orchid research question and a small set of taxa.
2. Use public Continuum evidence and public NAOCC resources only.
3. Compare taxonomy resolution and source attribution.
4. Demonstrate an Atlas → evidence → Calyx → source/provenance workflow.
5. Identify which NAOCC-held data would materially improve the result, without transferring it.
6. Let NAOCC/Smithsonian security and data-management staff classify that data and choose an integration pattern.
7. Only after the relevant controls are verified, test a small, explicitly authorized partner dataset in a non-production environment.

---

## 24. What would NAOCC gain even if it never contributes restricted data?

NAOCC can still benefit from:

- broader cross-source evidence discovery;
- synonym/accepted-name reconciliation;
- literature and relationship navigation;
- a common framework for joining occurrences, traits, ecological relationships, and literature;
- provenance-aware AI-assisted synthesis;
- data quality and completeness diagnostics;
- visual exploration of knowledge relationships;
- an extensible platform for new conservation questions.

The value proposition is therefore **access to a shared scientific analysis layer**, not payment for data with access.

---

## 25. How would researchers access it?

The intended partner experience can include authenticated web access, project-scoped research contexts, API/service access, and governed exports. The exact partner identity and federation mechanism should be selected with NAOCC/Smithsonian IT.

The current frontend includes Mission Control, Calyx, Atlas, Research, Species Dossier, Conservation, and other module work; some routes are more mature than others, so partner pilots should use capability-specific acceptance tests rather than a single blanket claim of completion.

---

## 26. Can the Continuum connect to an existing NAOCC API instead of copying the database?

That is a preferred option where practical.

A read-only federated connector can reduce duplication and allow NAOCC to remain authoritative. The connector should still enforce rate limits, authentication where required, attribution, purpose, caching rules, sensitivity restrictions, and revocation.

Whether direct federation is permitted by Smithsonian policy must be confirmed by Smithsonian technical/security staff.

---

## 27. Could analysis be performed while the data stays in NAOCC/Smithsonian-controlled infrastructure?

Architecturally, yes. "Bring computation to protected data" is one of the partner-security principles.

A future pattern could run a bounded analysis service or connector inside a Smithsonian/NAOCC-controlled boundary and return only policy-approved aggregates or evidence references. That pattern is not presented as a currently deployed product feature; it is an integration option to evaluate with the partner's IT/security team.

---

## 28. What standards or government requirements may matter?

This depends on how NAOCC/Smithsonian classifies the collaboration and the information involved.

Topics likely to require review include:

- a Data Management Plan and/or Memorandum of Understanding covering ownership, access, backup, stewardship, attribution, retention, and sharing restrictions;
- institutional security review and system authorization;
- identity, least privilege, auditability, incident response, backup/continuity, and supply-chain/dependency controls;
- NIST security/privacy control families if federal-style controls apply;
- FedRAMP applicability **only if** the arrangement falls within current FedRAMP scope for a cloud service that creates, collects, processes, stores, or maintains Federal information on behalf of a Federal agency;
- records management, privacy, contractual, scientific-ethics, and conservation-sensitive-location requirements.

Applicability must be decided by Smithsonian/NAOCC IT, security, privacy, procurement, records, and legal authorities—not by Orchid Continuum.

Useful public references include Smithsonian Libraries' Data Management Plan and data storage/archiving guidance, NIST SP 800-53 Rev. 5, and current FedRAMP policy/playbooks.

---

## 29. What documentation is available for a technical reviewer?

This FAQ should be read with:

- `NAOCC_TECHNICAL_ARCHITECTURE_SECURITY_REVIEW.md` — system blueprint, data flows, trust boundaries, partner integration patterns, security posture, risks, and acceptance gates;
- `docs/security/PARTNER_DATA_SECURITY_FOUNDATION.md` — canonical partner-data security principles;
- `docs/security/PARTNER_DATA_SECURITY_IMPLEMENTATION_STATUS.md` — candid implemented-vs-not-yet-complete status;
- the current repository's tests, migrations, security workflows, and relevant pull requests for implementation evidence.

---

## 30. What is the best next step for NAOCC and Orchid Continuum?

Use a **public-data, no-risk technical pilot** to prove value first, while the partner-security work proceeds independently.

That lets NAOCC evaluate what the Continuum can do for its researchers without requiring NAOCC to expose protected information. In parallel, Smithsonian/NAOCC technical staff can review the architecture and specify the controls or hosting/integration pattern required for any later restricted-data collaboration.

The desired outcome is not "move NAOCC into Orchid Continuum." It is:

> **Give NAOCC a useful, evidence-aware orchid research platform while allowing NAOCC/Smithsonian to remain authoritative over its data and to control every protected-data boundary.**
