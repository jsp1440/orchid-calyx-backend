from pathlib import Path


MIGRATION = Path("migrations/102b_concept_lexical_definition_services.sql")


def main() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    required = [
        "CREATE TABLE IF NOT EXISTS oc_concepts.concept_labels",
        "CREATE TABLE IF NOT EXISTS oc_concepts.concept_definitions",
        "uq_concept_preferred_label_context",
        "uq_concept_definition_variant",
        "REVOKE ALL ON oc_concepts.concept_labels FROM PUBLIC",
        "REVOKE ALL ON oc_concepts.concept_definitions FROM PUBLIC",
    ]
    forbidden = [
        "DROP TABLE",
        "TRUNCATE",
        "DELETE FROM",
        "ALTER TABLE oc_ontology",
    ]
    missing = [token for token in required if token not in sql]
    destructive = [token for token in forbidden if token in sql.upper()]
    if missing:
        raise SystemExit(f"Missing required migration clauses: {missing}")
    if destructive:
        raise SystemExit(f"Destructive migration clauses detected: {destructive}")
    print("BUILD-SEM-002B migration validation passed")


if __name__ == "__main__":
    main()
