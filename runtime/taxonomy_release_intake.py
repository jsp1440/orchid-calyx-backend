"""Compatibility surface for the hardened CALYX taxonomy release intake."""

from runtime.taxonomy_release_intake_v2 import (
    HASSLER_RANKS,
    HASSLER_SPECIES_CODES,
    HASSLER_SPECIES_NAME_RE,
    INTAKE_SCHEMA_VERSION,
    RELEASE_ID_RE,
    SYNONYM_MARKER_RE,
    ReleaseIdentity,
    TaxonomyReleaseIntakeService,
)

__all__ = [
    "HASSLER_RANKS",
    "HASSLER_SPECIES_CODES",
    "HASSLER_SPECIES_NAME_RE",
    "INTAKE_SCHEMA_VERSION",
    "RELEASE_ID_RE",
    "SYNONYM_MARKER_RE",
    "ReleaseIdentity",
    "TaxonomyReleaseIntakeService",
]
