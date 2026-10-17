# LANDSCAPE-001 Design Guidance: Orchid Continuum Homepage, Atlas and Calyx

Status: PROPOSED guidance for design retrieval. Evidence class: non-scientific design guidance. This document is not scientific evidence, makes no biological claim, and never authorizes publication of a relationship, identification or conservation status.

Origin: an external competitive and interpretive landscape review of the Orchid Continuum homepage (research date August 2026, supplied October 11, 2026). The source URLs below were checked for accessibility only. The review's exact claims have not been revalidated against primary sources. Canonical definitions live in the Orchid Continuum Brain repository contract `contracts/landscape_guidance_v1.json`.

How to use this guidance: retrieve it when designing or reviewing the homepage, Atlas, perspective views, evidence receipts or the docent behavior of Calyx. Where this guidance and a canonical Brain knowledge object disagree, the canonical object governs and the disagreement is an owner decision listed under Canon conflicts.

## LRI-001: One focal organism; re-center without losing context

Priority P1. Applies to modules: perspective_engine, species_explorer, homepage, calyx. Applies to perspectives: orchid, pollinator, fungus, habitat.

Instruction: Resolve the selected focal entity server-side to a canonical identity. Reveal a bounded, evidence-bearing neighborhood; selecting an entity changes perspective, not the graph or scientific status.

Acceptance criteria:
- Each selectable entity has a resolved ID and a real route or honest unavailable state.
- Re-centering retains the prior focal ID and supports back navigation.
- No unsupported relationship is synthesized to fill the exhibit.

Guardrails:
- Selecting a pollinator must not change VISITS into POLLINATES.
- Do not replace canonical taxon IDs with names.

External references (design precedent only):
- https://eol.org/docs/discover/food-webs

## LRI-002: Just-in-time neighborhood, not a whole-graph hairball

Priority P1. Applies to modules: perspective_engine, graph_intelligence, species_explorer, calyx. Applies to perspectives: orchid, pollinator, fungus, habitat, climate, chemical, literature, conservation, disease, theory, gene, protein.

Instruction: Use bounded neighborhood/path retrieval with deterministic ordering, pagination and truncation disclosure. Expose relevant relationships progressively, including a text-only alternative.

Acceptance criteria:
- Query cost is bounded by documented server-owned limits.
- A truncated response is labeled partial, never complete or biologically sparse.
- Keyboard and text-list traversal work without drag or animation.

Guardrails:
- FamilySearch is an analogy, not an implementation dependency or proof of ecological inference.

External references (design precedent only):
- https://www.familysearch.org/en/help/helpcenter/article/what-is-view-my-relationship-in-family-tree

## LRI-003: Explain typed relationships before showing graph machinery

Priority P1. Applies to modules: perspective_engine, homepage, calyx, species_explorer. Applies to perspectives: orchid, pollinator, fungus, habitat, climate, chemical, literature, conservation, disease, theory, gene, protein.

Instruction: Present entity -> relationship verb -> entity, followed by evidence and a deeper destination; a diagram is optional presentation, not the public model of knowledge.

Acceptance criteria:
- Selected relation shows direction, biological meaning, supporting source and scope.
- Text explanation is usable without graph visualization.
- Any diagram uses real retrieved entities and distinguishes evidence from navigation.

Guardrails:
- Musicmap is nonbiological inspiration, not a scientific source.
- This proposes an accessible presentation alternative; it does not silently repeal the existing Design Book graph requirements.

External references (design precedent only):
- https://musicmap.info/

## LRI-004: Relationship language preserves predicate and direction

Priority P0. Applies to modules: graph_intelligence, pollination_intelligence, fungal_perspective, calyx. Applies to perspectives: orchid, pollinator, fungus, chemical.

Instruction: Reuse the existing KO-0051/0056/0058 interaction vocabularies. Render human-readable inverses without minting duplicate canonical predicates.

Acceptance criteria:
- VISITS renders visits/is visited by; POLLINATES renders pollinates/is pollinated by.
- Fungal DNA detection, colonization, germination support and adult nutrition remain distinct claims.
- Original imported predicate, source identifier and crosswalk remain inspectable.

Guardrails:
- Do not promote VISITS, co-occurrence or association to DEPENDS_ON.
- No new production predicate is created by this artifact.

