from __future__ import annotations

CHAPTER = {
    "chapter_id": "BITB-CHAPTER-ORCHID-FLOWERING-001",
    "schema_version": "1.0.0",
    "title": "Why Orchids Flower—or Do Not",
    "status": "draft",
    "summary": (
        "An evidence-labeled introduction to orchid flowering that separates "
        "observation, plausible explanation, and unsupported causal certainty."
    ),
    "learning_objectives": [
        "Distinguish an observation from an interpretation.",
        "Form competing testable hypotheses for failure to bloom.",
        "Evaluate light, temperature, plant condition, and identity evidence.",
        "State uncertainty and identify the next evidence needed.",
    ],
    "sections": [
        {
            "section_id": "OBSERVATION-FIRST",
            "title": "Begin with what can actually be observed",
            "epistemic_status": "instructional",
            "body": (
                "A plant that has not flowered presents an outcome, not a diagnosis. "
                "Leaf color, growth size, root condition, flowering history, and label "
                "confidence are observations or records that must be evaluated before "
                "a causal explanation is accepted."
            ),
        },
        {
            "section_id": "COMPETING-HYPOTHESES",
            "title": "More than one explanation may fit",
            "epistemic_status": "supported",
            "body": (
                "Insufficient light, missing seasonal cues, plant immaturity, root loss, "
                "and incorrect identification can produce similar outcomes. A scientific "
                "investigation compares alternatives rather than choosing a favorite cause."
            ),
        },
        {
            "section_id": "IDENTITY-AS-CONFOUNDER",
            "title": "Identification determines which requirements apply",
            "epistemic_status": "provisional",
            "body": (
                "When a label is not independently verified, cultivation requirements tied "
                "to that name remain provisional. Missing flowers may also prevent confident "
                "identification, creating an important confounding variable."
            ),
        },
    ],
    "laboratory_links": [
        {
            "laboratory_id": "OCU-LAB-FAILURE-TO-BLOOM-001",
            "launch_label": "Investigate a failure-to-bloom case",
            "required_sections": ["OBSERVATION-FIRST", "COMPETING-HYPOTHESES"],
        }
    ],
    "publication_allowed": False,
}

LABORATORY = {
    "laboratory_id": "OCU-LAB-FAILURE-TO-BLOOM-001",
    "schema_version": "1.0.0",
    "title": "Why Did This Orchid Fail to Bloom?",
    "status": "draft",
    "summary": (
        "A curated scientific-method case using plant images, collection history, "
        "light, temperature, fertilizer, flowering evidence, and a label audit."
    ),
    "inquiry_sequence": [
        "observe",
        "question",
        "investigate",
        "analyze",
        "interpret",
        "communicate",
        "contribute",
    ],
    "evidence_catalog": [
        {
            "evidence_id": "E-PLANT-IMAGES",
            "label": "Current plant and root photographs",
            "epistemic_status": "observed",
            "summary": "Leaves are dark green; newest growth is full-sized; visible roots are firm.",
        },
        {
            "evidence_id": "E-COLLECTION-RECORD",
            "label": "Three-year collection history",
            "epistemic_status": "reported",
            "summary": "Adult division, repotted 16 months ago, label confidence unverified.",
        },
        {
            "evidence_id": "E-LIGHT-SERIES",
            "label": "Daily light integral summary",
            "epistemic_status": "observed",
            "summary": "Median DLI 3.4 mol m-2 day-1 across 42 measurement days.",
        },
        {
            "evidence_id": "E-TEMPERATURE-SERIES",
            "label": "Annual temperature summary",
            "epistemic_status": "observed",
            "summary": "Winter night median 18.7 C; average day-night difference 5.1 C.",
        },
        {
            "evidence_id": "E-LABEL-AUDIT",
            "label": "Identification and label audit",
            "epistemic_status": "interpreted",
            "summary": "The labeled species cannot be confirmed without flowers or provenance.",
        },
    ],
    "tutor_mode": "disabled_in_prototype",
    "publication_allowed": False,
    "automatic_candidate_knowledge": False,
    "human_review_required": True,
}
