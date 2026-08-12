"""Controlled Knowledge Graph vocabulary for scientific-method evidence structure.

The Orchid Continuum literature pipeline already extracts sections, entities,
measurements, claims, evidence spans, figures, tables, references and explicit
relationships.  This module gives those objects canonical graph semantics so
papers can be represented as more than a single ``publication`` node.

This is vocabulary only.  It does not publish extracted claims or mutate the
Knowledge Graph; publication remains provenance- and review-governed.
"""

from __future__ import annotations

from typing import Final

SCIENTIFIC_METHOD_NODE_TYPE_DOMAIN: Final[dict[str, str]] = {
    "observation": "scientific_method",
    "measurement": "scientific_method",
    "method": "scientific_method",
    "protocol": "scientific_method",
    "experiment": "scientific_method",
    "dataset": "scientific_method",
    "result": "scientific_method",
    "conclusion": "scientific_method",
    "limitation": "scientific_method",
    "recommendation": "scientific_method",
    "citation": "literature",
    "reference": "literature",
    "paper_section": "literature",
    "figure_evidence": "literature",
    "table_evidence": "literature",
}

SCIENTIFIC_METHOD_EDGE_TYPE_DOMAIN: Final[dict[str, str]] = {
    "has_observation": "scientific_method",
    "has_measurement": "scientific_method",
    "uses_method": "scientific_method",
    "uses_protocol": "scientific_method",
    "describes_experiment": "scientific_method",
    "has_dataset": "scientific_method",
    "reports_result": "scientific_method",
    "states_conclusion": "scientific_method",
    "states_limitation": "scientific_method",
    "makes_recommendation": "scientific_method",
    "tests_hypothesis": "scientific_method",
    "about_taxon": "scientific_method",
    "measurement_of": "scientific_method",
    "measured_at": "scientific_method",
    "derived_from_measurement": "scientific_method",
    "result_of": "scientific_method",
    "conclusion_from": "scientific_method",
    "supports_hypothesis": "scientific_method",
    "rejects_hypothesis": "scientific_method",
    "cites": "literature",
    "cited_by": "literature",
    "has_section": "literature",
    "has_figure_evidence": "literature",
    "has_table_evidence": "literature",
    "extracted_from": "evidence",
    "has_source_span": "evidence",
}

# Canonical mapping from literature-extraction Claim.claim_type to graph nodes.
CLAIM_TYPE_TO_NODE_TYPE: Final[dict[str, str]] = {
    "observation": "observation",
    "result": "result",
    "interpretation": "assertion",
    "hypothesis": "hypothesis",
    "methodological": "method",
    "background": "assertion",
    "limitation": "limitation",
    "recommendation": "recommendation",
}

# Canonical section semantics from literature_extraction.models.Section.
SECTION_TYPE_TO_PRIMARY_NODE_TYPE: Final[dict[str, str]] = {
    "methods": "method",
    "results": "result",
    "conclusion": "conclusion",
    "references": "reference",
}
