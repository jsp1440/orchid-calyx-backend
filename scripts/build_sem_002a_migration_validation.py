from pathlib import Path

MIGRATION = Path("migrations/102a_core_concept_registry.sql")


def main() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    lowered = sql.lower()
    required = (
        "create schema if not exists oc_concepts",
        "create table if not exists oc_concepts.concept_schemes",
        "create table if not exists oc_concepts.concept_releases",
        "create table if not exists oc_concepts.concepts",
        "create table if not exists oc_concepts.ontology_term_concepts",
        "concept_identity_immutable",
        "concept_lifecycle_valid",
        "concept_release_scheme_valid",
        "https://id.orchidcontinuum.org/concept/",
    )
    missing = [token for token in required if token not in lowered]
    destructive = [
        token
        for token in ("drop table", "truncate", "delete from", "alter table oc_ontology")
        if token in lowered
    ]
    if missing or destructive:
        raise SystemExit(
            f"migration validation failed: missing={missing}, destructive={destructive}"
        )
    print("BUILD-SEM-002A migration validation passed: additive core registry only")


if __name__ == "__main__":
    main()
