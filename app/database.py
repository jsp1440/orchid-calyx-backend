import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

Base = declarative_base()

_engine = None
_SessionLocal = None


def get_database_url() -> str:
    """
    CANONICAL RULE:
    1) If DATABASE_URL is set, ALWAYS use it. (This is the intended single source of truth.)
    2) Only fall back to Replit PG* vars if DATABASE_URL is NOT set.
    3) Final fallback: sqlite local dev.
    """
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    # Fallback (Replit / legacy)
    pghost = os.getenv("PGHOST")
    if pghost:
        pguser = os.getenv("PGUSER", "postgres")
        pgpassword = os.getenv("PGPASSWORD", "")
        pgdatabase = os.getenv("PGDATABASE", "postgres")
        pgport = os.getenv("PGPORT", "5432")
        return f"postgresql://{pguser}:{pgpassword}@{pghost}:{pgport}/{pgdatabase}"

    return "sqlite:///./calyx.db"


def get_engine():
    global _engine
    if _engine is None:
        database_url = get_database_url()

        connect_args = {}
        if database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False

        if '@' in database_url:
            scheme_part = database_url.split('://')[0]
            host_part = database_url.split('@', 1)[1]
            print(f"[DB] Connecting to: {scheme_part}://***@{host_part}")
        else:
            print(f"[DB] Connecting to: {database_url}")

        _engine = create_engine(
            database_url,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
    return _engine


def get_session_local():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(autocommit=False,
                                     autoflush=False,
                                     bind=get_engine())
    return _SessionLocal


def get_db():
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
