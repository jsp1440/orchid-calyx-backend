# Calyx Deep Research — Cross-Verification (Phase 4–5)
**Date:** 2026-07-21 | **Inputs:** calyx_wide01–06.md, calyx_dim01–12.md (all under /mnt/agents/output/research/)

## 1. HIGH CONFIDENCE (verified live by ≥1 agent, corroborated by ≥2 agents or authoritative source)

| Finding | Evidence |
|---|---|
| NDLTD union OAI archive is live and harvestable: `https://ndltdunion.cs.uct.ac.za/OAI-PMH/`, ~7.9M records, 212 sets, 6 metadata prefixes (incl. oai_etdms) | dim01 live-probed all verbs; supersedes wide01's 6.54M estimate and "search UI down" concern (search.ndltd.org remains 503 — discovery UI ≠ harvest channel) |
| OpenAlex is the viable metadata spine: 11.02M `type:dissertation` core works / 20.26M with XPAC; 497 Orchidaceae-concept dissertations core (667 XPAC); 10/10 precision in manual sample | dim04 live API queries 2026-07-21 |
| OpenAlex freemium now enforced: free tier = $1/day credit with free API key; anonymous $0.10/day; PDF/full-text content $0.01/file; **free snapshot now QUARTERLY** (monthly = paid); Content API serves 60M+ OA PDFs + GROBID TEI at content.openalex.org | dim04 live 429s + Phase-5 validation (developers.openalex.org, June 2026; Q2-2026 town hall) |
| DataCite: 818,074 `resourceTypeGeneral:Dissertation` DOIs + ~740k "Thesis"; CC0; GraphQL retires 2027-07-01 | dim04 live queries |
| Crossref: 1,062,500 type:dissertation; retraction 73,700 / correction 209,348 / EoC 4,094 records; RW CSV daily on GitLab | dim04, dim09 live counts |
| DART-Europe permanently closed Feb 2025 → successors: OpenAIRE (~2.6M theses), BASE (~3.75M), national nodes | dim02 confirmed, wide02/03 concur |
| CiNii Dissertations ended 2025-05-12 (merged into CiNii Research); IRDB OAI (`irdb.nii.ac.jp/oai`) live; OpenAlex ingested 4.6M IRDB records Q1 2026 | dim03 live probe + OpenAlex town hall corroboration |
| theses.fr: OAI at `http://staroai.theses.fr/OAIHandler`; ddc:580 botany set + `diffusable` full-text set live; Etalab OL 2.0; data.gouv.fr dump stale since 2024-01 (gap-fill via OAI/API) | dim02 live probes |
| DNB: OAI + `dnb:reiheH` Hochschulschriften tree (incl. sg580 Botanik) + SRU verified live; GND CC0 | dim02 |
| EThOS post-relaunch: 650k+ records, no login, CC0 CSV (v9 2022, 610,535 records), ~65% IR full-text links, no central PDFs | dim02 vs BL pages |
| NVA Norway: live public API, DegreePhd 36,162 / DegreeMaster 225,445 | dim02 live |
| Tier-1 botanical OAI endpoints verified live: Leiden (OpenDissertations set = 7,764 records), Kew Research Repository (9,361 records; OAI passes though UI Cloudflare-blocked), OpenUCT, UH ScholarSpace, Bayreuth, KU Leuven, Imperial Spiral, UPM (21 orchid-title theses — top IR orchid-title yield) | dim05, 28 live probes |
| CNKI international access restored April 2024 (oversea.cnki.net / East View license) — licensed-only, no bulk | dim03, CDL-confirmed; corrects wide02 "suspended" framing |
| Retraction tracking solved & open: Crossref absorbed Retraction Watch (2023); OpenAlex `is_retracted` has ~2,300 false flags (Hauschke & Nazarovets 2024) → merge RW CSV | dim09 |
| S2AG citation contexts: 2.4B records, ODC-BY, releases current (2026-07-14) | dim09 |
| WCVP v15 exists (Jan 2026, DOI 10.34885/rvc3-4d77); annual versioned snapshots with DOIs; no official per-version release notes | dim09; supersedes wide06's v14 |
| gnfinder: 15M pages/h, F1 0.86, verbatim sp. nov./comb. nov. detection; GBIF /species/match live | wide05, dim09 |
| GROBID: best metadata/reference extraction (F1 ~0.87–0.90 refs), ~10.6 PDF/s on 16-CPU; production-proven (OpenAlex/S2/HAL) | wide05, dim07, Meuschke 2023 benchmark |
| No tool natively segments thesis chapters reliably: READoc v2 shows ~22 TEDS drop heading-detection→tree nesting across all systems | dim07 (benchmark paper) |
| InvenioRDM v13 (MIT) fit for registry; oaipmh-scythe (BSD-3) is the maintained harvester (Sickle stalled) | dim06, dim11 (GitHub/PyPI live) |
| Legal hard rules: lawful-access precondition (Bartz v. Anthropic 2025); no redistribution of non-CC full text; machine-readable opt-outs (OLG Hamburg Dec 2025: only machine-readable counts under Art. 4(3)); OAI deleted-record embargo compliance | dim10 (primary legal sources) |
| Direct long-tail OAI harvesting is operationally fragile: >1/5 repositories offline, ~44% OAI-PMH endpoints dead (Macgregor 2026); ~25% repository HTTP requests fail | dim12 (peer-reviewed infrastructure study) |
| Only ~32% of world theses are OA; ~10–26% ETDs embargoed; ~41% of dissertations never yield a peer-reviewed publication | dim12 (survey literature) |