External references (design precedent only):
- https://www.globalbioticinteractions.org/

## LRI-005: Missing, unavailable, not linked and negative evidence differ

Priority P0. Applies to modules: atlas, calyx, relationship_validator, perspective_engine, species_explorer. Applies to perspectives: orchid, pollinator, fungus, habitat, climate, chemical, literature, conservation, disease, theory, gene, protein.

Instruction: Keep coverage/query availability separate from scientific consensus. Explain unknown, not linked, unavailable and study-bounded negative evidence distinctly.

Acceptance criteria:
- A successful zero-row query says no linked records, not absent in nature.
- Source failure says unavailable, not no evidence.
- Negative claims require actual negative evidence plus method, location and time scope.
- Use labels and accessible non-color cues; validate any palette with visitors.

Guardrails:
- eBird documents light gray as species absence or very rare occurrence in a model and dark gray as no prediction for lack of data; that is a modeled-surface convention, so Orchid Continuum may borrow the unknown-versus-low distinction but must not present modeled absence as documented absence.
- Do not create a competing confidence/status enum.

External references (design precedent only):
- https://science.ebird.org/en/status-and-trends

## LRI-006: Claim-level uncertainty with scope and provenance

Priority P0. Applies to modules: relationship_validator, calyx, perspective_engine, research_station. Applies to perspectives: orchid, pollinator, fungus, habitat, climate, chemical, literature, conservation, disease, theory, gene, protein.

Instruction: Derive public language from existing evidence-aggregate/review state. Preserve conflict, source count, geographic, temporal, methodological and taxonomic limitations.

Acceptance criteria:
- Every claim-level receipt links its aggregate or source anchor.
- Single-source and limited/context-bound states remain visible.
- Withdrawn/superseded records cannot appear as clean current evidence.

Guardrails:
- Research Grade is a community record-quality status, not universal truth.
- Do not adopt Confirmed/Provisional/Disputed/Unknown as new database statuses.

External references (design precedent only):
- https://help.inaturalist.org/en/support/solutions/articles/151000169936-what-is-the-data-quality-assessment-dqa-and-how-do-observations-qualify-to-become-research-grade-

## LRI-007: Evidence support is not a probability of truth

Priority P0. Applies to modules: relationship_validator, calyx, research_station, atlas. Applies to perspectives: orchid, pollinator, fungus, habitat, climate, chemical, literature, conservation, disease, theory, gene, protein.

Instruction: Retain SCIAN-002 semantics: evidence-support scores are heuristic and uncalibrated. Explain evidence strength separately from any modeled likelihood.

Acceptance criteria:
- A heuristic index is never displayed as percent probability or calibrated likelihood.
- A statistical interval names model, estimand and level where available.
- Missing numeric uncertainty stays null; use a plain explanation, not a manufactured percentage.

Guardrails:
- IPCC climate likelihood conventions cannot calibrate an orchid relationship score.
- The report's bare-number pairing recommendation applies only when a valid number exists.

External references (design precedent only):
- https://www.ipcc.ch/site/assets/uploads/2017/08/AR5_Uncertainty_Guidance_Note.pdf

## LRI-008: Unknown conservation risk is not safety

Priority P0. Applies to modules: conservation, atlas, calyx, relationship_validator. Applies to perspectives: orchid, pollinator, fungus, habitat, climate, conservation.

Instruction: Separate Data Deficient, Not Evaluated, assessment unavailable, and a reviewed conservation assessment. Show assessment authority, version/date and scope.

Acceptance criteria:
- Missing assessment never becomes Least Concern.
- Calyx explains what data would resolve the assessment gap.
- Display does not infer new IUCN categories from orchid popularity or available literature.

Guardrails:
- The IUCN homepage is not an exact criteria citation; primary criteria verification is a task dependency.

External references (design precedent only):
- https://www.iucnredlist.org/

## LRI-009: Atlas as ecological place, not data-control panel

Priority P1. Applies to modules: atlas, homepage, calyx. Applies to perspectives: orchid, habitat, climate, conservation, pollinator, fungus.

Instruction: Provide a place summary explaining records, habitat and linked relationships before advanced map controls. Keep researcher GIS tools available deeper in the existing module.

