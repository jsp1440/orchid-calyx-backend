import uuid
from datetime import date, datetime
from sqlalchemy import Column, String, Date, DateTime, ForeignKey, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def generate_uuid():
    return str(uuid.uuid4())


class Show(Base):
    __tablename__ = "shows"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    start_date = Column(Date, nullable=False)
    location = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Entry(Base):
    __tablename__ = "entries"

    id = Column(String, primary_key=True, default=generate_uuid)
    show_id = Column(String, ForeignKey("shows.id"), nullable=False)
    exhibitor_name = Column(String, nullable=False)
    plant_name = Column(String, nullable=False)
    class_code = Column(String, nullable=True)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)


class VolunteerTask(Base):
    __tablename__ = "volunteer_tasks"

    id = Column(String, primary_key=True, default=generate_uuid)
    show_id = Column(String, ForeignKey("shows.id"), nullable=False)
    title = Column(String, nullable=False)
    assigned_to = Column(String, nullable=True)
    status = Column(String, default="open")
    created_at = Column(DateTime, default=datetime.utcnow)


class Award(Base):
    __tablename__ = "awards"

    id = Column(String, primary_key=True, default=generate_uuid)
    entry_id = Column(String, ForeignKey("entries.id"), nullable=False)
    award_name = Column(String, nullable=False)
    level = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
