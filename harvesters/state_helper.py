"""
harvesters/state_helper.py

State + bookkeeping helpers for harvesters.

Goals:
- Always return a dict from get_state() (never None)
- Provide robust record_harvest_result() that tolerates extra kwargs
- Create/maintain harvest_state table if missing
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import psycopg2
import psycopg2.extras


DATABASE_URL_ENV = "DATABASE_URL"


def _get_db_url() -> str:
    url = os.getenv(DATABASE_URL_ENV)
    if not url:
        raise RuntimeError(
            f"{DATABASE_URL_ENV} is not set. Export it (e.g., export {DATABASE_URL_ENV}=...)"
        )
    return url


def _connect():
    # Using sslmode=require is safe for Neon and most hosted PGs; if your URL already has sslmode it will be respected.
    url = _get_db_url()
    if "sslmode=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}sslmode=require"
    return psycopg2.connect(url)


def ensure_state_table() -> None:
    """
    Ensures public.harvest_state exists with expected columns.
    Safe to call repeatedly.
    """
    ddl = """
    CREATE TABLE IF NOT EXISTS public.harvest_state (
        source        text PRIMARY KEY,
        last_offset   integer NOT NULL DEFAULT 0,
        updated_at    timestamptz NOT NULL DEFAULT now(),
        total_inserted bigint NOT NULL DEFAULT 0,
        exhausted     boolean NOT NULL DEFAULT false,
        error_count   integer NOT NULL DEFAULT 0,
        last_error    text,
        created_at    timestamptz NOT NULL DEFAULT now(),
        last_run_at   timestamptz,
        meta         jsonb
    );
    """

    images_ddl = """
    CREATE TABLE IF NOT EXISTS public.images (
        id bigserial PRIMARY KEY
    );
    """

    trigger_fn = """
    CREATE OR REPLACE FUNCTION public.sync_updated_at()
    RETURNS trigger AS $$
    BEGIN
        NEW.updated_at := now();
        IF NEW.last_run_at IS NULL THEN
            NEW.last_run_at := now();
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

    trigger = """
    DROP TRIGGER IF EXISTS harvest_state_sync ON public.harvest_state;
    CREATE TRIGGER harvest_state_sync
    BEFORE UPDATE ON public.harvest_state
    FOR EACH ROW
    EXECUTE FUNCTION public.sync_updated_at();
    """

    alters = [
        "ALTER TABLE public.harvest_state ADD COLUMN IF NOT EXISTS total_inserted bigint NOT NULL DEFAULT 0;",
        "ALTER TABLE public.harvest_state ADD COLUMN IF NOT EXISTS exhausted boolean NOT NULL DEFAULT false;",
        "ALTER TABLE public.harvest_state ADD COLUMN IF NOT EXISTS error_count integer NOT NULL DEFAULT 0;",
        "ALTER TABLE public.harvest_state ADD COLUMN IF NOT EXISTS last_error text;",
        "ALTER TABLE public.harvest_state ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();",
        "ALTER TABLE public.harvest_state ADD COLUMN IF NOT EXISTS last_run_at timestamptz;",
        "ALTER TABLE public.harvest_state ADD COLUMN IF NOT EXISTS meta jsonb;",
        "ALTER TABLE public.images ADD COLUMN IF NOT EXISTS source text;",
        "ALTER TABLE public.images ADD COLUMN IF NOT EXISTS url text;",
        "ALTER TABLE public.images ADD COLUMN IF NOT EXISTS genus text;",
        "ALTER TABLE public.images ADD COLUMN IF NOT EXISTS species text;",
        "ALTER TABLE public.images ADD COLUMN IF NOT EXISTS scientific_name text;",
        "ALTER TABLE public.images ADD COLUMN IF NOT EXISTS country text;",
        "ALTER TABLE public.images ADD COLUMN IF NOT EXISTS latitude double precision;",
        "ALTER TABLE public.images ADD COLUMN IF NOT EXISTS longitude double precision;",
        "ALTER TABLE public.images ADD COLUMN IF NOT EXISTS photographer text;",
        "ALTER TABLE public.images ADD COLUMN IF NOT EXISTS license text;",
        "ALTER TABLE public.images ADD COLUMN IF NOT EXISTS source_id text;",
        "ALTER TABLE public.images ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();",
    ]

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)
            cur.execute(images_ddl)
            for a in alters:
                cur.execute(a)
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS images_url_unique ON public.images (url);")
            cur.execute(trigger_fn)
            cur.execute(trigger)
        conn.commit()


def _coerce_jsonb(value: Any) -> Any:
    # psycopg2 can handle dict -> json automatically via Json wrapper,
    # but we keep this explicit for safety.
    return psycopg2.extras.Json(value) if isinstance(value, (dict, list)) else value


def get_state(source: str) -> Dict[str, Any]:
    """
    Returns a dict for the given source. If missing, inserts a default row and returns defaults.
    NEVER returns None.
    """
    ensure_state_table()

    q_sel = "SELECT source, last_offset, total_inserted, exhausted, error_count, last_error, meta, last_run_at, updated_at, created_at FROM public.harvest_state WHERE source=%s"
    q_ins = "INSERT INTO public.harvest_state (source) VALUES (%s) ON CONFLICT (source) DO NOTHING"

    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(q_sel, (source,))
            row = cur.fetchone()
            if not row:
                cur.execute(q_ins, (source,))
                conn.commit()
                cur.execute(q_sel, (source,))
                row = cur.fetchone()

    if not row:
        return {
            "source": source,
            "last_offset": 0,
            "total_inserted": 0,
            "exhausted": False,
            "error_count": 0,
            "last_error": None,
            "meta": {},
            "last_run_at": None,
        }

    meta = row.get("meta") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}

    row["meta"] = meta
    return dict(row)


def save_state(source: str, state: Optional[Dict[str, Any]] = None, **fields: Any) -> None:
    """
    Persists updated state/meta fields for a source.
    """
    ensure_state_table()

    merged: Dict[str, Any] = {}
    if state:
        merged.update(state)
    merged.update(fields)

    meta = merged.get("meta", None)
    known_cols = {"last_offset", "total_inserted", "exhausted", "error_count", "last_error", "last_run_at"}
    col_updates: Dict[str, Any] = {k: merged[k] for k in known_cols if k in merged}

    extra_keys = {k: v for k, v in merged.items() if k not in known_cols and k not in {"source", "updated_at", "created_at", "meta"}}
    if extra_keys:
        if not isinstance(meta, dict) or meta is None:
            meta = {}
        meta = {**meta, **extra_keys}

    sets = []
    params = []
    for k, v in col_updates.items():
        sets.append(f"{k}=%s")
        params.append(v)

    if meta is not None:
        sets.append("meta=%s")
        params.append(_coerce_jsonb(meta))

    if not sets:
        return

    q = f"UPDATE public.harvest_state SET {', '.join(sets)} WHERE source=%s"
    params.append(source)

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(q, tuple(params))
        conn.commit()


def is_source_exhausted(source: str) -> bool:
    st = get_state(source)
    return bool(st.get("exhausted", False))


def mark_source_exhausted(source: str, exhausted: bool = True, reason: Optional[str] = None) -> None:
    st = get_state(source)
    meta = st.get("meta") or {}
    if reason:
        meta["exhausted_reason"] = reason
    save_state(source, exhausted=exhausted, meta=meta)


def bump_error(source: str, err: str) -> None:
    st = get_state(source)
    save_state(source, error_count=int(st.get("error_count") or 0) + 1, last_error=str(err), last_run_at=None)