Acceptance criteria:
- A place view answers what is observed, what is modeled and what is missing.
- Occurrence, range, modeled suitability and sampling effort have separate legends.
- A persistent explanation names layer source, temporal basis and limitations.

Guardrails:
- No spatial overlap alone is a pollination or fungal interaction.
- Conservation education remains allowed; neither neutrality nor avoiding fundraising is a new constitution.

External references (design precedent only):
- https://www.oneearth.org/bioregions/

## LRI-010: Spatial uncertainty, extrapolation and scale stay visible

Priority P1. Applies to modules: atlas, fungal_perspective, calyx, research_station. Applies to perspectives: fungus, orchid, habitat, climate, conservation.

Instruction: Expose sampling effort, coordinate uncertainty, model confidence and extrapolation as different concepts. Plain-language explanations accompany layers.

Acceptance criteria:
- Unknown layer metrics show unavailable, not zero.
- Global fungal richness is never presented as a specific orchid-fungus association.
- Taxon, geographic and temporal resolution are shown before interpretations.

Guardrails:
- SPUN model predictions are not evidence for the focal orchid's fungal partner.

External references (design precedent only):
- https://www.spun.earth/underground-atlas/mycorrhizal-biodiversity

## LRI-011: Protect sensitive locality before narration or rendering

Priority P0. Applies to modules: atlas, calyx, conservation, species_explorer, brain. Applies to perspectives: orchid, habitat, conservation.

Instruction: Reuse Atlas public-display and server-owned locality policy. Apply it before data reach maps, Calyx context, exports, URLs, citations, logs or downloadable artifacts.

Acceptance criteria:
- Public payload, prose and artifacts cannot leak withheld exact locations.
- Generalized records identify their permitted geographic precision.
- Private access follows existing permission gates; a request to explain does not bypass them.

Guardrails:
- Do not invent a second locality policy or permit client-only obfuscation.

External references (design precedent only):
- https://explorer.natureserve.org/

## LRI-012: Structured context for a docent, not raw activity replay

Priority P0. Applies to modules: calyx, homepage, perspective_engine, species_explorer. Applies to perspectives: orchid, pollinator, fungus, habitat, climate, chemical, literature, conservation, disease, theory, gene, protein.

Instruction: Extend existing CRR-001 bounded evidence packets and current conversation continuity with the focal entity, selected relationship, perspective, authorized evidence IDs, unavailable domains and prior answered topics.

Acceptance criteria:
- UI selection is navigation context only; backend resolves evidence IDs and identity.
- Delayed response for a previous focal entity cannot appear under a new taxon.
- Prior AI answers and design guidance are not scientific evidence.
- Audience-mode adaptation preserves the existing expert/collaborator voice.

Guardrails:
- Do not replace the global Calyx persona with a toy or first-person orchid.
- Use page context without implying the live provider has loaded this package.

External references (design precedent only):
- https://blog.khanacademy.org/how-khan-academy-is-building-a-better-ai-tutor-our-most-recent-learnings/

## LRI-013: Ground explanations; disclose failures without chatbot theater

Priority P1. Applies to modules: calyx, relationship_validator, homepage, ocu. Applies to perspectives: orchid, pollinator, fungus, habitat, climate, chemical, literature, conservation, disease, theory, gene, protein.

Instruction: Calyx uses vetted governed evidence and explicitly labeled review-bound sources, explains limitations naturally, and proposes inspectable next paths. External research remains available under existing authorization.

Acceptance criteria:
- Citation refers to evidence actually supplied or retrieved for this turn.
- Missing evidence produces an honest explanation or bounded authorized research path.
- Calyx does not pretend the report or design graph establishes biology.

Guardrails:
- Do not claim closed-model training; implement retrieval and review gates instead.
- Do not ban external research already permitted by Calyx persona.

External references (design precedent only):
- https://www.news-herald.com/2026/07/24/cleveland-museum-of-arts-reimagined-artlens-gallery-leans-into-ai/

## LRI-014: Alternatives rather than false single-answer precision

Priority P1. Applies to modules: calyx, vision_lab, relationship_validator, species_explorer. Applies to perspectives: orchid, pollinator, fungus, conservation.

Instruction: When identification or relation evidence admits alternatives, present supported alternatives and discriminating evidence rather than a single asserted verdict.

