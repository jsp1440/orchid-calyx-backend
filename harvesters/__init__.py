"""Mature production harvesters vendored for BUILD-093.

Only the iNaturalist, GBIF, and EOL/TraitBank harvesters (and the shared
helpers they import: base, state_helper) are vendored here. This package
intentionally does NOT import its submodules at package load time --
harvesters.gbif_api raises at import when DATABASE_URL is unset, so callers
(harvesters.execution) import each harvester lazily at dispatch time.
"""