## 2. MEDIUM CONFIDENCE (single authoritative source, or verified but fast-changing)

- **Marker 2.0.0 relicensed Apache-2.0 (code) 2026-07-20** — verified in PyPI/LICENSE by dim11 one day after release; model-weight licensing (historically OpenRAIL-M / cc-by-nc-sa revenue caps) NOT yet re-verified → treat as: code Apache-2.0, weights caveat pending legal read. [MED]
- MinerU 3.x custom Apache-based license (commercial OK under 100M MAU/$20M monthly revenue) — official repo, bespoke terms. [MED]
- MinIO CE archived 2026-04-25 → use SeaweedFS/managed S3. [MED-HIGH, GitHub]
- LA Referencia OAI `oai.lareferencia.info/request` live (1,480,679 records) and NOT Anubis-blocked (portal is); earliestDatestamp buggy → incremental harvest via set-diffing. [MED, dim01 live]
- Trove API v3: thesis metadata = Level-1 approval, `bulkHarvest=true`, `l-format=Thesis`; AI/ML use needs Level 3–4 + possible data-sharing agreement. [MED-HIGH, dim03 official docs]
- RISS Korea OpenAPI exists (application-based via KERIS). [MED, dim03]
- Shodhganga geo-block re-confirmed; fallback = OpenAlex source S4377209701 (117,620 works, stale) with direct bitstream-PDF landing URLs. [MED]
- BDTD OAI endpoint correct but behind "Oasisbr" anti-bot interstitial; ~565k dissertations + 214k theses. [MED]
- Rubin Certainty corpus / AZ-II access terms not openly licensed; BioScope subcorpus counts approximate. [MED, dim08]
- OhioLINK OAI carries oai_etdms rights text → CC vs ARR machine-capturable. [MED-HIGH, dim01]
- scite pricing: Basic $20/Pro $50/user; bulk API Enterprise-only → build-own-classifier recommendation stands. [MED-HIGH, dim09]

## 3. CONFLICT ZONE (documented, with resolution status)