Acceptance criteria:
- Candidate ranking preserves uncertainty and the supporting method.
- No rank is a probability unless a calibrated model supports it.
- A botanically useful next observation/test is offered without auto-verification.

Guardrails:
- Merlin's accuracy numbers and tier names do not transfer to orchids.

External references (design precedent only):
- https://support.ebird.org/en/support/solutions/articles/48000961587-merlin-bird-id-faqs

## LRI-015: Real scientific media, not synthetic evidence decoration

Priority P1. Applies to modules: homepage, vision_lab, species_explorer, calyx, ocu. Applies to perspectives: orchid, pollinator, fungus, habitat, chemical.

Instruction: Use sourced images, specimens and actual datasets to support wonder. Technical immersion must answer a biological question and have an accessible fallback.

Acceptance criteria:
- Media has source, rights, credit and taxon/record linkage.
- Synthetic reconstruction is labeled and cannot imply a recorded interaction.
- Reduced motion and non-3D fallback preserve scientific meaning.

Guardrails:
- A 3D orchid is an optional later enhancement, not the first implementation milestone.

External references (design precedent only):
- https://www.nationalgeographic.com/into-the-amazon/

## LRI-016: Guided exploration complements free research navigation

Priority P1. Applies to modules: perspective_engine, homepage, ocu, atlas, calyx. Applies to perspectives: orchid, pollinator, fungus, habitat, climate, chemical, literature, conservation, disease, theory, gene, protein.

Instruction: Offer finite, evidence-backed tours around a focal organism with inspectable branching and exit. Preserve deeper expert exploration rather than forbidding it.

Acceptance criteria:
- A tour has real canonical entries and accessible text.
- Broken/missing paths are explained; no fake tour buttons.
- Progress and back navigation preserve focal identity.

Guardrails:
- Avoid treating a single linear scroll as mandatory across all ecological domains.

External references (design precedent only):
- https://www.onezoom.org/

## LRI-017: A living evidence history, not a novelty ticker

Priority P1. Applies to modules: orep, brain, calyx, homepage, research_station. Applies to perspectives: literature, orchid, pollinator, fungus, conservation, theory.

Instruction: Expose reviewed additions, corrections, supersessions and retractions using existing evidence/publication lifecycle. Distinguish event date, paper date and observation date.

Acceptance criteria:
- Event identifies affected claim/entity, version and evidence anchor.
- Imported old papers are not announced as newly discovered science.
- Withdrawals/corrections are visible alongside additions; sensitive information remains protected.

Guardrails:
- A feed is unavailable until actual lifecycle events exist; no invented activity.

External references (design precedent only):
- https://eyes.nasa.gov/apps/solar-system
- https://science.ebird.org/en/status-and-trends

## LRI-018: Semantic doorways without duplicate source silos

Priority P0. Applies to modules: brain, orep, species_explorer, calyx, graph_intelligence. Applies to perspectives: orchid, pollinator, fungus, habitat, climate, chemical, literature, conservation, disease, theory, gene, protein.

Instruction: Connect related evidence through existing canonical identity, dossier and semantic annotation paths; do not create another taxon, publication or design store.

Acceptance criteria:
- Guidance resolves to existing KOs/modules and current implementation seams.
- Dossier links source records and relationship receipts without copying their scientific authority.
- Graph projection is private design metadata only.

Guardrails:
- The report characterizes Kew resources as separate catalogues; POWO has since been observed announcing an app-switcher trial, so treat that characterization as time-bound and recheck before relying on it.
- Keep public scientific publication separate from internal design publication.

External references (design precedent only):
- https://www.kew.org/read-and-watch/new-data-portal-live

## LRI-019: Evidence receipt plus a readable explanation

Priority P1. Applies to modules: calyx, atlas, relationship_validator, perspective_engine, ocu. Applies to perspectives: orchid, pollinator, fungus, habitat, climate, chemical, literature, conservation, disease, theory, gene, protein.

Instruction: Pair state/method/scope with a short plain-language explanation of what it permits the visitor to conclude, plus a route to inspect the supporting evidence.

Acceptance criteria:
- No unexplained confidence tag or opaque flag is the entire explanation.
- A numeric indicator is optional and only used if semantically valid.
- Receipts can be read by keyboard and screen reader.

