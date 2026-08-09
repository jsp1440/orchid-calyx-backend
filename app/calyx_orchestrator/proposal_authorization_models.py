from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

from .models import utcnow


class ProposalAuthorizationDecisionRecord(Base):
    __tablename__ = "calyx_proposal_authorization_decisions"
    __table_args__ = (
        UniqueConstraint(
            "manifest_digest",
            "review_class",
            name="uq_calyx_proposal_authorization_manifest_class",
        ),
    )

    record_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    manifest_digest: Mapped[str] = mapped_column(String(64), index=True)
    review_class: Mapped[str] = mapped_column(String(40), index=True)
    authorization_digest: Mapped[str] = mapped_column(
        String(64), unique=True, index=True
    )
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
