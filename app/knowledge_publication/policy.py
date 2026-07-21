from __future__ import annotations

from typing import Any

from .models import PublicationPathway, PublicationState


class PublicationAuthority:
    """Deterministic fail-closed evaluation of trusted registry records."""

    def evaluate(
        self, candidate: dict[str, Any], policy: dict[str, Any]
    ) -> dict[str, Any]:
        rules, assertion, routing = (
            policy["rules"],
            candidate["assertion"],
            candidate["eligibility_decision"],
        )
        scope, statement = (
            assertion.get("scientific_scope", {}),
            assertion.get("normalized_statement", {}),
        )
        assertion_type, domain = (
            statement.get("assertion_type"),
            scope.get("scientific_domain"),
        )
        sources = candidate.get("provenance_roots", [])
        copyrights = {source.get("copyright_policy") for source in sources}
        checks = {
            "exact_assertion_version": assertion.get("version")
            == candidate["assertion_version"],
            "assertion_unpublished": assertion.get("published") is False,
            "assertion_publication_eligible": assertion.get("publication_eligible")
            is True,
            "eligibility_linked": assertion.get("routing_decision_id")
            == candidate["eligibility_decision_id"],
            "eligibility_automatic": routing.get("path") == "AUTOMATIC_PROMOTION",
            "eligibility_hard_gates": not routing.get("hard_failures"),
            "assertion_type_supported": assertion_type
            in rules["supported_assertion_types"],
            "domain_supported": domain in rules["supported_domains"],
            "assertion_type_not_prohibited": assertion_type
            not in rules["prohibited_assertion_types"],
            "domain_not_prohibited": domain not in rules["prohibited_domains"],
            "provenance_complete": (not rules["require_complete_provenance"])
            or bool(sources),
            "copyright_permitted": bool(sources)
            and copyrights.issubset(set(rules["permitted_copyright_policies"])),
            "taxonomy_unambiguous": (not rules["require_unambiguous_taxonomy"])
            or scope.get("taxonomy_unambiguous") is True,
            "conflicts_resolved": (not rules["reject_unresolved_conflicts"])
            or not assertion.get("conflicting_interpretation_ids"),
            "independence_threshold": len(
                {item.get("source_revision_id") for item in sources}
            )
            >= rules["minimum_independent_sources"],
        }
        failures = sorted(name for name, passed in checks.items() if not passed)
        reviews: list[str] = []
        requested = candidate["requested_pathway"]
        if (
            scope.get("impact_class", "STANDARD")
            in rules["mandatory_review_impact_classes"]
        ):
            reviews.append("MANDATORY_IMPACT_REVIEW")
        if requested in {
            PublicationPathway.HUMAN.value,
            PublicationPathway.PROVISIONAL.value,
        }:
            reviews.append("HUMAN_AUTHORIZATION_REQUIRED")
        if (
            requested == PublicationPathway.PROVISIONAL.value
            and not rules["provisional_enabled"]
        ):
            failures.append("PROVISIONAL_PUBLICATION_DISABLED")
        if requested == PublicationPathway.AUTOMATIC.value:
            if assertion_type not in rules["automatic_assertion_types"]:
                reviews.append("ASSERTION_TYPE_REQUIRES_REVIEW")
            if domain not in rules["automatic_domains"]:
                reviews.append("DOMAIN_REQUIRES_REVIEW")
        authorized = not failures and not reviews
        resolved = requested if authorized else "NO_PUBLICATION"
        reason_codes = sorted(set(failures + reviews)) or [
            "ALL_AUTHORIZATION_RULES_PASSED"
        ]
        return {
            "state": PublicationState.AUTHORIZED.value
            if authorized
            else PublicationState.REJECTED.value,
            "outcome": "AUTHORIZED"
            if authorized
            else ("REVIEW_REQUIRED" if reviews and not failures else "REJECTED"),
            "checks": checks,
            "evaluated_rules": sorted(checks),
            "failure_reasons": sorted(set(failures)),
            "review_reasons": sorted(set(reviews)),
            "reason_codes": reason_codes,
            "rationale": "; ".join(reason_codes),
            "required_reviewer_classes": sorted(set(reviews)),
            "unresolved_blockers": sorted(set(failures + reviews)),
            "resolved_pathway": resolved,
            "validation_results": {
                "provenance": checks["provenance_complete"],
                "taxonomy": checks["taxonomy_unambiguous"],
                "copyright": checks["copyright_permitted"],
                "contradiction": checks["conflicts_resolved"],
                "evidence_independence": checks["independence_threshold"],
            },
            "confidence_decomposition_reference": routing.get("factors"),
            "policy_id": policy["policy_id"],
            "policy_version": policy["version"],
        }
