"""Write-ahead provider evidence, not a queue or source of execution authority."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

from .models import utcnow


class AzureExecutionRecord(Base):
    __tablename__ = "calyx_azure_execution_records"

    program_job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("calyx_engineering_program_jobs.program_job_id"),
        primary_key=True,
    )
    lease_digest: Mapped[str] = mapped_column(String(64))
    input_checksum: Mapped[str] = mapped_column(String(64))
    config_checksum: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(40))
    execution_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    receipt_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
