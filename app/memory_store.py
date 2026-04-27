from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Iterator, List
from uuid import uuid4

from .security_utils import ensure_private_dir, ensure_private_file

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "storage"
MEMORY_DB_PATH = STORAGE_DIR / "user_memory.sqlite"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class UserMemoryStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        ensure_private_dir(self.db_path.parent)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = RLock()
        self._setup()
        self._harden_storage_files()

    def _harden_storage_files(self) -> None:
        ensure_private_file(self.db_path)
        ensure_private_file(self.db_path.with_name(f"{self.db_path.name}-wal"))
        ensure_private_file(self.db_path.with_name(f"{self.db_path.name}-shm"))

    def _setup(self) -> None:
        with self.lock:
            self.conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA secure_delete=ON;

                CREATE TABLE IF NOT EXISTS user_memories (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'assistant',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_user_memories_user_updated
                ON user_memories (user_id, updated_at DESC);

                CREATE INDEX IF NOT EXISTS idx_user_memories_user_category
                ON user_memories (user_id, category);
                """
            )
            self.conn.commit()
            self._harden_storage_files()

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        with self.lock:
            cur = self.conn.cursor()
            try:
                yield cur
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
            finally:
                self._harden_storage_files()
                cur.close()

    def _row_to_memory(self, row: sqlite3.Row | None) -> Dict[str, Any] | None:
        if row is None:
            return None
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "category": row["category"],
            "content": row["content"],
            "reason": row["reason"],
            "source": row["source"],
            "is_active": bool(row["is_active"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _fetch_memory_by_id(
        self,
        cur: sqlite3.Cursor,
        user_id: str,
        memory_id: str,
        *,
        include_inactive: bool = False,
    ) -> Dict[str, Any] | None:
        params: List[Any] = [user_id, memory_id]
        active_clause = "" if include_inactive else " AND is_active = 1"
        cur.execute(
            f"""
            SELECT id, user_id, category, content, reason, source, is_active, created_at, updated_at
            FROM user_memories
            WHERE user_id = ? AND id = ?{active_clause}
            LIMIT 1
            """,
            params,
        )
        return self._row_to_memory(cur.fetchone())

    def _fetch_memories_by_ids(
        self,
        cur: sqlite3.Cursor,
        user_id: str,
        memory_ids: List[str],
        *,
        include_inactive: bool = False,
    ) -> List[Dict[str, Any]]:
        normalized_ids = [memory_id for memory_id in dict.fromkeys(memory_ids) if memory_id]
        if not normalized_ids:
            return []

        placeholders = ",".join("?" for _ in normalized_ids)
        active_clause = "" if include_inactive else " AND is_active = 1"
        cur.execute(
            f"""
            SELECT id, user_id, category, content, reason, source, is_active, created_at, updated_at
            FROM user_memories
            WHERE user_id = ? AND id IN ({placeholders}){active_clause}
            """,
            [user_id, *normalized_ids],
        )
        rows = {row["id"]: self._row_to_memory(row) for row in cur.fetchall()}
        return [rows[memory_id] for memory_id in normalized_ids if memory_id in rows]

    def get_memory_by_id(self, user_id: str, memory_id: str, include_inactive: bool = False) -> Dict[str, Any] | None:
        with self._cursor() as cur:
            return self._fetch_memory_by_id(cur, user_id, memory_id, include_inactive=include_inactive)

    def get_memories_by_ids(
        self,
        user_id: str,
        memory_ids: List[str],
        include_inactive: bool = False,
    ) -> List[Dict[str, Any]]:
        with self._cursor() as cur:
            return self._fetch_memories_by_ids(cur, user_id, memory_ids, include_inactive=include_inactive)

    def find_memories_by_content(
        self,
        user_id: str,
        content: str,
        category: str | None = None,
        include_inactive: bool = False,
    ) -> List[Dict[str, Any]]:
        normalized_content = str(content or "").strip()
        if not normalized_content:
            return []

        with self._cursor() as cur:
            params: List[Any] = [user_id, normalized_content]
            category_clause = ""
            if category is not None:
                category_clause = " AND category = ?"
                params.append(str(category))
            active_clause = "" if include_inactive else " AND is_active = 1"
            cur.execute(
                f"""
                SELECT id, user_id, category, content, reason, source, is_active, created_at, updated_at
                FROM user_memories
                WHERE user_id = ? AND content = ?{category_clause}{active_clause}
                ORDER BY updated_at DESC
                """,
                params,
            )
            return [self._row_to_memory(row) for row in cur.fetchall()]

    def find_exact_memory(self, user_id: str, content: str, category: str = "") -> Dict[str, Any] | None:
        memories = self.find_memories_by_content(user_id, content, category=category, include_inactive=False)
        return memories[0] if memories else None

    def search_memories(self, user_id: str, query: str = "", limit: int = 5) -> List[Dict[str, Any]]:
        normalized_query = str(query or "").strip()
        safe_limit = max(1, min(int(limit), 50))

        with self._cursor() as cur:
            if not normalized_query:
                cur.execute(
                    """
                    SELECT id, user_id, category, content, reason, source, is_active, created_at, updated_at
                    FROM user_memories
                    WHERE user_id = ? AND is_active = 1
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (user_id, safe_limit),
                )
                return [self._row_to_memory(row) for row in cur.fetchall()]

            terms = [normalized_query]
            for token in normalized_query.split():
                token = token.strip()
                if len(token) >= 2 and token not in terms:
                    terms.append(token)

            where_parts: List[str] = []
            params: List[Any] = [user_id]
            for term in terms[:5]:
                wildcard = f"%{term}%"
                where_parts.append("(content LIKE ? OR category LIKE ? OR reason LIKE ?)")
                params.extend([wildcard, wildcard, wildcard])
            params.append(safe_limit)

            cur.execute(
                f"""
                SELECT id, user_id, category, content, reason, source, is_active, created_at, updated_at
                FROM user_memories
                WHERE user_id = ? AND is_active = 1 AND ({' OR '.join(where_parts)})
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                params,
            )
            return [self._row_to_memory(row) for row in cur.fetchall()]

    def count_active_memories(self, user_id: str) -> int:
        with self._cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM user_memories WHERE user_id = ? AND is_active = 1",
                (user_id,),
            )
            return int(cur.fetchone()[0])

    def save_memory(
        self,
        user_id: str,
        content: str,
        category: str = "",
        reason: str = "",
        source: str = "assistant",
    ) -> Dict[str, Any]:
        normalized_content = str(content or "").strip()
        normalized_category = str(category or "").strip()
        normalized_reason = str(reason or "").strip()
        timestamp = now_iso()

        existing = self.find_exact_memory(user_id, normalized_content, normalized_category)
        if existing is not None:
            with self._cursor() as cur:
                next_reason = existing.get("reason") or normalized_reason
                cur.execute(
                    """
                    UPDATE user_memories
                    SET reason = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (next_reason, timestamp, existing["id"]),
                )
                cur.execute(
                    """
                    SELECT id, user_id, category, content, reason, source, is_active, created_at, updated_at
                    FROM user_memories
                    WHERE id = ?
                    """,
                    (existing["id"],),
                )
                row = cur.fetchone()
            payload = self._row_to_memory(row) or existing
            payload["duplicate"] = True
            return payload

        memory_id = str(uuid4())
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_memories (
                    id, user_id, category, content, reason, source, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    user_id,
                    normalized_category,
                    normalized_content,
                    normalized_reason,
                    source,
                    timestamp,
                    timestamp,
                ),
            )
            cur.execute(
                """
                SELECT id, user_id, category, content, reason, source, is_active, created_at, updated_at
                FROM user_memories
                WHERE id = ?
                """,
                (memory_id,),
            )
            row = cur.fetchone()
        payload = self._row_to_memory(row) or {}
        payload["duplicate"] = False
        return payload

    def delete_memories(self, user_id: str, memory_ids: List[str]) -> List[Dict[str, Any]]:
        normalized_ids = [memory_id for memory_id in dict.fromkeys(memory_ids) if str(memory_id).strip()]
        if not normalized_ids:
            return []

        timestamp = now_iso()
        with self._cursor() as cur:
            active_memories = self._fetch_memories_by_ids(cur, user_id, normalized_ids, include_inactive=False)
            if not active_memories:
                return []

            placeholders = ",".join("?" for _ in active_memories)
            active_ids = [memory["id"] for memory in active_memories]
            cur.execute(
                f"""
                UPDATE user_memories
                SET is_active = 0, updated_at = ?
                WHERE user_id = ? AND id IN ({placeholders}) AND is_active = 1
                """,
                [timestamp, user_id, *active_ids],
            )
            return self._fetch_memories_by_ids(cur, user_id, active_ids, include_inactive=True)

    def purge_all_memories(self, user_id: str) -> int:
        with self._cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM user_memories WHERE user_id = ? AND is_active = 1",
                (user_id,),
            )
            active_count = int(cur.fetchone()[0])
            cur.execute(
                "DELETE FROM user_memories WHERE user_id = ?",
                (user_id,),
            )
            return active_count


user_memory_store = UserMemoryStore(MEMORY_DB_PATH)