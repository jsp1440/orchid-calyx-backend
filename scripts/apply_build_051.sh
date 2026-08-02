#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL must be set}"

psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/BUILD-051-owner-operations-console.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/BUILD-051-owner-operations-smoke-test.sql

echo "BUILD-051 migration and database smoke test completed successfully."
