"""Featured Genus v1 — versioned capability contracts for the Orchid Continuum.

This package composes the Featured Genus scientific profile and selection from
existing, proven Calyx evidence sources. It adds no scheduler, no new media
pipeline, and no second knowledge graph: it reads canonical taxonomy, approved
media, widget habitat evidence, and the scientific Knowledge Graph through the
same boundaries the existing endpoints already use.

Contracts:
    featured-genus-profile/v1   — composed genus scientific exhibit payload
    featured-genus-selection/v1 — reproducible 12h rotation + editorial override
"""

FEATURED_GENUS_PROFILE_CONTRACT = "featured-genus-profile/v1"
FEATURED_GENUS_SELECTION_CONTRACT = "featured-genus-selection/v1"
