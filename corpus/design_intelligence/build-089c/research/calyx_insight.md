# Calyx Deep Research — Cross-Dimension Insights (Phase 6)
**Date:** 2026-07-21 | Derived from wide01–06, dim01–12, cross_verification.

---

## Insight 1 — The discovery layer is solved; the acquisition layer is where Calyx creates (and keeps) value
**Derived from:** dim01, dim03, dim04, dim12; wide03.
**Rationale:** Between OpenAlex XPAC (20.26M dissertation-typed records, CC0), DataCite (818k thesis DOIs), Crossref (1.06M), NDLTD union (7.9M OAI), and CORE (452M records), *finding* theses is a solved problem — the marginal cost of one more metadata record is near zero. What none of these provide reliably is (a) rights-aware full-text acquisition, (b) per-record license state, (c) anti-bot-blocked hosts. Calyx's defensible asset is therefore not an index but the **rights-verified document store + license registry** built on top of free spines. Every architecture dollar should flow to rights/registration/provenance, not discovery.
**Implications:** Phase 1 needs no crawler fleet; it needs a license engine and a content-addressed store. Report should reframe "repository survey" as "acquisition-channel portfolio."
**Confidence:** high.

## Insight 2 — OpenAlex's 2026 pivot quietly became Calyx's full-text channel — and its biggest dependency risk
**Derived from:** dim04, dim06, dim12 + Phase-5 validation (Q2-2026 town hall).
**Rationale:** The Content API (60M+ OA PDFs + GROBID TEI at predictable URLs, $0.01/file, 62M-row Parquet manifest) means Calyx can acquire OA thesis full text *and pre-parsed structure* from one vendor-neutral-key endpoint — collapsing dim06's "polite per-host download" problem for the OA subset. Simultaneously, OpenAlex went keyed-freemium ($1/day free credits, quarterly free snapshots, paid monthly/daily) — the exact pattern dim12 warns about ("free upstream tiers are a subsidy that shrinks"). The same entity is both the best new pathway and the canonical sustainability risk.
**Implications:** Adopt OpenAlex Content API as primary OA full-text source *and* mirror everything consumed into Calyx's own store on first touch (snapshot-first posture); never design live-query dependencies into serving paths.
**Confidence:** high.

## Insight 3 — Orchid research geography inverts the harvesting priority list
**Derived from:** wide04, dim03, dim05, dim12.
**Rationale:** Orchid-relevant theses concentrate in Latin America (388 of 2,296 Orchidaceae-concept dissertations; UNAM/UIS/UFRGS/UNESP nodes), South/Southeast Asia (UPM Malaysia = top orchid-title IR; Shodhganga 42 orchid-title), and South Africa (UKZN/UCT) — precisely the regions where infrastructure is weakest (Anubis/geo-blocks, no bulk APIs, stale OpenAlex coverage: single-digit CN/IN/KR/TR indexing). Meanwhile the technically-easiest sources (US/EU Tier-A OAI) are orchid-sparse (Kew ~15–30 orchid theses of 9,361 records; Leiden 30–60 of 7,764). **Acquisition difficulty and botanical value are anti-correlated.**
**Implications:** A purely technical "harvest what's easy" plan systematically under-collects exactly the flora Calyx exists for. The roadmap needs an explicit "hard-region strategy" (partner egress, national-node MoUs, OpenAlex-XPAC resolution, curated manual batches for UKZN/Shodhganga) as a first-class workstream, not an afterthought.
**Confidence:** high.

## Insight 4 — The reasoning corpus's scientific credibility depends on three thin-evidence categories — and the annotation program is therefore the critical path, not the models
**Derived from:** wide05, dim07, dim08.
**Rationale:** Parsing/structure is benchmark-mature (GROBID ~0.9 F1 refs; Docling/Marker/MinerU layout). But *Assumptions*, *Alternative explanations*, and *Speculation-vs-hypothesis-vs-opinion boundaries* have essentially no training corpora (ARCHE 2026 shows even frontier LLMs fail at latent reasoning chains), and *no thesis-native labeled corpus exists at all*. Every category's production quality is gated by the same artifact: a double-annotated gold set (~12 chapters, ~220–260 person-hours, $8–15k via INCEpTION). Fine-tuned small models then beat zero-shot LLMs by 15–40 F1 at ~20× throughput — but only after that gold set exists.
**Implications:** Sequence the roadmap: gold-set annotation starts in Phase 1 (parallel with ingestion), LLM-scoped extraction ships as scaffolding, per-category fine-tunes replace LLMs as data accrues. Budget for annotation before GPUs.
**Confidence:** high.

