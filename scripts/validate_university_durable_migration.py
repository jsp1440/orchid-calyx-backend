#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "ocu_sci_008_durable_sessions.sql"

REQUIRED_FRAGMENTS = (
    "CREATE SCHEMA IF NOT EXISTS oc_university",
    "CREATE TABLE IF NOT EXISTS oc_university.lab_sessions",
    "CREATE TABLE IF NOT EXISTS oc_university.session_events",
    "CREATE TABLE IF NOT EXISTS oc_university.session_reviews",
    "publication_allowed BOOLEAN NOT NULL DEFAULT FALSE CHECK (publication_allowed = FALSE)",
    "automatic_candidate_knowledge BOOLEAN NOT NULL DEFAULT FALSE CHECK (automatic_candidate_knowledge = FALSE)",
    "human_review_required BOOLEAN NOT NULL DEFAULT TRUE CHECK (human_review_required = TRUE)",
    "candidate_knowledge_promoted BOOLEAN NOT NULL DEFAULT FALSE CHECK (candidate_knowledge_promoted = FALSE)",
    "publication_performed BOOLEAN NOT NULL DEFAULT FALSE CHECK (publication_performed = FALSE)",
    "UNIQUE (session_id, sequence_no)",
    "UNIQUE (session_id, session_revision)",
)

PROHIBITED_FRAGMENTS = (
    "candidate_knowledge_promoted BOOLEAN NOT NULL DEFAULT TRUE",
    "publication_allowed BOOLEAN NOT NULL DEFAULT TRUE",
    "publication_performed BOOLEAN NOT NULL DEFAULT TRUE",
    "ON DELETE SET NULL",
)


def validate(text: str) -> list[str]:
    errors: list[str] = []
    for fragment in REQUIRED_FRAGMENTS:
        if fragment not in text:
            errors.append(f"missing required migration invariant: {fragment}")
    for fragment in PROHIBITED_FRAGMENTS:
        if fragment in text:
            errors.append(f"prohibited migration fragment present: {fragment}")
    return errors


def main() -> int:
    text = MIGRATION.read_text(encoding="utf-8")
    errors = validate(text)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"VALID: {MIGRATION}")
    print("Durable University migration preserves review and publication safeguards.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
