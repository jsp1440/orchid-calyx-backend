from __future__ import annotations

import re

from .models import DesignDomain, DesignKnowledgeType


DOMAIN_TERMS: dict[DesignDomain, tuple[str, ...]] = {
    DesignDomain.USER_EXPERIENCE: ("user experience", "usability", "user research", "ux"),
    DesignDomain.USER_INTERFACE: ("user interface", "interface", "ui"),
    DesignDomain.GRAPHIC_DESIGN: ("graphic design", "layout", "typography"),
    DesignDomain.INFORMATION_ARCHITECTURE: ("information architecture", "navigation", "taxonomy"),
    DesignDomain.INTERACTION_DESIGN: ("interaction design", "affordance", "feedback"),
    DesignDomain.DASHBOARD_DESIGN: ("dashboard", "status display", "key performance indicator"),
    DesignDomain.ACCESSIBILITY: ("accessibility", "wcag", "screen reader", "contrast", "keyboard"),
    DesignDomain.MOTION_AND_ANIMATION: ("motion design", "animation", "transition", "reduced motion"),
    DesignDomain.EDUCATIONAL_DESIGN: ("instructional design", "educational design", "lesson"),
    DesignDomain.LEARNING_SCIENCES: ("mayer", "multimedia learning", "cognitive load", "learning science"),
    DesignDomain.SCIENTIFIC_VISUALIZATION: ("scientific visualization", "data visualization", "uncertainty visualization"),
    DesignDomain.BRANDING_AND_VISUAL_IDENTITY: ("branding", "visual identity", "brand system"),
    DesignDomain.DESIGN_SYSTEMS: ("design system", "design token", "style guide"),
    DesignDomain.COMPONENT_LIBRARIES: ("component library", "component api", "storybook"),
}

TYPE_TERMS: dict[DesignKnowledgeType, tuple[str, ...]] = {
    DesignKnowledgeType.DESIGN_PRINCIPLE: ("principle",),
    DesignKnowledgeType.PATTERN: ("pattern",),
    DesignKnowledgeType.ANTI_PATTERN: ("anti-pattern", "antipattern", "avoid"),
    DesignKnowledgeType.GUIDELINE: ("guideline", "recommendation", "should"),
    DesignKnowledgeType.STANDARD: ("standard", "conformance"),
    DesignKnowledgeType.BEST_PRACTICE: ("best practice",),
    DesignKnowledgeType.EDUCATIONAL_THEORY: ("theory", "multimedia learning", "cognitive load"),
    DesignKnowledgeType.ACCESSIBILITY_REQUIREMENT: ("wcag", "accessibility requirement", "success criterion"),
    DesignKnowledgeType.VISUALIZATION_TECHNIQUE: ("visualization", "chart", "encoding"),
    DesignKnowledgeType.INTERACTION_PATTERN: ("interaction pattern", "affordance", "interaction"),
}


def classify(
    text: str,
    requested_domains: tuple[DesignDomain, ...] = (),
    requested_types: tuple[DesignKnowledgeType, ...] = (),
) -> tuple[tuple[DesignDomain, ...], tuple[DesignKnowledgeType, ...], float, tuple[str, ...]]:
    normalized = text.casefold()

    def contains(term: str) -> bool:
        if len(term) <= 3:
            return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", normalized) is not None
        return term in normalized

    domain_hits = {
        domain: tuple(term for term in terms if contains(term))
        for domain, terms in DOMAIN_TERMS.items()
    }
    type_hits = {
        knowledge_type: tuple(term for term in terms if contains(term))
        for knowledge_type, terms in TYPE_TERMS.items()
    }
    domains = set(requested_domains) | {key for key, hits in domain_hits.items() if hits}
    types = set(requested_types) | {key for key, hits in type_hits.items() if hits}
    if not domains or not types:
        raise ValueError("DESIGN_CLASSIFICATION_INSUFFICIENT_EVIDENCE")
    evidence = tuple(
        sorted(
            {
                term
                for hits in (*domain_hits.values(), *type_hits.values())
                for term in hits
            }
        )
    )
    confidence = min(0.99, 0.65 + min(0.25, len(evidence) * 0.04))
    if requested_domains or requested_types:
        confidence = min(confidence, 0.85)
    return (
        tuple(sorted(domains, key=str)),
        tuple(sorted(types, key=str)),
        round(confidence, 3),
        evidence,
    )
