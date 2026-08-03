from runtime.knowledge_graph.dynamic_source_projection import ProjectionPlan
from runtime.knowledge_graph.unresolved_taxon_queue import (
    queue_from_projection_plans,
    queue_from_rows,
    unresolved_queue_report,
)


def test_projection_blockers_become_review_queue_items():
    plans = [
        ProjectionPlan(
            domain="habitat",
            source="oc_habitat.habitats",
            state="blocked",
            sql=None,
            source_pk_column="id",
            taxon_pk_column=None,
            limitation="No canonical taxon identifier was discovered.",
        ),
        ProjectionPlan(
            domain="molecular",
            source=None,
            state="unavailable",
            sql=None,
            source_pk_column=None,
            taxon_pk_column=None,
            limitation="No live source relation was discovered.",
        ),
        ProjectionPlan(
            domain="media",
            source="public.orchid_images",
            state="ready",
            sql="SELECT 1",
            source_pk_column="id",
            taxon_pk_column="taxonomy_id",
        ),
    ]

    report = unresolved_queue_report(queue_from_projection_plans(plans))
    assert report["count"] == 2
    assert report["by_domain"] == {"habitat": 1, "molecular": 1}
    assert report["publication_blocked"] is True
    assert {item["review_state"] for item in report["items"]} == {
        "needs_taxon_resolution",
        "source_unavailable",
    }


def test_unresolved_rows_preserve_operator_evidence():
    items = queue_from_rows(
        "literature",
        "oc_graph.taxon_literature_edges",
        [
            {
                "source_pk": 41,
                "scientific_name": "Unresolved orchid",
                "taxon_value": "legacy:77",
                "reason": "No exact canonical match",
            }
        ],
    )
    report = unresolved_queue_report(items)
    item = report["items"][0]
    assert item["source_pk"] == "41"
    assert item["supplied_scientific_name"] == "Unresolved orchid"
    assert item["supplied_taxon_value"] == "legacy:77"
    assert item["reason"] == "No exact canonical match"