## Insight 5 — The "evolution of scientific ideas" is feasible today only for its mechanical third; the semantic two-thirds need a botany-specific redefinition
**Derived from:** dim09, dim06, wide06.
**Rationale:** Feasible now: retraction/correction graph (Crossref+RW CSV, verified counts), citation-context traversal (S2AG 2.4B contexts), taxonomic name pinning + WCVP version drift (v15, ChecklistBank diffs). Not feasible turnkey: thesis→article lineage (no API anywhere; NBER w33944 shows it's a bespoke record-linkage build with no ground truth), contradiction/consensus (scite Enterprise-gated; own classifier needed). And in botany, "replication" rarely exists as formal replication — the living signal is *taxonomic re-circumscription, re-sequencing, and Flora-treatment updates*. Synonym drift across WCVP versions (67% of names are synonyms; est. 1–5% accepted-concept churn/version) is itself a measurable, botany-native "idea evolution" trace no generic system captures.
**Implications:** Part 7 should be reframed: ship the mechanical third in Phase 2–3, define botany-native evolution signals (WCVP drift ledger, treatment updates, nomenclatural acts from theses via gnfinder sp. nov. detection → IPNI linkage) as Calyx's distinctive contribution, and defer generic consensus reconstruction.
**Confidence:** high.

## Insight 6 — Compliance can be 90% automated — but only as a *policy engine*, not as legal judgment
**Derived from:** dim10, dim06, dim01/02/03 (anti-bot evidence).
**Rationale:** The five hard rules (lawful access only; no non-CC full-text redistribution; machine-readable opt-out honoring; license-gated default-ARR; locality fuzzing) are all mechanically encodable: SPDX/rightsURI parsing, robots.txt/TDMRep/RFC 9309 detection, OAI deleted-record processing, CC-class gating, CITES/genera fuzz lists. What cannot be automated: jurisdictional drift (India ANI judgment reserved, Brazil PL 2338 pending, UK reform dropped, EU Art. 3 "lawful access" CJEU-untested) and ambiguous cases (repo-default rights, orphaned licenses). Hence the decision matrix needs exactly three lanes — auto-allow, auto-deny, human-review — with the review lane sized for ~10–30% of records initially.
**Implications:** Build the compliance layer as config-driven rules + full provenance logging (license snapshot at acquisition time), with a quarterly legal-watch task. This is cheap and converts Part 10's biggest risk into an operational routine.
**Confidence:** high.

## Insight 7 — The honest Phase-1 scope is six channels, not six hundred endpoints — and go/no-go metrics should gate Phase 2
**Derived from:** dim12, dim01, dim04, dim05, cross-verification conflict-zone resolutions.
**Rationale:** Macgregor 2026's endpoint-mortality data (44% OAI dead) + staff-cost reality (0.5–1 FTE endpoint gardening forever) + OpenAlex/CORE/OATD/NDLTD/EThOS/BDTD coverage overlap means Phase 1 = OpenAlex snapshot (+Content API) + CORE dump + NDLTD union OAI + theses.fr + EThOS CSV + ~10 verified Tier-1 botanical OAI endpoints. That yields the orchid corpus with <5% of the maintenance surface. Compute is trivial (<$5k at 100k-thesis scale with olmOCR/Marker + scoped Flash-class LLM passes); duplication is not (30–50% raw; OpenAIRE ~52% publication duplication) — so dedupe precision is the real Phase-1 quality gate.
**Implications:** Report Part 9 roadmap: Phase 1 gated on ≥30k orchid-relevant parsed theses, ≥85% dedupe precision on audit, complete per-source license register, <$5k compute. If the true near-term goal is serving orchid researchers, a curated 5–10k orchid-only corpus delivers more value per dollar than any scale play — Part 10 must say this plainly.
**Confidence:** high.

## Insight 8 — Calyx's registry should itself be a repository (InvenioRDM) emitting the same protocols it consumes — turning compliance into discoverability
**Derived from:** dim06, dim11, wide06.
**Rationale:** Running InvenioRDM gives Calyx OAI-PMH *provider*, REST deposit, versioning, and DOI-mintable annual snapshots (the WCVP v15 model) for free. Publishing Calyx's own derived dataset (metadata + extracted claims as nanopublications, never non-CC full text) as versioned, DOI'd snapshots makes the corpus citable, reproducible, and positions "evolution of scientific reasoning" releases as first-class scholarly objects — while the OAI provider feeds Calyx back into NDLTD/OpenAlex/OpenAIRE, amplifying Orchid Continuum visibility at zero marginal cost.
**Implications:** Architecture spec: InvenioRDM as system-of-record; annual "Calyx Corpus vN" snapshot DOIs; qlever SPARQL read endpoint with WDQS-style limits for the reasoning ledger.
**Confidence:** medium-high.