| # | Conflict | Status |
|---|---|---|
| C1 | OpenAlex snapshot cadence: help-center pricing page says "monthly"; developers.openalex.org (2026-06-27) says free snapshot **quarterly**, monthly/daily = paid | **RESOLVED** — Phase-5 validation: quarterly for free tier is current (June 2026 docs supersede stale help page). Plan for quarterly + API deltas within free credit. |
| C2 | Marker license: wide05 reported GPL-3.0; dim11 found Apache-2.0 relicense dated 2026-07-20 | **PARTIALLY RESOLVED** — temporal change, both were right at their check dates. Code Apache-2.0 confirmed; weight licensing unresolved → flag for legal read before redistribution; Docling (MIT) remains license-safe default. |
| C3 | LA Referencia counts: portal claims ~4.65M docs; OAI endpoint exposes 1,480,679 records | **UNRESOLVED** — no public explanation (Phase-5 search found nothing). Likely OAI subset/harvest lag. Action: query per-country sets and diff; contact RedCLARA. Documented as open question. |
| C4 | ProQuest PQDT size: 5M / 5.5M / 6M+ citations across sources | **UNRESOLVED** — marketing figures vary; treat as "~5.5M+ citations, 3M+ full text" with LOW-MED confidence; immaterial to design (PQDT is licensed-only anyway). |
| C5 | OpenAlex vs Retraction Watch retraction flags disagree (~2,300 false OpenAlex flags) | **RESOLVED by design** — merge RW CSV as ground truth; OpenAlex flag as signal only. |
| C6 | HathiTrust thesis identification: wide01 implied genre fields; dim01 found bib_fmt lacks thesis granularity | **RESOLVED** — use MARC 502/imprint heuristics via Bib API; HathiFiles alone insufficient. |
| C7 | OATD record count: homepage 7.46M vs FAQ 3.5M (stale) | **RESOLVED** — 7.46M current; OATD itself unscrapable (Cloudflare) but its 1,100+ source list recoverable via Wayback 2024-07-08 snapshot. |

## 4. CONSISTENT CROSS-AGENT SIGNALS (independent convergence — strongest evidence class)

1. **Aggregator-first beats endpoint-gardening.** dim01 (OATD blocked, use source list), dim03 (national nodes > blocked federation portals), dim04 (OpenAlex spine + XPAC), dim06 (aggregator-first full text), dim12 (44% endpoints dead; zero long-tail harvesting) — five independent agents converged: harvest few big channels, resolve full text via aggregators/OpenAlex Content API, keep direct OAI only for Tier-1 botanical precision sources.
2. **License capture at ingest is the compliance linchpin.** wide03, dim06, dim10 all independently: most ETD records lack machine-readable licenses → license-gate per record, default all-rights-reserved, repo-default policies to shrink review queue.
3. **Anti-bot escalation is systemic, not incidental.** LA Referencia/RENATI (Anubis), BDTD (Oasisbr), OATD/UKZN/UCL/QMUL/RHUL (Cloudflare/WAF), Swepub (Anubis despite free-reuse policy), Shodhganga/YÖK (geo) — across dim01/02/03/05. Cloudflare default AI-crawler blocking from Sept 2026 (dim06) worsens it. Architecture must treat blocked hosts as routine (aggregator fallback + admin contact + manual queue), never stealth.
4. **LLMs scoped, classical-first.** wide05, dim07, dim08 concur: deterministic parsing + classical classifiers where corpora exist; LLM only on pre-filtered spans with JSON-schema constraint + verbatim-span hallucination gate; cost driver is LLM passes, not parsing.
5. **Snapshot-first posture against freemium drift.** OpenAlex (credits, quarterly), CORE (recent dumps paid), BASE (gated), scite (Enterprise) — dim03/04/06/09/12: download free snapshots/dumps NOW, treat APIs as delta/enrichment channels.

## 5. UNRESOLVED / OPEN QUESTIONS (carried to report as explicit caveats)
- U1: LA Referencia OAI-vs-portal count gap (C3).
- U2: Marker model-weight license post-2026-07-20 (C2) — legal read required.
- U3: EThOS 2026-refreshed CSV existence (v9 2022 confirmed; refresh unverified).
- U4: NDLTD union archive rate policy (pilot needed before bulk).
- U5: XPAC dissertation-slice precision at scale (10-sample core was clean; XPAC-only unsampled).
- U6: US AI-training case law appellate trajectory; India ANI v. OpenAI judgment (reserved Apr 2026); Brazil PL 2338; UK TDM reform dropped 2026-03-18.
- U7: CORE API thesis counts (no key during research); CORE dump recency vs paid tiers.
