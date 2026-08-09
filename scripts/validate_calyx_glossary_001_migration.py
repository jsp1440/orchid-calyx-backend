from pathlib import Path


MIGRATION = Path("migrations/20260808_glossary_scientific_language.sql")


def main() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    upper = sql.upper()

    required = (
        "CREATE TABLE IF NOT EXISTS OC_CONCEPTS.GLOSSARY_CANDIDATES",
        "CREATE TABLE IF NOT EXISTS OC_CONCEPTS.GLOSSARY_FIGURE_REQUESTS",
        "REFERENCES OC_CONCEPTS.CONCEPTS(CONCEPT_ID)",
        "AUTOMATIC",  # absence checked below; marker documents intent in validator
    )
    for statement in required[:3]:
        if statement not in upper:
            raise SystemExit(f"missing required migration contract: {statement}")

    forbidden = (
        "DROP TABLE",
        "DROP SCHEMA",
        "TRUNCATE ",
        "DELETE FROM OC_CONCEPTS.CONCEPTS",
        "ALTER TABLE OC_CONCEPTS.CONCEPTS",
        "ALTER TABLE OC_CONCEPTS.CONCEPT_LABELS",
        "ALTER TABLE OC_CONCEPTS.CONCEPT_DEFINITIONS",
    )
    for statement in forbidden:
        if statement in upper:
            raise SystemExit(f"destructive or canonical mutation forbidden: {statement}")

    if "SCIENTIFIC_EVIDENCE BOOLEAN NOT NULL DEFAULT FALSE" not in upper:
        raise SystemExit("figure requests must remain explicitly non-evidence")
    if "REVIEW_REQUIRED BOOLEAN NOT NULL DEFAULT TRUE" not in upper:
        raise SystemExit("figure requests must remain review gated")
    if "MATCHED_PENDING_REVIEW" not in upper or "AMBIGUOUS" not in upper:
        raise SystemExit("candidate review/ambiguity states are required")


if __name__ == "__main__":
    main()
