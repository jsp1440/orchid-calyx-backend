# CALYX CI — occurrence workflow repair (#949)

Date: 2026-08-13
Status: validated on repair branch; merge pending.

## Symptom

`CALYX Occurrence Consolidated Validation` produced repeated failed workflow runs with no runner jobs. Because no job existed, occurrence tests, taxonomy guards, and PostgreSQL integration had not executed in those runs.

## Verified diagnosis

The failure was in workflow configuration, not occurrence science. Replacing the database connection configuration with unambiguous local CI fields allowed GitHub to parse the workflow and create a real `occurrence-consolidated` runner job.

The first real runner execution then exposed a second configuration defect: the interim libpq key/value DSN was accepted by psycopg but not by SQLAlchemy `create_engine()`. That failure occurred before scientific assertions and was corrected without changing occurrence code.

## Final repair

The workflow now:

- keeps the isolated PostgreSQL 16 service with ordinary test-only user/password/database fields;
- stores only separate `PGUSER`, `PGPASSWORD`, `PGDATABASE`, `PGHOST`, and `PGPORT` values in workflow environment configuration;
- constructs the SQLAlchemy `postgresql+psycopg` URL inside the runner after dependencies are installed using `sqlalchemy.URL.create()`;
- writes the generated value to `DATABASE_URL` and `TEST_DATABASE_URL` through `GITHUB_ENV`;
- uses explicit YAML forms for `workflow_dispatch` and the service port;
- retains the original pull-request path scoping and manual-dispatch behavior.

No production database credential is introduced by this repair. The configured database identity is confined to the disposable GitHub Actions PostgreSQL service.

## Validation

A temporary branch-only `push` trigger was added solely to force GitHub to parse and execute the repaired workflow before merge. Run `31748597679` created the real `occurrence-consolidated` job and passed every substantive validation step:

1. PostgreSQL service initialization;
2. dependency installation;
3. runtime/test Python compilation;
4. Ruff checks;
5. PostgreSQL taxonomy-bound occurrence integration tests;
6. exact-replay regression;
7. migration non-authority assertions;
8. `git diff --check`.

The temporary `push` trigger was removed after this proof. The final workflow retains only its intended pull-request and manual-dispatch triggers.

## Scientific invariants

No occurrence persistence logic, taxonomy-review guard, reconciliation identity rule, migration, production database setting, or canonical graph authority was changed. In particular, the workflow continues to protect the rule that occurrence reconciliation cannot invent canonical taxon identity or bypass taxonomy-review evidence.

## Outcome

Issue #949 was a CI execution defect. The repaired workflow now reaches and passes the occurrence scientific validation suite, restoring meaningful CI coverage instead of zero-job failure noise.
