import os
from pathlib import Path
from uuid import uuid4

import psycopg

MIGRATIONS = (
    Path("migrations/076a_universal_intake.sql"),
    Path("migrations/076b_semantic_extraction.sql"),
    Path("migrations/077_ontology_evidence_registry.sql"),
    Path("migrations/102a_core_concept_registry.sql"),
)


def main() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        raise SystemExit("TEST_DATABASE_URL is required")

    with psycopg.connect(database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            for migration in MIGRATIONS:
                cur.execute(migration.read_text(encoding="utf-8"))
            # The new migration must be safe to reapply.
            cur.execute(MIGRATIONS[-1].read_text(encoding="utf-8"))

            scheme_id = uuid4()
            release_id = uuid4()
            original_id = uuid4()
            replacement_id = uuid4()
            marker = uuid4().hex
            cur.execute(
                """
                INSERT INTO oc_concepts.concept_schemes
                  (scheme_id, scheme_key, name, authority, steward)
                VALUES (%s, %s, 'Validation', 'Orchid Continuum', 'validator')
                """,
                (scheme_id, f"build-sem-002a-{marker}"),
            )
            cur.execute(
                """
                INSERT INTO oc_concepts.concept_releases
                  (release_id, scheme_id, version, metadata)
                VALUES (%s, %s, 'validation-1', '{"issue":124}'::jsonb)
                """,
                (release_id, scheme_id),
            )
            for concept_id in (original_id, replacement_id):
                cur.execute(
                    """
                    INSERT INTO oc_concepts.concepts
                      (concept_id, concept_uri, scheme_id, release_id, steward)
                    VALUES (%s, %s, %s, %s, 'validator')
                    """,
                    (
                        concept_id,
                        f"https://id.orchidcontinuum.org/concept/{concept_id}",
                        scheme_id,
                        release_id,
                    ),
                )
                cur.execute(
                    """
                    UPDATE oc_concepts.concepts
                    SET status='ACTIVE', review_state='APPROVED'
                    WHERE concept_id=%s
                    """,
                    (concept_id,),
                )
            cur.execute(
                """
                UPDATE oc_concepts.concepts
                SET status='SUPERSEDED', superseded_by_id=%s
                WHERE concept_id=%s
                """,
                (replacement_id, original_id),
            )
            cur.execute(
                """
                SELECT status, superseded_by_id, concept_uri
                FROM oc_concepts.concepts WHERE concept_id=%s
                """,
                (original_id,),
            )
            status, superseded_by_id, uri = cur.fetchone()
            assert status == "SUPERSEDED"
            assert superseded_by_id == replacement_id
            assert uri == f"https://id.orchidcontinuum.org/concept/{original_id}"

            try:
                cur.execute(
                    "UPDATE oc_concepts.concepts SET concept_id=%s WHERE concept_id=%s",
                    (uuid4(), original_id),
                )
                raise AssertionError("concept identity update unexpectedly succeeded")
            except psycopg.errors.RaiseException:
                pass
            try:
                cur.execute(
                    "DELETE FROM oc_concepts.concepts WHERE concept_id=%s",
                    (original_id,),
                )
                raise AssertionError("concept deletion unexpectedly succeeded")
            except psycopg.errors.RaiseException:
                pass

            cur.execute(
                """
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema='oc_ontology'
                  AND table_name IN ('ontology_registries','ontology_terms')
                """
            )
            assert cur.fetchone()[0] == 2

    print("BUILD-SEM-002A PostgreSQL migration validation passed")


if __name__ == "__main__":
    main()