Guardrails:
- NOAA reference is a design-research lead; specific efficacy claims need exact-source verification.

External references (design precedent only):
- https://repository.library.noaa.gov/view/noaa/63628/noaa_63628_DS1.pdf

## LRI-020: Perspective-specific questions over the same canonical graph

Priority P1. Applies to modules: perspective_engine, graph_intelligence, calyx, atlas, species_explorer. Applies to perspectives: orchid, pollinator, fungus, habitat, climate, chemical, literature, conservation, disease, theory, gene, protein.

Instruction: Make the focal identity and perspective explicit. Orchid, pollinator and fungus views ask different questions but preserve the same underlying evidence and relationship status.

Acceptance criteria:
- Re-centering is read-only and cannot invent or promote a new edge.
- Shared-resource or indirect dependency explanations inspect each edge and its scope.
- Weak/inferred/missing links remain visible in multi-hop paths.

Guardrails:
- Paths are hypotheses or connections, not automatically causal chains.
- Market first/only claims in the report are bounded landscape interpretations, not verified originality.

External references (design precedent only):
- https://eol.org/docs/discover/food-webs
- https://www.globalbioticinteractions.org/
- https://science.sandiegozoo.org/science-blog/webapp-exploring-pollinator-networks-sustain-rare-plant-species

## Canon conflicts requiring an owner decision

- LRC-001 Homepage opening sequence: Section B opens with the fragmented record; the proposed direction opens with wonder and one real orchid. HOMEPAGE-DESIGN-0007 (museum mode) already centers one featured organism. Resolution: Owner decision; draft HOMEPAGE-DESIGN-0008 only after review.
- LRC-002 Graph presentation: The Design Book requires an interactive network; the proposed direction wants relationships felt rather than shown as a technical node-link diagram. Resolution: Owner decides whether the relationship-sentence view may be primary with the network as a deeper layer.
- LRC-003 relationship_status name collision: The same field name, relationship_status, carries two meanings: record provenance in KO-0051 and edge lifecycle in the backend migration. Resolution: Never add an eighth vocabulary; build one server-owned public projection that takes V1-V4 and V7 as inputs (LRT-003).
- LRC-004 Two-axis uncertainty from IPCC: IPCC likelihood language implies calibrated probability, which SCIAN-002 forbids for heuristic scores. Resolution: Borrow the evidence-versus-agreement separation only.
- LRC-005 Closed-model docent: The reviewed museum example is a closed curated model; Calyx is a governed-retrieval collaborator that may use authorized external research. Resolution: Borrow grounding and failure honesty, not the closed corpus.
- LRC-006 Living layer versus no auto-publication: A live ticker could imply unreviewed claims are current science. Resolution: Only reviewed lifecycle events; separate recently added to review from recently verified.
- LRC-007 Market-first claims: The report says no live public orchid-specific interactive mapping tool was found; that is a bounded landscape observation, not proof of absence. Resolution: Recheck before using in any public or funding claim.

## Uncertainty vocabulary crosswalk

Eight uncertainty vocabularies already exist. Do not add a ninth. Each answers a different question:

- V1 KO-0051 relationship_status (observed, published, curated, inferred, machine_generated, hypothesis, requires_review, rejected): record provenance and review of a relationship.
- V2 kg_edges.relationship_status (active, superseded, retracted): edge lifecycle.
- V3 ConsensusStatus (STRONGLY_SUPPORTED, SUPPORTED, MIXED_EVIDENCE, CONFLICTING, LIMITED_EVIDENCE, SINGLE_SOURCE, METHOD_DEPENDENT, GEOGRAPHICALLY_LIMITED, ...): agreement across independent evidence.
- V4 SCIAN inference output states: review state of an inferred candidate.
- V5 Calyx evidence labels (Observed, Reported, Inferred, Unresolved, Not yet linked, No evidence available): how Calyx words an assertion for the public.
- V6 Graph provenance display states (validated, extracted but unvalidated, inferred, conflicting, missing evidence, unavailable data source): how a visible relationship exposes provenance.
- V7 Content state rules (verified, evidence_available, provisional_interpretation, unavailable): display state of a data-bearing component.
- V8 Public Calyx relationship coverage (documented, unknown, unavailable): whether linked evidence exists for a domain.
