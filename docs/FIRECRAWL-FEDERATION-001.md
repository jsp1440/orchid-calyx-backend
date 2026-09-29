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

Once `FIRECRAWL_API_KEY` is present in the runtime environment, run:

```bash
python scripts/oc_firecrawl_federation_pilot.py --source all --limit 50 --output /tmp/oc-federation-phragmipedium.json
```

The pilot intentionally requests at most 50 URLs per source by default and uses
`Phragmipedium` as the discovery search term. Review the resulting JSON before
building or changing any production connector.

Do **not** use the pilot output as scientific publication evidence by itself.
