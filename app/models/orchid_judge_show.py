from __future__ import annotations

import uuid
from datetime import datetime, date, time
from typing import Optional

from sqlalchemy import String, Date, Time, DateTime, Boolean, ForeignKey, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Organization(Base):
    """Minimal org model for show ownership + multi-tenant routing later."""
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    shows = relationship("Show", back_populates="organization")


class Show(Base):
    __tablename__ = "shows"

    __table_args__ = (
        Index("ix_shows_org_id_start_date", "organization_id", "start_date"),
    )


    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), index=True)

    name: Mapped[str] = mapped_column(String(200))
    venue_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)

    setup_window_start: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    setup_window_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    judging_window_start: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    judging_window_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    doors_open_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)

    internet_reliability: Mapped[str] = mapped_column(String(20), default="SPOTTY")  # GOOD|SPOTTY|NONE
    scale: Mapped[str] = mapped_column(String(20), default="SMALL")  # SMALL|MEDIUM|LARGE

    module_judging: Mapped[bool] = mapped_column(Boolean, default=True)
    module_displays: Mapped[bool] = mapped_column(Boolean, default=True)
    module_vendors: Mapped[bool] = mapped_column(Boolean, default=True)
    module_volunteers: Mapped[bool] = mapped_column(Boolean, default=True)
    module_auctions: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    organization = relationship("Organization", back_populates="shows")
    zones = relationship("ShowZone", back_populates="show")
    vendors = relationship("Vendor", back_populates="show")
    volunteer_roles = relationship("VolunteerRole", back_populates="show")
    training_assets = relationship("TrainingAsset", back_populates="show")
    shifts = relationship("VolunteerShift", back_populates="show")

    entries = relationship("ShowEntry", back_populates="show")


class ShowEntry(Base):
    """Minimal entry model: enough to support future judging + linking photos."""
    __tablename__ = "show_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    show_id: Mapped[str] = mapped_column(String(36), ForeignKey("shows.id"), index=True)

    entry_number: Mapped[str] = mapped_column(String(50), index=True)
    exhibitor_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    plant_display_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    taxon_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    show = relationship("Show", back_populates="entries")
