from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Iterator, List

from .security_utils import ensure_private_dir, ensure_private_file

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "storage"
CHAT_DB_PATH = STORAGE_DIR / "chat_history.sqlite"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChatStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        ensure_private_dir(self.db_path.parent)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = RLock()
        self._setup()
        self._harden_storage_files()
        self._clear_legacy_json()

    def _harden_storage_files(self) -> None:
        ensure_private_file(self.db_path)
        ensure_private_file(self.db_path.with_name(f"{self.db_path.name}-wal"))
        ensure_private_file(self.db_path.with_name(f"{self.db_path.name}-shm"))

    def _setup(self) -> None:
        with self.lock:
            self.conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
                PRAGMA secure_delete=ON;

                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    model TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_conversations_user_updated
                ON conversations (user_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    parts TEXT NOT NULL DEFAULT '[]',
                    feedback TEXT,
                    is_error_fallback INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
                    UNIQUE(conversation_id, position)
                );

                CREATE INDEX IF NOT EXISTS idx_messages_conversation_position
                ON messages (conversation_id, position);
                """
            )
            self._ensure_message_columns()
            self.conn.commit()
            self._harden_storage_files()

    def _ensure_message_columns(self) -> None:
        columns = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(messages)").fetchall()
        }
        if "reasoning_content" not in columns:
            self.conn.execute("ALTER TABLE messages ADD COLUMN reasoning_content TEXT")

    def _clear_legacy_json(self) -> None:
        for path in STORAGE_DIR.glob("**/conversations.json*"):
            if path.is_file():
                path.unlink(missing_ok=True)

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        with self.lock:
            cur = self.conn.cursor()
            try:
                cur.execute("PRAGMA foreign_keys=ON")
                yield cur
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
            finally:
                self._harden_storage_files()
                cur.close()

    def _message_from_row(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "role": row["role"],
            "content": row["content"],
            "timestamp": row["timestamp"],
            "parts": json.loads(row["parts"] or "[]"),
            "reasoning_content": row["reasoning_content"] if "reasoning_content" in row.keys() else None,
            "feedback": row["feedback"],
            "is_error_fallback": bool(row["is_error_fallback"]),
        }

    def _get_conversation_row(self, cur: sqlite3.Cursor, user_id: str, conversation_id: str) -> sqlite3.Row | None:
        cur.execute(
            """
            SELECT id, user_id, title, model, thread_id, created_at, updated_at
            FROM conversations
            WHERE id = ? AND user_id = ?
            """,
            (conversation_id, user_id),
        )
        return cur.fetchone()

    def _get_messages(self, cur: sqlite3.Cursor, conversation_id: str) -> List[Dict[str, Any]]:
        cur.execute(
            """
            SELECT id, role, content, timestamp, parts, reasoning_content, feedback, is_error_fallback
            FROM messages
            WHERE conversation_id = ?
            ORDER BY position ASC
            """,
            (conversation_id,),
        )
        return [self._message_from_row(row) for row in cur.fetchall()]

    def _conversation_from_row(self, cur: sqlite3.Cursor, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "model": row["model"],
            "thread_id": row["thread_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "messages": self._get_messages(cur, row["id"]),
        }

    def _message_preview(self, messages: List[Dict[str, Any]]) -> str:
        preview = ""
        for skip_error_fallback in (True, False):
            for msg in reversed(messages):
                if skip_error_fallback and msg.get("is_error_fallback"):
                    continue
                preview = (msg.get("content") or "").strip()
                if preview:
                    return preview[:80]
        return preview[:80]

    def _summary_from_row(self, cur: sqlite3.Cursor, row: sqlite3.Row) -> Dict[str, Any]:
        messages = self._get_messages(cur, row["id"])
        return {
            "id": row["id"],
            "title": row["title"],
            "model": row["model"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "preview": self._message_preview(messages),
            "message_count": len(messages),
        }

    def _next_position(self, cur: sqlite3.Cursor, conversation_id: str) -> int:
        cur.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        )
        return int(cur.fetchone()[0])

    def _insert_message(self, cur: sqlite3.Cursor, conversation_id: str, message: Dict[str, Any]) -> None:
        cur.execute(
            """
            INSERT INTO messages (
                id, conversation_id, position, role, content, timestamp, parts, reasoning_content, feedback, is_error_fallback
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message["id"],
                conversation_id,
                self._next_position(cur, conversation_id),
                message["role"],
                message["content"],
                message["timestamp"],
                json.dumps(message.get("parts", []), ensure_ascii=False),
                message.get("reasoning_content"),
                message.get("feedback"),
                int(bool(message.get("is_error_fallback", False))),
            ),
        )

    def list_conversations(self, user_id: str) -> List[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, title, model, thread_id, created_at, updated_at
                FROM conversations
                WHERE user_id = ?
                ORDER BY updated_at DESC
                """,
                (user_id,),
            )
            rows = cur.fetchall()
            return [self._summary_from_row(cur, row) for row in rows]

    def get_user_data_summary(self, user_id: str) -> Dict[str, int]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM conversations WHERE user_id = ?",
                (user_id,),
            )
            conversation_count = int(cur.fetchone()[0])
            cur.execute(
                """
                SELECT COUNT(*)
                FROM messages m
                JOIN conversations c ON c.id = m.conversation_id
                WHERE c.user_id = ?
                """,
                (user_id,),
            )
            message_count = int(cur.fetchone()[0])
        return {
            "conversation_count": conversation_count,
            "message_count": message_count,
        }

    def find_reusable_conversation(self, user_id: str, title: str = "新对话") -> Dict[str, Any] | None:
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT c.id, c.user_id, c.title, c.model, c.thread_id, c.created_at, c.updated_at
                FROM conversations c
                WHERE c.user_id = ?
                  AND c.title = ?
                  AND NOT EXISTS (
                      SELECT 1 FROM messages m WHERE m.conversation_id = c.id
                  )
                ORDER BY c.updated_at DESC
                LIMIT 1
                """,
                (user_id, title),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return self._conversation_from_row(cur, row)

    def create_conversation(self, user_id: str, conversation: Dict[str, Any]) -> Dict[str, Any]:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversations (id, user_id, title, model, thread_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation["id"],
                    user_id,
                    conversation["title"],
                    conversation["model"],
                    conversation["thread_id"],
                    conversation["created_at"],
                    conversation["updated_at"],
                ),
            )
            row = self._get_conversation_row(cur, user_id, conversation["id"])
            return self._conversation_from_row(cur, row)

    def get_conversation(self, user_id: str, conversation_id: str) -> Dict[str, Any] | None:
        with self._cursor() as cur:
            row = self._get_conversation_row(cur, user_id, conversation_id)
            if row is None:
                return None
            return self._conversation_from_row(cur, row)

    def update_conversation(self, user_id: str, conversation_id: str, *, title: str | None = None, model: str | None = None, updated_at: str) -> Dict[str, Any] | None:
        with self._cursor() as cur:
            row = self._get_conversation_row(cur, user_id, conversation_id)
            if row is None:
                return None
            next_title = title if title is not None else row["title"]
            next_model = model if model is not None else row["model"]
            cur.execute(
                """
                UPDATE conversations
                SET title = ?, model = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (next_title, next_model, updated_at, conversation_id, user_id),
            )
            row = self._get_conversation_row(cur, user_id, conversation_id)
            return self._conversation_from_row(cur, row)

    def delete_conversation(self, user_id: str, conversation_id: str) -> Dict[str, Any] | None:
        with self._cursor() as cur:
            row = self._get_conversation_row(cur, user_id, conversation_id)
            if row is None:
                return None
            payload = {
                "id": row["id"],
                "thread_id": row["thread_id"],
            }
            cur.execute("DELETE FROM conversations WHERE id = ? AND user_id = ?", (conversation_id, user_id))
            return payload

    def delete_all_conversations(self, user_id: str) -> Dict[str, int]:
        summary = self.get_user_data_summary(user_id)
        with self._cursor() as cur:
            cur.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
        return summary

    def update_feedback(self, user_id: str, conversation_id: str, message_id: str, feedback: str | None) -> bool:
        with self._cursor() as cur:
            row = self._get_conversation_row(cur, user_id, conversation_id)
            if row is None:
                return False
            cur.execute(
                "UPDATE messages SET feedback = ? WHERE id = ? AND conversation_id = ?",
                (feedback, message_id, conversation_id),
            )
            if cur.rowcount == 0:
                return False
            cur.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ? AND user_id = ?",
                (now_iso(), conversation_id, user_id),
            )
            return True

    def update_message_parts(self, user_id: str, conversation_id: str, message_id: str, parts: List[Dict[str, Any]]) -> bool:
        with self._cursor() as cur:
            row = self._get_conversation_row(cur, user_id, conversation_id)
            if row is None:
                return False
            cur.execute(
                """
                UPDATE messages
                SET parts = ?
                WHERE id = ? AND conversation_id = ?
                """,
                (json.dumps(parts, ensure_ascii=False), message_id, conversation_id),
            )
            return cur.rowcount > 0

    def truncate_after_user_message(
        self,
        user_id: str,
        conversation_id: str,
        message_id: str,
        *,
        content: str | None = None,
        model: str | None = None,
        updated_at: str,
    ) -> Dict[str, Any] | None:
        with self._cursor() as cur:
            row = self._get_conversation_row(cur, user_id, conversation_id)
            if row is None:
                return None
            cur.execute(
                """
                SELECT id, position, role, content
                FROM messages
                WHERE id = ? AND conversation_id = ?
                """,
                (message_id, conversation_id),
            )
            message_row = cur.fetchone()
            if message_row is None or message_row["role"] != "user":
                return None

            if content is not None:
                cur.execute(
                    """
                    UPDATE messages
                    SET content = ?, parts = ?, timestamp = ?, feedback = NULL
                    WHERE id = ? AND conversation_id = ?
                    """,
                    (
                        content,
                        json.dumps([{"type": "text", "content": content}], ensure_ascii=False),
                        updated_at,
                        message_id,
                        conversation_id,
                    ),
                )

            cur.execute(
                """
                DELETE FROM messages
                WHERE conversation_id = ? AND position > ?
                """,
                (conversation_id, int(message_row["position"])),
            )
            cur.execute(
                """
                UPDATE conversations
                SET model = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (model or row["model"], updated_at, conversation_id, user_id),
            )
            row = self._get_conversation_row(cur, user_id, conversation_id)
            return self._conversation_from_row(cur, row)

    def append_message(self, user_id: str, conversation_id: str, message: Dict[str, Any], *, model: str | None = None) -> Dict[str, Any] | None:
        with self._cursor() as cur:
            row = self._get_conversation_row(cur, user_id, conversation_id)
            if row is None:
                return None
            cur.execute(
                "UPDATE conversations SET model = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                (model or row["model"], message["timestamp"], conversation_id, user_id),
            )
            self._insert_message(cur, conversation_id, message)
            row = self._get_conversation_row(cur, user_id, conversation_id)
            return self._conversation_from_row(cur, row)


chat_store = ChatStore(CHAT_DB_PATH)
