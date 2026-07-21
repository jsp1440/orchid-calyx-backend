# Calyx Deep-Dive Dimension 06 — Ingestion Pipeline Engineering
## Harvest → Rights → Registration → Download Automation Spec

Date: 2026-07-21. ~30 targeted searches; official docs/papers consulted include the OAI-PMH 2.0 spec, oaipmh-scythe repo, ResourceSync/NISO Z39.99, CORE's CHARS ingestion-pipeline paper (MTSR 2017), InvenioRDM v13 docs, DSpace RestContract, RFC 9309, W3C TDMRep, DataCite schema 4.4, NDLTD ETD-MS 1.1, CC REL (W3C submission), HTRC non-consumptive policy. Confidence tags: [HIGH] official docs/primary paper; [MED] credible secondary; [LOW] inference/extrapolation.

---

## 0. Architecture at a glance

```
[Endpoint Registry] → [Harvester (oaipmh-scythe + resync)] → [Raw Record Store (S3/MinIO, WORM)]
        ↓                        ↓ Celery/RabbitMQ queues (CHARS pattern)
[Normalize: oai_dc/ETD-MS/xoai/DataCite → Calyx-JSON] → [Rights Verifier] → [Decision Router]
        ↓                                                        ├─ metadata-only
[Registry: InvenioRDM] ←─────── dedupe/merge ←──────────────────┼─ fetch-fulltext
        ↑                                                        └─ human-review queue
[Downloader (per-host token bucket, robots-aware, ClamAV)] → [CAS blob store: sha256/ab/cd/hash.pdf]
        ↓
[PROV ledger + Prometheus/Grafana metrics]
```

