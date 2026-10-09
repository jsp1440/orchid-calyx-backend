"""Authenticated canonical producer: admission -> durable program queue."""
from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import verify_owner_or_api_key

from .build_queue import GovernedBuildQueue
from .constitution import BuildAdmissionRequest
from .program_handoff import persist_governed_queue
from .scheduler_bridge import SchedulerJobMetadata

PRODUCER_SCHEMA = "canonical-brain-program-handoff.v1"
AuthDependency = Annotated[dict[str, Any], Depends(verify_owner_or_api_key)]
DbDependency = Annotated[Session, Depends(get_db)]


class BrainProgramRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["canonical-brain-program-handoff.v1"]
    admissions: list[BuildAdmissionRequest] = Field(min_length=1, max_length=50)
    metadata: tuple[SchedulerJobMetadata, ...] = Field(min_length=1, max_length=50)
    dependencies: tuple[tuple[str, str], ...] = Field(max_length=200)
    inputs: dict[str, dict[str, Any]]


def submit_brain_program(payload: BrainProgramRequest, auth: AuthDependency, db: DbDependency):
    # Match existing program ownership: principal from verified auth, never body.
    owner = str(auth.get("subject") or auth.get("actor") or "").strip()
    if not owner:
        raise HTTPException(401, detail={"code": "AUTHENTICATED_OWNER_REQUIRED"})
    try:
        queue = GovernedBuildQueue()
        admissions = {record.build_id: record for record in payload.admissions}
        if len(admissions) != len(payload.admissions):
            raise ValueError("BRAIN_HANDOFF_DUPLICATE_ADMISSION")
        for record in payload.admissions:
            queue.submit(record)
        if set(payload.inputs) != set(admissions):
            raise ValueError("BRAIN_HANDOFF_INPUT_IDENTITIES_MISMATCH")
        inputs = {
            key: {
                **value,
                # Preserve submitted source/intent/decision/validation references.
                # These are declared provenance, not verified scientific results.
                "brain_request_provenance": {
                    "schema": PRODUCER_SCHEMA,
                    "admission_request": admissions[key].model_dump(mode="json"),
                },
            }
            for key, value in payload.inputs.items()
        }
        program = persist_governed_queue(
            db, owner=owner, queue=queue.snapshot(), metadata=payload.metadata,
            dependencies=payload.dependencies, inputs=inputs,
        )
        return {
            "schema": PRODUCER_SCHEMA, "program_id": program.program_id,
            "status": program.status, "build_ids": sorted(admissions),
            "authority": {"scientific_publication": False, "provider_calls": False},
        }
    except (ValueError, PermissionError, LookupError) as exc:
        db.rollback()
        raise HTTPException(409, detail={"code": str(exc)}) from exc
