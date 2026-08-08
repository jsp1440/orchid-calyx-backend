from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from threading import RLock
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class ConversationStore:
    """Persist Calyx conversations in PostgreSQL with a deterministic memory fallback.

    Production uses DATABASE_URL. The memory fallback exists for local development and
    isolated tests only; callers can inspect ``persistence_mode`` to make that explicit.
    """

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn if dsn is not None else os.getenv("DATABASE_URL")
        self._lock = RLock()
        self._conversations: dict[str, dict[str, Any]] = {}
        self._messages: dict[str, list[dict[str, Any]]] = {}

    @property
    def persistence_mode(self) -> str:
        return "postgres" if self.dsn else "memory"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def ensure_schema(self) -> None:
        if not self.dsn:
            return
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS calyx_conversations (
                        conversation_id UUID PRIMARY KEY,
                        title TEXT,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        context JSONB NOT NULL DEFAULT '{}'::jsonb,
                        status TEXT NOT NULL DEFAULT 'active'
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS calyx_conversation_messages (
                        message_id UUID PRIMARY KEY,
                        conversation_id UUID NOT NULL REFERENCES calyx_conversations(conversation_id) ON DELETE CASCADE,
                        role TEXT NOT NULL CHECK (role IN ('operator','calyx','system')),
                        content TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_calyx_messages_conversation_created ON calyx_conversation_messages(conversation_id, created_at)"
                )
            conn.commit()

    def create_or_touch(self, conversation_id: str | None, *, title: str | None, context: dict[str, Any]) -> str:
        cid = conversation_id or str(uuid.uuid4())
        if self.dsn:
            self.ensure_schema()
            with psycopg.connect(self.dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO calyx_conversations(conversation_id, title, context)
                        VALUES (%s::uuid, %s, %s)
                        ON CONFLICT (conversation_id) DO UPDATE
                        SET updated_at=now(),
                            title=COALESCE(calyx_conversations.title, EXCLUDED.title),
                            context=calyx_conversations.context || EXCLUDED.context
                        """,
                        (cid, title, Jsonb(context)),
                    )
                conn.commit()
            return cid

        now = self._now()
        with self._lock:
            existing = self._conversations.get(cid)
            if existing is None:
                self._conversations[cid] = {
                    "conversation_id": cid,
                    "title": title,
                    "created_at": now,
                    "updated_at": now,
                    "context": dict(context),
                    "status": "active",
                }
                self._messages[cid] = []
            else:
                existing["updated_at"] = now
                existing["context"].update(context)
                if not existing.get("title") and title:
                    existing["title"] = title
        return cid

    def append(self, conversation_id: str, role: str, content: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        message_id = str(uuid.uuid4())
        metadata = metadata or {}
        if self.dsn:
            self.ensure_schema()
            with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO calyx_conversation_messages(message_id, conversation_id, role, content, metadata)
                        VALUES (%s::uuid, %s::uuid, %s, %s, %s)
                        RETURNING message_id::text, conversation_id::text, role, content, created_at, metadata
                        """,
                        (message_id, conversation_id, role, content, Jsonb(metadata)),
                    )
                    row = cur.fetchone()
                    cur.execute("UPDATE calyx_conversations SET updated_at=now() WHERE conversation_id=%s::uuid", (conversation_id,))
                conn.commit()
            return dict(row)

        item = {
            "message_id": message_id,
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "created_at": self._now(),
            "metadata": metadata,
        }
        with self._lock:
            self._messages.setdefault(conversation_id, []).append(item)
            if conversation_id in self._conversations:
                self._conversations[conversation_id]["updated_at"] = item["created_at"]
        return item

    def get(self, conversation_id: str, *, message_limit: int = 100) -> dict[str, Any] | None:
        if self.dsn:
            self.ensure_schema()
            with psycopg.connect(self.dsn, row_factory=dict_row) as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT conversation_id::text, title, created_at, updated_at, context, status FROM calyx_conversations WHERE conversation_id=%s::uuid",
                    (conversation_id,),
                )
                conversation = cur.fetchone()
                if conversation is None:
                    return None
                cur.execute(
                    """
                    SELECT message_id::text, conversation_id::text, role, content, created_at, metadata
                    FROM calyx_conversation_messages
                    WHERE conversation_id=%s::uuid
                    ORDER BY created_at ASC
                    LIMIT %s
                    """,
                    (conversation_id, message_limit),
                )
                messages = [dict(row) for row in cur.fetchall()]
            result = dict(conversation)
            result["messages"] = messages
            return result

        with self._lock:
            conversation = self._conversations.get(conversation_id)
            if conversation is None:
                return None
            return {**conversation, "messages": list(self._messages.get(conversation_id, []))[:message_limit]}

    def recent(self, *, limit: int = 20) -> list[dict[str, Any]]:
        if self.dsn:
            self.ensure_schema()
            with psycopg.connect(self.dsn, row_factory=dict_row) as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT c.conversation_id::text, c.title, c.created_at, c.updated_at, c.context, c.status,
                           COUNT(m.message_id)::int AS message_count
                    FROM calyx_conversations c
                    LEFT JOIN calyx_conversation_messages m ON m.conversation_id=c.conversation_id
                    GROUP BY c.conversation_id
                    ORDER BY c.updated_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                return [dict(row) for row in cur.fetchall()]

        with self._lock:
            rows = []
            for cid, conversation in self._conversations.items():
                rows.append({**conversation, "message_count": len(self._messages.get(cid, []))})
            rows.sort(key=lambda item: item["updated_at"], reverse=True)
            return rows[:limit]

    def history_text(self, conversation_id: str, *, turns: int = 6, max_chars: int = 1800) -> str:
        conversation = self.get(conversation_id, message_limit=max(2, turns * 2))
        if not conversation:
            return ""
        messages = conversation.get("messages", [])[-turns * 2 :]
        text = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        return text[-max_chars:]