Component choices: **oaipmh-scythe** (Python, BSD-3, active 2026) for OAI-PMH; **resync** library for ResourceSync where offered; **Celery + RabbitMQ** worker/queue backbone (mirrors CORE CHARS [^8^] and SHARE's RabbitMQ+Celery [^8^]); **InvenioRDM v13** as registry; **PostgreSQL** state DB; **MinIO/S3** for raw + content-addressed blobs; **ClamAV clamd** sidecar; **RapidFuzz + blocking** for dedupe; **Grafana/Prometheus** for metrics. [HIGH for tool facts]

---

## 1. Harvester layer

### 1.1 oaipmh-scythe capabilities/limits
Verified from the repo README [^1^]: fork of Sickle (mloesch), Python ≥3.10, built on **httpx** (sync+async-capable client) + **lxml**; supports **all six OAI verbs**; Pythonic iterators; auto-deserialization of oai_dc to dicts; **option to ignore deleted items** (`ignore_deleted`); context-manager sessions. Actively maintained (2026). [HIGH]

Limits (observed/inferred): it is a *client library*, not a scheduler — no built-in cron, no persistent checkpointing of resumptionTokens across process restarts, no per-endpoint rate policy. Scythe/Sickle-style iterators follow resumptionTokens automatically within a run; **Calyx must persist the last resumptionToken + request parameters itself** to resume after crash mid-list. OAI idempotency (a repository must accept re-issued tokens) makes re-issuing the last token the correct recovery primitive [^13^]. [HIGH for protocol, MED for scythe gap framing]

### 1.2 Incremental harvesting (OAI-PMH 2.0 spec facts [^2^])
- `from`/`until` datestamps on ListIdentifiers/ListRecords; **inclusive both ends**; from ≤ until else `badArgument`.
- Day granularity mandatory; seconds (`YYYY-MM-DDThh:mm:ssZ`) optional — declared in `Identify.granularity`. **Calyx config: always query `Identify` first; cache granularity, earliestDatestamp, deletedRecord policy, adminEmail per endpoint.**
- Datestamp must be bumped on any metadata change; therefore incremental harvest with `from = last_successful_harvest − overlap` catches updates. Recommended overlap: **2 days** (timezone/day-granularity safety per UIUC tutorial guidance [^13^]); 1 s if the repo advertises seconds granularity + proper UTC.
- **resumptionToken**: opaque; empty token element = end of list; optional attributes `completeListSize`, `cursor`, `expirationDate`; when resuming, *only* the token is passed (all other params omitted) [^2^][^14^]. Flow control: server may answer **503 + Retry-After**; ignoring it may earn 403 [^14^]. Scythe handles token-following; Calyx adds: honor Retry-After via httpx retry transport, checkpoint after every page.
- **Deleted records**: `Identify.deletedRecord` ∈ {no, transient, persistent}. Headers with `status="deleted"` carry no metadata; persistent repos keep advertising deletions — Calyx processes them into the registry as **tombstone events** (metadata withdrawn; full text quarantined if policy requires) — this is the embargo/takedown compliance path. For repos with `no`/`transient`, schedule periodic full `ListIdentifiers` diff (same technique InvenioRDM itself recommends for its own OAI server [^12^]). [HIGH]

### 1.3 ResourceSync as alternative
ANSI/NISO Z39.99-2017: Sitemap-based; **Resource List, Change List, Resource Dump, Change Dump, Capability List**, discovered via `/.well-known/resourcesync`; change events typed created/updated/deleted with fixity (sha-256 supported in the reference `resync` client v1.0.6+ [^4^]); push notification via PubSubHubbub-style channels [^3^]. Basis of **CORE FastSync** [wide03]. Rule: **if a repository exposes a capability list, prefer ResourceSync for bulk/file-level sync; use OAI-PMH otherwise** (OAI-PMH remains near-universal on DSpace/EPrints/Digital Commons). [HIGH]

### 1.4 Scheduling & failure recovery at scale (CORE/OpenAIRE patterns)
CORE's CHARS (production, 70M records at paper time) [^8^]:
- Microservice workers behind **RabbitMQ queues** (pub/sub; chose RabbitMQ over Kafka for message *priorities*); a **scheduler** enqueues repositories whose records are older than a freshness window; cron lines up periodic re-harvest; supervisor API endpoint for manual submission.
- Worker lifecycle: notify-start → collect → perform → finalize+metrics → assess success/failure → notify-end. **Fail-fast validation after each task**, not end-of-pipeline.
- Recovery: tasks resume automatically after failure/redeploy ("task is not lost"); article-level (not repo-level) parallelism for extraction/enrichment/indexing stages.
- Full-text discovery: extract links from metadata; if absent, crawl landing page to limited depth ("harvesting levels"); pattern-compose PDF URLs per platform [^8^][^9^].
OpenAIRE (D-NET toolkit) harvests OAI-PMH metadata into an XML graph; its interest is metadata+enrichment, not full text [^8^]; SHARE: RabbitMQ + Celery scheduler + Elasticsearch [^8^]. Calyx adopts: Celery beat + RabbitMQ, queue-priority classes {new-repo bootstrap, freshness re-harvest, takedown-urgent, manual}. [HIGH]

---

## 2. Rights-verification automation

### 2.1 License signal extraction (ordered precedence)
1. **DataCite `rightsList`** (schema 4.4): `rightsURI`, `rightsIdentifier` (e.g. `CC-BY-4.0`), `rightsIdentifierScheme` (SPDX), `schemeURI`; also `info:eu-repo/semantics/openAccess` values [^16^]. Machine-parse directly. [HIGH]
2. **oai_dc `dc:rights`** — free text or URL; regex/SPDX-URI match; ETD-MS maps dc.rights→MARC 540 (rights statement) [^17^].
3. **ETD-MS v1.1** thesis block (degree name/level/discipline/grantor) — no license element beyond dc.rights; EThOS-style records add **embargo end date** [^17^][^18^].
4. **CC REL / RDFa on landing pages** (`rel="license"`, `cc:attributionName`) and **XMP in PDFs** — the W3C ccREL submission defines RDFa (web) + XMP (standalone media) as default syntaxes [^19^]. Parse landing pages when metadata is silent. [HIGH]
5. **Repository-level default policy**: many IRs publish a default license/statement in their deposit license or OAI `Identify/description` (rightsManifest container exists in OAI-PMH 2.0 for collection-level rights [^15^]). Store per-endpoint default with confidence=repo-default. [MED]

### 2.2 Embargo handling
- Signals: embargo end-date fields (EThOS pattern [^18^]), `dc.date.available`, DSpace `dc.embargo.lift`/bitstream policies, repository access-rights text. Note the DCMI distinction: `dc:accessRights` (who may access — embargo) vs `dc:license` (reuse terms) — parse both separately [^16^].
- Behavior: embargoed → register metadata now, **schedule re-check at embargo end +1 day**, no full-text fetch until then; deleted-record events always honored immediately (§1.2). [MED]

### 2.3 Opt-out / reservation detection (current standards state)
- **RFC 9309** (2022, Proposed Standard): robots.txt parsing/semantics; voluntary, "not a form of access authorization"; 404 robots = allowed, **5xx robots = assume full disallow**; cache ≤24h [^10^][^11^]. Calyx crawler honors it (UA-identified, group matching, longest-match Allow/Disallow).
- **TDM opt-outs**: W3C **TDMRep** (finalized May 2024): three surfaces — `/.well-known/tdmrep.json`, `<meta name="tdm-reservation" content="1">`, HTTP header `tdm-reservation: 1` [^20^]. German case law (**OLG Hamburg, Kneschke v. LAION, 2025-12-10**): Art. 4 DSM opt-out valid **only if machine-readable** — robots.txt, X-Robots-Tag, TDMRep all count; natural-language ToS does not [^21^]. EU AI Act Art. 53(1)(c) (in force since 2025-08-02 for GPAI providers) + Code of Practice require respecting robots.txt per RFC 9309 [^21^]. IETF **aipref** WG is standardizing AI-use preferences (Content-Usage in robots.txt) — monitor. [HIGH for TDMRep/case; MED for aipref maturity]
- Calyx implements a **reservation scanner**: robots.txt (RFC 9309) + TDMRep header/meta/json + X-Robots-Tag noai. Any positive reservation → route per decision matrix (EU research-org Art. 3 has no opt-out for TDM, but *lawful access* is still required and redistribution is never excused [wide03]).

### 2.4 Decision matrix

| License observed | Access/embargo | Reservation signal | Action |
|---|---|---|---|
| CC-BY/CC0/CC-BY-SA/CC-BY-NC (SPDX ID or CC URI in rightsList/dc:rights/CC REL) | open | none | **fetch-fulltext**; store license + attribution |
| CC license, any | open | TDMRep/robots reservation on PDF host | fetch fulltext (license grants reuse) but **log reservation**; skip AI-training use of NC/ND; review [MED] |
| No license; `info:eu-repo/semantics/openAccess` or OA repo default | open | none | fetch-fulltext for **internal TDM only** (US fair use / EU Art. 3); **never redistribute**; flag no-redistribution |
| No license | embargo active | — | metadata-only; schedule re-check at lift date |
| Conflicting signals (CC in metadata vs © page, NC vs commercial use) | any | any | **queue-for-review** |
| Landing page 403/login; Cloudflare challenge persistent | — | — | manual-contact queue; try aggregator copy (§4.3) |
| Deleted header / takedown | — | — | tombstone; quarantine file |

[Confidence: HIGH for signal mechanics; MED for the legal-action column — counsel review advised.]

---

## 3. Document registration — InvenioRDM

Verified facts (InvenioRDM docs/releases) [^5^][^6^][^12^]:
- **v13 (2025-07-22)** added a **Thesis optional-field group** (university, degree, department etc.) + dedicated **copyright** field; older `thesis:university` custom field was migrated to `thesis:thesis.university` (Zenodo migration recipe documents the custom-fields init/copy/reindex workflow). [HIGH]
- Custom fields are configured via three variables: `RDM_NAMESPACES`, `RDM_CUSTOM_FIELDS`, `RDM_CUSTOM_FIELDS_UI`; initialize with `invenio rdm-records custom-fields init`; optional contribs exist for journal/imprint/thesis/meeting/software. **Calyx adds a `calyx:` namespace** for lineage fields: source endpoint, harvest run ID, license-observed + license-source, PROV record URI, dedupe cluster ID, sha256. [HIGH]
- **OAI provider**: invenio-oaiserver; sets via admin/REST (query/percolator-based); `OAISERVER_ID_PREFIX`, `OAISERVER_GRANULARITY`, `OAISERVER_PAGE_SIZE`, `OAISERVER_RESUMPTION_TOKEN_EXPIRE_TIME` configurable; **deleted-record policy = `no`** — InvenioRDM explicitly tells harvesters to diff ListIdentifiers (mirror this caveat in Calyx's own downstream feeds). OpenAIRE sets included by default since v11. [HIGH]
- REST API for programmatic deposit; versioning (new-version relation); **v13 adds audit logs + compare-revisions** — useful for the audit requirement. [HIGH]
- Jobs feature (Celery-backed, UI/REST) for recurrent tasks. [HIGH]

**Alternatives**: DSpace 7–10 — full HAL/HATEOAS REST contract (JWT auth, CSRF token, JSON-Patch RFC 6902, bitstream endpoints with MD5 checksum + range download) [^7^]; viable but Java-heavy and no built-in thesis-typed schema nicety; Hyrax/Samvera only if preservation-grade (Fedora/OCFL) needed [wide06]. Recommendation: **InvenioRDM**. [HIGH]

**Internal ID scheme**: `calx:` + UUIDv7 (time-ordered) as record PID; external IDs kept in `alternateIdentifiers` typed list (DOI, Handle, URN:NBN, OAI-ID `oai:{repo}:{id}`, OpenAlex WID, ProQuest). OAI-ID of Calyx's own provider: `oai:calyx.<domain>:<uuid>`. [LOW-MED, design choice]

---

## 4. Polite full-text acquisition

- **Identity**: descriptive User-Agent with contact + `From` header (OAI etiquette guidance [^13^]).
- **Per-host token bucket**: default 1 req / 2 s per host (OAI best-practice 1–2 s between paged requests [^13^]); honor `Crawl-delay` (non-standard but widely deployed [^11^]) and `Retry-After` (429/503 → exponential backoff, jitter, max 6 retries).
- **Concurrency**: global ~32–64 download workers, but **per-host semaphore = 1–2** (arXiv's published rule of 1 request/3 s, single connection, is a good ceiling exemplar [^22^]).
- **robots**: fetch+cache robots.txt ≤24 h; treat 5xx-on-robots as disallow-all (RFC 9309 [^10^]).
- **Cloudflare-blocked hosts** (cf. POWO precedent — "public API but bot-guarded" [wide06]): legitimate paths only — (a) try alternate copies: **CORE** (API/dump, ~57M full texts), Unpaywall `best_oa_location`, HathiTrust/HTRC (Extracted Features/TORCHLITE for non-consumptive features; Data Capsules for member researchers [^23^]), DataCite media links; (b) email repository admin (adminEmail from `Identify`) requesting bulk/ResourceSync access; (c) manual-review queue. **No challenge-solving/stealth-UA/IP-rotation** — documented as abusive (Cloudflare/Perplexity incident [^11^]) and incompatible with the AI Act Code-of-Practice posture. [HIGH]
- **Integrity**: stream to temp; compute **SHA-256**; store content-addressed `sha256/ab/cd/<hash>.pdf`; store size + hash in registry; ResourceSync fixity cross-check when available.
- **Malware scanning**: **ClamAV `clamd`** sidecar (TCP 3310, streaming, freshclam auto-updates) in a quarantine→scan→promote flow [^24^]. Caveat: ClamAV's own PDF parser has had heap-overflow/OOB-read CVEs (CVE-2025-20260, CVE-2024-20505) — run clamd **sandboxed with resource limits and auto-restart**, keep updated; optionally add PDFiD-style static checks for JS/embedded-launch actions. [HIGH]
- Validation: magic-byte check (`%PDF-`), size sanity, GROBID parse smoke-test downstream (fail-fast per CHARS).

---

## 5. Dedupe pipeline

1. **Identifier crosswalk (exact)**: DOI (case-insensitive), Handle, URN:NBN, OAI-ID, OpenAlex/DataCite/Crossref IDs, SHA-256 of PDF. DOI retained as canonical on conflict [^25^]. (Wide03/wide04 crosswalk applied at ingest.)
2. **Blocking**: (author surname + year), (first-4-title-tokens), (grantor + year). Embeddings optional second pass.
3. **Fuzzy scoring**: RapidFuzz `token_sort_ratio` on normalized titles. Literature practice clusters at **0.85–0.88**: 85% title threshold w/ rapidfuzz in ProQuest↔Scholar dedupe [^25^]; 0.88 title+year(±1) with <2% FP on manual audit [^26^]; 0.85 Levenshtein for name normalization [^27^]. Calyx defaults: **auto-merge ≥0.95 (title) + author-surname match + year ±1; review band 0.85–0.95; non-match <0.85**. Keep both records linked via `relatedIdentifier: IsIdenticalTo` on review-merge. Rule-based academic tools (ASySD/SRA-DM) validate this configurability [^28^]. [MED — thresholds empirical, tune on a gold set]
4. Never delete merged records — tombstone-as-duplicate with PROV link.

---

## 6. Provenance & audit

- **W3C PROV-O** (2013 Recommendation) model per document [^29^]: `prov:Entity` (harvested record v_n, file hash), `prov:Activity` (harvest run, rights decision, download, dedupe merge), `prov:Agent` (Calyx pipeline version, endpoint admin). Fields: source endpoint URL, OAI-ID, harvest timestamp, metadataPrefix, license observed + where (metadata/page/PDF), transformation chain (raw XML → Calyx-JSON → registry record), software version.
- **Nanopublication compatibility**: emit per-document "registration nanopub" — assertion graph (bibliographic claims), provenance graph (source/harvest), pubinfo graph (Calyx agent, timestamp, license of the record itself, CC0) [^30^]; Trusty-URI optional. Registry stores raw XML + PROV JSON-LD per record version; InvenioRDM v13 audit logs complement at the platform level [^5^].
- Retention: raw harvest responses WORM-stored ≥ license-dispute horizon; every rights decision reproducible from logs.

---

## 7. Monitoring & metrics

- **Harvest coverage**: endpoints registered vs harvested vs failing; records/endpoint; freshness lag distribution (CHARS schedules on exactly this [^8^]); resumptionToken-failure rate; 503/Retry-After incidence.
- **License mix**: % CC-by-family / OA-no-license / embargoed / unknown / conflicting, per endpoint and global — drives the review-queue workload.
- **Download**: per-host success/403/429/Cloudflare rates; ClamAV detections; dedupe auto-merge vs review volume (review-band = capacity proxy).
- **Error budget**: e.g., ≤0.5% records lost per run; failed harvest auto-resume success ≥99%; alert on endpoint error-rate >20% or robots-status change. Metrics via Prometheus; dashboards Grafana. [LOW-MED — operational targets, not sourced facts]

### Throughput estimates [LOW]
Metadata: OAI-PMH pages ~100 records @ 1–2 s politeness → **~180k–360k records/host/day serial**; with ~500 concurrent hosts (one worker each), full first pass over ~5–10M ETD records ≈ days-to-2-weeks. Full text: 2 s/host cadence × ~64 workers → ~1.5–2.7M PDF fetch *attempts*/day theoretical; realistically **300k–800k/day** after retries/failures. CORE-scale confirmation: CHARS sustains 70M+ record aggregation with this exact worker/queue shape [^8^].

### Top risks
1. **License ambiguity at scale** (most ETDs have no machine-readable license) → large review queue; mitigate with repo-default policies + aggregator licenses.
2. **Endpoint fragility** (broken OAI installs, token expiry 60 s defaults, day-granularity races) → checkpointing + 2-day overlap + full-diff fallback.
3. **Anti-bot escalation** (Cloudflare default blocks spreading in 2026 [^11^]) → aggregator-first full-text strategy.
4. **Legal drift** (Art. 4 reservations, aipref standardization, AI Act enforcement) → reservation scanner is config, not code.
5. **ClamAV/parser CVE surface** → sandbox + auto-update + PDFiD second layer.

---

### References
[^1^]: https://github.com/afuetterer/oaipmh-scythe — features: 6 verbs, httpx/lxml, ignore_deleted, Py≥3.10, active fork of Sickle
[^2^]: http://oai.dlib.vt.edu/OAI/2.0/openarchivesprotocol.htm — OAI-PMH 2.0 spec: §2.7.1 from/until inclusive; §4.2 Identify (granularity, deletedRecord, earliestDatestamp)
[^3^]: https://casrai.org/dictionary/term/resourcesync + https://ar5iv.labs.arxiv.org/html/1605.06154 — ResourceSync Z39.99: resource/change lists, dumps, capability list, notifications
[^4^]: https://github.com/resync/resync/blob/main/CHANGES.md — resync v2.0.1; Z39.99-2017 default; sha-256/md5 fixity; --delay, --tries, access tokens
[^5^]: https://inveniosoftware.org/blog/2025-07-22-invenio-rdm-13/ — v13: Thesis fields, copyright field, audit logs, compare revisions, Jobs, sitemaps
[^6^]: https://inveniordm.docs.cern.ch/operate/customize/metadata/optional_fields/ + https://github.com/zenodo/zenodo-rdm/issues/1169 — RDM_NAMESPACES/CUSTOM_FIELDS/UI; thesis contrib; custom-fields init; migration recipe
[^7^]: https://github.com/DSpace/RestContract + bitstreams.md — DSpace 7–10 REST: HAL, JWT, CSRF, JSON-Patch, bitstream checksum/content endpoints
[^8^]: https://oro.open.ac.uk/51070/1/ingestion-pipelines-microservices-cancellieri-pontika-pearce-anastasiou-knoth-3-MTSR2017.pdf — CORE CHARS: RabbitMQ+scheduler+workers, priorities, fail-fast, auto-resume, freshness-window scheduling; D-NET/OpenAIRE & SHARE comparisons
[^9^]: https://core.ac.uk/download/pdf/30274969.pdf — CORE harvesting levels, full-text link discovery, OpenDOAR sync, scheduling/monitoring UI
[^10^]: https://www.rfc-editor.org/rfc/rfc9309 — robots.txt standard; 4xx→allowed, 5xx→disallow-all; not access control; 24h caching
[^11^]: https://aisearchglossary.com/terms/robots-txt + https://apollodigital.io/blog/ai-crawler-access/ — RFC 9309 status 2026; Cloudflare stealth-crawler findings; Cloudflare default AI-crawler blocking (Sept 2026)
[^12^]: https://inveniordm.docs.cern.ch/reference/oai_pmh/ — OAI sets, deleted-record policy "no" (diff ListIdentifiers), OpenAIRE default sets, OAISERVER_ID_PREFIX
[^13^]: https://dli.grainger.uiuc.edu/Publications/TWCole/JCDL-OAI/ — harvester etiquette: User-Agent/From, 2-day overlap, token re-issue recovery, 503 handling
[^14^]: https://www.cs.odu.edu/~mln/jcdl02/oai-2.0-adv-final.pdf — resumptionToken semantics, 503/403 escalation ladder, completeListSize caveat
[^15^]: https://arup-cas.github.io/aiscr-api-home/oai-pmh/ — live example: rightsManifest in Identify description; deleted-record datestamp semantics
[^16^]: https://casrai.org/guides/how-to-describe-reuse-rights-and-permissions-for-a-shared-dataset — DataCite rightsList fields; DCMI dc:rights vs dc:license vs dc:accessRights
[^17^]: https://ndltd.org/wp-content/uploads/2021/04/etd-ms-v1.1.html — ETD-MS 1.1 schema, thesis.degree.*, MARC crosswalk (dc.rights→540)
[^18^]: https://journals.ala.org/lrts/article/view/5963/7586 — ETD metadata standards evolution; EThOS embargo-end-date practice
[^19^]: https://www.w3.org/Submission/2008/SUBM-ccREL-20080501/ — ccREL: RDFa default for web, XMP for standalone media; rel="license"
[^20^]: https://www.sacstudio.be/en/blog/ai-voice-ethics/ai-cloned-voices-belgian-european-law-ai-act-gdpr — TDMRep finalized May 2024; tdmrep.json / meta / header surfaces
[^21^]: https://blckalpaca.at/en/knowledge-base/seo-geo/technical-seo/robotstxt-and-ai-eu-legal-situation-and-tdm-opt-out — OLG Hamburg Kneschke v. LAION 2025-12-10 (machine-readable requirement); AI Act Art. 53(1)(c) + CoP RFC 9309 compliance
[^22^]: https://www.kim.uni-konstanz.de/en/services/research-and-teaching/text-and-data-mining/ — arXiv rule: 1 req/3 s, single connection; HTRC terms
[^23^]: https://jawalsh.github.io/assets/pdf/walsh2023.pdf + https://researchguides.library.wisc.edu/c.php?g=1366965&p=10100202 — HTRC Extracted Features (17.1M vols, unrestricted JSON-LD/TORCHLITE), Data Capsules, non-consumptive policy
[^24^]: https://www.c-sharpcorner.com/article/scanning-uploaded-files-for-malware-in-net-applications/ + https://www.sentinelone.com/vulnerability-database/cve-2025-20260/ — clamd sidecar quarantine→scan pattern; ClamAV PDF-parser CVEs
[^25^]: https://arxiv.org/html/2603.00399v1 — rapidfuzz token_sort_ratio 85% threshold for cross-DB dedupe
[^26^]: https://www.mdpi.com/2413-8851/9/12/508 — two-stage dedupe: DOI/URL exact, then fuzzy title-year 0.88, <2% FP audited
[^27^]: https://www.frontiersin.org/articles/10.3389/frhs.2025.1501035 — 0.85 Levenshtein threshold for name normalization
[^28^]: https://blog.hubmeta.com/methodology/attack-of-the-clones-the-duplicate-study-problem-in-meta-analysis — dedupe tool comparison (ASySD/SRA-DM configurable thresholds)
[^29^]: https://semantic-web-journal.net/system/files/swj1606.pdf — PROV-O W3C Recommendation 2013 (Entity/Activity/Agent)
[^30^]: https://link.springer.com/article/10.1007/s00799-025-00431-x + https://peerj.com/articles/cs-78/ — nanopublication model: assertion/provenance/pubinfo/head graphs; Trusty URIs
