# FIRECRAWL-FEDERATION-001 — Federation Mapper

Status: draft implementation on issue #1682

## Purpose

Use Firecrawl as a bounded **source reconnaissance** layer for Orchid Continuum federation.

This component answers: how is an external botanical source organized, what identifiers and data classes does it expose, what provenance and licensing clues are present, and is there a sanctioned API/download/Darwin Core route that should be preferred over scraping?

It is not a scientific authority, a replacement taxonomy, or a default bulk harvester.

## Placement

- **Brain**: canonical architecture, federation rules, source interpretation, decisions.
- **Calyx backend**: executable mapping, normalization, source profiles, later connector hand-off.
- **Harvester V2 / canonical importers**: bulk data acquisition once a preferred sanctioned route is known.

World Plants remains the canonical OC taxonomy. POWO, WFO, IPNI, GBIF and other sources attach as external authority/evidence mappings.

## Safety defaults

1. Map before crawl.
2. Default maximum: 100 discovered URLs.
3. Do not follow subdomains unless explicitly enabled.
4. Never send credentials to the target site.
5. Read the Firecrawl credential only from `FIRECRAWL_API_KEY`.
6. Prefer official API, downloadable snapshot, Darwin Core Archive, OAI-PMH, or documented bulk endpoint over page scraping.
7. Respect robots.txt, target-site terms, access controls and rate limits.
8. No automatic Knowledge Graph publication.
9. No sensitive-locality publication.
10. Tests mock the network and spend zero Firecrawl credits.

Firecrawl documentation states that Map is intended for discovering site URLs before paying to scrape them, and that Firecrawl respects robots.txt. The OC integration additionally requires target-source terms/licence review.

## Initial pilot

Targets:
- https://powo.science.kew.org/
- https://www.worldfloraonline.org/

Pilot taxon:
- *Phragmipedium*

Run in map-only mode first. Inspect representative taxon, identifier, download/API, licence/terms and provider pages. Do not initiate a full-domain crawl as part of the pilot.

## Output

The mapper emits a source profile containing:
- source identifier
- root URL
- retrieval timestamp
- mapped URLs
- inferred URL classes
- candidate stable identifiers
- candidate API/download endpoints
- terms/licence URLs
- preferred ingestion recommendation
- raw discovery metadata needed for provenance

The profile is reconnaissance evidence. It must be reviewed before it is promoted into a durable production connector configuration.

## Pilot command

The pilot runs only through the acquisition ledger
(`app/federation/federation_pilot.py`, `SharedFirecrawlFederationService`).
It needs the application database (`PGHOST` or `DATABASE_URL`) with
`migrations/20260930_acquisition_ledger.sql` applied, and a live call also needs
`NO_API_MODE=false`, `FIRECRAWL_KILL_SWITCH` unset or `false`, and
`FIRECRAWL_API_KEY`:

```bash
python scripts/oc_firecrawl_federation_pilot.py --source all --limit 50 --output /tmp/oc-federation-phragmipedium.json
```

Per source, before any paid call: a completed ledger record for the same
request is reused; the provider gate is checked; the existing corpus and source
registry inventory (`audit_existing_corpus`, matched with `held_source_match` on
DOI/URL/content hash/bibliography) are searched, and an unverifiable audit
blocks the source. The mapper runs only on an acquired ledger lease, so repeat
and concurrent runs pay once per resource. A missing or incompatible ledger
schema aborts with zero provider calls; there is no direct-call fallback or
bypass flag. Exit status: 0 all sources answered, 2 aborted, 3 blocked/in
flight/failed.

The pilot intentionally requests at most 50 URLs per source by default and uses
`Phragmipedium` as the discovery search term. Review the resulting JSON before
building or changing any production connector.

Do **not** use the pilot output as scientific publication evidence by itself.
