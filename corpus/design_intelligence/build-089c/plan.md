# PLAN — Calyx Automated Research Acquisition System (Implementation Research Report)

**Mission source**: Chief Research Librarian brief (10 parts) — survey global dissertation repositories, map technical access, design ingestion pipeline, reasoning-extraction methods, idea-evolution tracking, existing software, phased roadmap, and critical review.

**Final deliverable**: Comprehensive implementation research report → `.md` + `.docx` in `/mnt/agents/output/`

---

## Stage 1 — Deep Research (skill: `deep-research-swarm`, Route A wide search)
Load skill at stage start. Six parallel foreground research agents (web search + URL reading). Each returns a structured, source-cited markdown brief saved to `/mnt/agents/output/research/`.

| Agent | Covers | Mission |
|---|---|---|
| R1 Global Repository Survey | Parts 1, 3 | All major ETD repositories worldwide (ProQuest, EThOS, DART-Europe, NDLTD, OATD, EBSCO Open Dissertations, BASE, CORE, OpenAlex, theses.fr/ABES, Shodhganga, CNKI/Wanfang, CAPES/BDTD, DNB, NARCIS/DANS, TROVE, LAC Canada, institutional DSpace/EPrints networks…). All 21 fields per repository + API/OAI-PMH endpoints + doc links + ingestion suitability ranking. |
| R2 Botanical Priority Sources | Part 2 | Repositories richest in Orchidaceae / taxonomy / systematics / pollination / mycorrhiza / anatomy / morphology / physiology / ecology / conservation / evolution / phylogenetics / horticulture. University ETD collections with strong botany programs, botanical institution libraries, regional biodiversity repos. |
| R3 Ingestion Workflow + Document Structure | Parts 4, 5 | End-to-end pipeline design; PDF/ETD parsing stack (GROBID, ScienceParse, CERMINE, ParsCit, anystyle); section/chapter segmentation; figure/table extraction; taxonomy name extraction (gnfinder, TaxonFinder); LLM-assisted structure detection. |
| R4 Scientific Reasoning Extraction | Part 6 | Argument mining, scientific discourse models (ART/ANL/SciArg), hedging/uncertainty detection, claim/evidence extraction, SciBERT-class models, LLM extraction; which NLP/AI approaches are most promising per reasoning category. |
| R5 Idea Evolution Tracking | Part 7 | Dissertation→article→citation lineage (OpenAlex, Semantic Scholar, Crossref Event Data, Scite), replication/contradiction detection, corrections/retractions (Retraction Watch, Crossmark), taxonomic revision chains (IPNI, POWO, WFO), consensus reconstruction. |
| R6 Existing Software Landscape | Part 8 | Open-source/commercial systems covering any pipeline segment (DSpace/Invenio/Samvera, harvesters, PKP, Zotero/translation-server, Unpaywall, OpenHarvesters, VIVO, etc.) — strengths/weaknesses/license/reuse/integration. |

Stage-gate: all 6 briefs validated (citations, coverage, concrete endpoints) before Stage 2.

## Stage 2 — Report Writing (skill: `report-writing`)
Load skill at stage start. Assemble research briefs into the full 10-part report. Writers draft assigned parts from the research corpus (not new research). Main agent integrates into `Calyx_Research_Acquisition_Report.md`. Parts 9 (roadmap) + 10 (critical review) synthesized from all briefs.

## Stage 3 — Word Delivery (skill: `docx`)
Load skill at stage start. Convert final `.md` → `Calyx_Research_Acquisition_Report.docx` with professional formatting (TOC, headings, tables). Deliver both files.

## Rules
- Research agents: verifiable sources, concrete URLs/endpoints, no fabrication; mark unknowns explicitly.
- Writers: no new research; structured, actionable, technical depth.
- Language: English. Tone: implementation-focused, critical where required (Part 10 must be a real critique, not praise).
