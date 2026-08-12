# CALYX-TIG-008 — Canonical Taxon Target Resolution

## Purpose

TIG-006 required operators to provide `CANONICAL_TAXON_ID=Scientific name` manually before literature harvesting. TIG-008 removes that avoidable manual step while preserving strict taxonomic identity.

The resolver reads the operational canonical taxonomy surface already used by the species exhibit: `public.orchid_taxonomy`. Its `id` is retained as the TIG `canonical_taxon_id`; the normalized scientific name is retained as the harvest search name.

## Resolution policy

Resolution is exact after the existing Orchid Continuum scientific-name normalizer is applied. The resolver:

1. requires a supported binomial or infraspecific scientific name;
2. limits the database lookup to the requested genus;
3. normalizes each returned canonical scientific name;
4. resolves only when exactly one canonical row has the same normalized name;
5. returns `unresolved` for no match;
6. returns `ambiguous` for multiple matching canonical rows and requires human selection;
7. never performs fuzzy matching or silently substitutes a synonym.

Authorship differences therefore do not prevent an accepted binomial from resolving, while genuinely ambiguous duplicate rows fail closed.

## Operator workflow

Resolve only, with no Europe PMC request and no database write:

```bash
python scripts/calyx_tig_europepmc_harvest.py \
  --name 'Dendrobium cuthbertsonii' \
  --resolve-only
```

Run a bounded literature dry run using the resolved canonical taxon ID:

```bash
python scripts/calyx_tig_europepmc_harvest.py \
  --name 'Dendrobium cuthbertsonii' \
  --page-size 10 \
  --dry-run
```

Explicit `--target 'ID=Scientific name'` remains available for reviewed exceptional cases. `--name` and `--target` may be repeated; exact duplicate targets are deduplicated before harvesting.

## Governance

Taxon resolution does not activate or modify taxonomy. It reads `public.orchid_taxonomy` only. It does not use staged Hassler releases, perform fuzzy matching, resolve ambiguous duplicates automatically, or alter the scientific review boundary introduced by TIG-005. Literature harvest results remain review-only candidates until explicit human acceptance.

## Validation

Focused tests cover authorship-insensitive exact resolution, preservation of infraspecific identity, duplicate-row ambiguity, invalid-name rejection without a database call, and fail-closed `resolve_or_raise` behavior.
