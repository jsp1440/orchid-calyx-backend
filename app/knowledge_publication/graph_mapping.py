from __future__ import annotations

import hashlib
import json
from typing import Any

from .graph_models import GraphOperation, GraphOperationType


SUPPORTED_PREDICATES = {
    "HAS_TRAIT",
    "OCCURS_IN",
    "HAS_MEASUREMENT",
    "ASSOCIATED_WITH",
    "CITES",
}
MATERIAL_SCOPE = {
    "qualifiers",
    "geography",
    "temporal_scope",
    "population",
    "life_stage",
    "environmental_conditions",
    "experimental_conditions",
    "methods",
    "uncertainty",
    "negation",
    "comparison",
    "units",
}


def stable_id(prefix: str, value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}:{hashlib.sha256(encoded.encode()).hexdigest()}"


class AssertionGraphMapper:
    """Maps trusted canonical assertions without flattening material context."""

    def map(
        self, assertion: dict[str, Any], publication: dict[str, Any]
    ) -> tuple[GraphOperation, ...]:
        statement = assertion.get("normalized_statement", {})
        scope = assertion.get("scientific_scope", {})
        subject = statement.get("subject")
        predicate = str(statement.get("predicate", "")).upper()
        object_value = statement.get("object", statement.get("value"))
        if not subject or object_value is None:
            raise ValueError("MATERIAL_CONTEXT_MISSING")
        if predicate not in SUPPORTED_PREDICATES:
            raise ValueError("UNSUPPORTED_PREDICATE")
        if (
            scope.get("taxonomy_unambiguous") is not True
            or not scope.get("taxonomy_concept_id")
            or not scope.get("taxonomy_version")
        ):
            raise ValueError("TAXONOMY_RESOLUTION_REQUIRED")
        if statement.get("measurement") is not None and not statement.get("units"):
            raise ValueError("UNSAFE_UNIT_NORMALIZATION")
        context = {
            key: statement.get(key, scope.get(key))
            for key in sorted(MATERIAL_SCOPE)
            if statement.get(key, scope.get(key)) is not None
        }
        subject_key = stable_id(
            "scientific-subject",
            {
                "subject": subject,
                "taxonomy": scope["taxonomy_concept_id"],
                "taxonomy_version": scope["taxonomy_version"],
            },
        )
        object_key = stable_id(
            "scientific-object",
            {"object": object_value, "units": statement.get("units")},
        )
        assertion_key = stable_id(
            "qualified-assertion",
            {
                "assertion_id": publication["assertion_id"],
                "assertion_version": publication["assertion_version"],
                "predicate": predicate,
                "context": context,
            },
        )
        common = {
            "publication_id": publication["publication_id"],
            "publication_version": publication["publication_version"],
            "assertion_id": publication["assertion_id"],
            "assertion_version": publication["assertion_version"],
        }
        operations = [
            GraphOperation(
                0,
                GraphOperationType.CREATE_NODE,
                subject_key,
                {
                    **common,
                    "node_type": "scientific_subject",
                    "display_label": str(subject),
                    "scientific_scope": scope,
                },
            ),
            GraphOperation(
                1,
                GraphOperationType.CREATE_NODE,
                object_key,
                {
                    **common,
                    "node_type": "scientific_object",
                    "display_label": str(object_value),
                    "units": statement.get("units"),
                },
            ),
            GraphOperation(
                2,
                GraphOperationType.CREATE_NODE,
                assertion_key,
                {
                    **common,
                    "node_type": "qualified_assertion",
                    "display_label": predicate,
                    "predicate": predicate,
                    "context": context,
                    "negation": bool(context.get("negation", False)),
                },
            ),
            GraphOperation(
                3,
                GraphOperationType.CREATE_EDGE,
                stable_id("edge", [subject_key, "HAS_ASSERTION", assertion_key]),
                {
                    **common,
                    "edge_type": "HAS_ASSERTION",
                    "from_key": subject_key,
                    "to_key": assertion_key,
                },
            ),
            GraphOperation(
                4,
                GraphOperationType.CREATE_EDGE,
                stable_id("edge", [assertion_key, predicate, object_key]),
                {
                    **common,
                    "edge_type": predicate,
                    "from_key": assertion_key,
                    "to_key": object_key,
                    "context": context,
                },
            ),
        ]
        for offset, interpretation_id in enumerate(
            assertion.get("supporting_interpretation_ids", []), 5
        ):
            operations.append(
                GraphOperation(
                    offset,
                    GraphOperationType.ADD_ASSERTION_SUPPORT,
                    stable_id("support", [assertion_key, interpretation_id]),
                    {
                        **common,
                        "assertion_key": assertion_key,
                        "interpretation_id": interpretation_id,
                    },
                )
            )
        start = len(operations)
        for offset, interpretation_id in enumerate(
            assertion.get("conflicting_interpretation_ids", []), start
        ):
            operations.append(
                GraphOperation(
                    offset,
                    GraphOperationType.ADD_CONFLICTING_EVIDENCE,
                    stable_id("conflict", [assertion_key, interpretation_id]),
                    {
                        **common,
                        "assertion_key": assertion_key,
                        "interpretation_id": interpretation_id,
                    },
                )
            )
        return tuple(operations)
