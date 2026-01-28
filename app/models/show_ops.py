from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, ForeignKey, Integer, Text, Boolean, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class ShowZone(Base):
    __tablename__ = "show_zones"

    __table_args__ = (
        UniqueConstraint("show_id", "name", name="uq_show_zones_show_id_name"),
        Index("ix_show_zones_show_id_zone_type", "show_id", "zone_type"),
    )


    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    show_id: Mapped[str] = mapped_column(String(36), ForeignKey("shows.id"), index=True)

    zone_type: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    capacity_hint: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    show = relationship("Show", back_populates="zones")


class Vendor(Base):
    __tablename__ = "vendors"

    __table_args__ = (
        UniqueConstraint("show_id", "name", name="uq_vendors_show_id_name"),
        Index("ix_vendors_show_id_vendor_type", "show_id", "vendor_type"),
    )


    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    show_id: Mapped[str] = mapped_column(String(36), ForeignKey("shows.id"), index=True)

    vendor_type: Mapped[str] = mapped_column(String(20), default="PLANT")  # PLANT|FOOD|OTHER
    name: Mapped[str] = mapped_column(String(200))

    contact_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    zone_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("show_zones.id"), nullable=True)
    setup_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    show = relationship("Show", back_populates="vendors")


class TrainingAsset(Base):
    __tablename__ = "training_assets"

    __table_args__ = (
        Index("ix_training_assets_show_id_asset_type", "show_id", "asset_type"),
    )


    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    show_id: Mapped[str] = mapped_column(String(36), ForeignKey("shows.id"), index=True)

    asset_type: Mapped[str] = mapped_column(String(20))  # PDF|LINK|VIDEO|TEXT
    title: Mapped[str] = mapped_column(String(200))

    content_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    tags: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    show = relationship("Show", back_populates="training_assets")
    roles = relationship("VolunteerRole", back_populates="training_asset")


class VolunteerRole(Base):
    __tablename__ = "volunteer_roles"

    __table_args__ = (
        UniqueConstraint("show_id", "role_key", name="uq_volunteer_roles_show_id_role_key"),
        Index("ix_volunteer_roles_show_id_display_name", "show_id", "display_name"),
    )


    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    show_id: Mapped[str] = mapped_column(String(36), ForeignKey("shows.id"), index=True)

    role_key: Mapped[str] = mapped_column(String(80))
    display_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    default_zone_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    requires_training: Mapped[bool] = mapped_column(Boolean, default=False)
    training_asset_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("training_assets.id"), nullable=True)

    min_people_per_shift: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    show = relationship("Show", back_populates="volunteer_roles")
    training_asset = relationship("TrainingAsset", back_populates="roles")
    shifts = relationship("VolunteerShift", back_populates="role")


class VolunteerShift(Base):
    __tablename__ = "volunteer_shifts"

    __table_args__ = (
        Index("ix_volunteer_shifts_show_id_start", "show_id", "start_time"),
        Index("ix_volunteer_shifts_role_id_start", "role_id", "start_time"),
    )


    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    show_id: Mapped[str] = mapped_column(String(36), ForeignKey("shows.id"), index=True)
    role_id: Mapped[str] = mapped_column(String(36), ForeignKey("volunteer_roles.id"), index=True)

    zone_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("show_zones.id"), nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime)
    end_time: Mapped[datetime] = mapped_column(DateTime)

    capacity: Mapped[int] = mapped_column(Integer, default=1)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    show = relationship("Show", back_populates="shifts")
    role = relationship("VolunteerRole", back_populates="shifts")
    signups = relationship("VolunteerSignup", back_populates="shift")


class VolunteerSignup(Base):
    __tablename__ = "volunteer_signups"

    __table_args__ = (
        Index("ix_volunteer_signups_shift_id_status", "shift_id", "status"),
    )


    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    shift_id: Mapped[str] = mapped_column(String(36), ForeignKey("volunteer_shifts.id"), index=True)

    full_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="SIGNED_UP")
    checked_in_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    checked_out_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    checkin_method: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    shift = relationship("VolunteerShift", back_populates="signups")
