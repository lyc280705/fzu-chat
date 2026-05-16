from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from threading import RLock
from typing import Any, Dict, Iterator, List, Set
import unicodedata
from uuid import uuid4

from .security_utils import ensure_private_dir, ensure_private_file

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "storage"
MEMORY_DB_PATH = STORAGE_DIR / "user_memory.sqlite"
MEMORY_SELECT_COLUMNS = """
    id, user_id, category, content, reason, source, is_active,
    created_at, updated_at, normalized_content, keywords,
    importance, access_count, last_accessed_at
"""
MAX_SEARCH_CANDIDATES = 300

WORD_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{1,}", re.I)
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]{2,}")
NEGATIVE_PREFERENCE_RE = re.compile(r"(不喜欢|不吃|不喝|讨厌|不要|别|避免|避开|错开|禁忌|过敏)")
POSITIVE_PREFERENCE_RE = re.compile(r"(?<!不)(喜欢|爱吃|爱喝|偏好|习惯)")
GENERIC_MEMORY_TOKENS = {
    "用户",
    "偏好",
    "习惯",
    "喜欢",
    "不喜",
    "不喜欢",
    "不吃",
    "不喝",
    "希望",
    "默认",
    "输出",
    "回答",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clamp_int(value: Any, default: int, lower: int, upper: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(lower, min(number, upper))


def normalize_memory_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    chars: List[str] = []
    for char in text:
        category = unicodedata.category(char)
        if category[0] in {"P", "S", "Z"} or char.isspace():
            continue
        chars.append(char)
    return "".join(chars)


def tokenize_memory_text(value: Any, limit: int = 80) -> List[str]:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    tokens: List[str] = []

    for match in WORD_RE.finditer(text):
        token = match.group(0).strip("._-")
        if len(token) >= 2:
            tokens.append(token[:40])

    for chunk in CJK_RE.findall(text):
        if 2 <= len(chunk) <= 12:
            tokens.append(chunk)
        for size in (2, 3):
            if len(chunk) < size:
                continue
            for index in range(0, len(chunk) - size + 1):
                tokens.append(chunk[index : index + size])

    seen: Set[str] = set()
    unique_tokens: List[str] = []
    for token in tokens:
        token = normalize_memory_text(token)
        if len(token) < 2 or token in seen:
            continue
        seen.add(token)
        unique_tokens.append(token)
        if len(unique_tokens) >= limit:
            break
    return unique_tokens


def extract_memory_keywords(content: str, category: str = "", reason: str = "", limit: int = 24) -> List[str]:
    weighted: List[str] = []
    weighted.extend(tokenize_memory_text(category, limit=20))
    weighted.extend(tokenize_memory_text(content, limit=80))
    weighted.extend(tokenize_memory_text(reason, limit=40))

    seen: Set[str] = set()
    keywords: List[str] = []
    for token in weighted:
        if token in seen:
            continue
        seen.add(token)
        keywords.append(token)
        if len(keywords) >= limit:
            break
    return keywords


def memory_similarity(left: str, right: str) -> float:
    left_norm = normalize_memory_text(left)
    right_norm = normalize_memory_text(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    if left_norm in right_norm or right_norm in left_norm:
        coverage = min(len(left_norm), len(right_norm)) / max(len(left_norm), len(right_norm))
        return max(0.72, min(0.95, 0.72 + 0.23 * coverage))

    left_tokens = set(tokenize_memory_text(left))
    right_tokens = set(tokenize_memory_text(right))
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens)
    if overlap == 0:
        return 0.0
    jaccard = overlap / len(left_tokens | right_tokens)
    dice = (2 * overlap) / (len(left_tokens) + len(right_tokens))
    score = max(jaccard, dice * 0.82)

    meaningful_overlap = {
        token
        for token in left_tokens & right_tokens
        if token not in GENERIC_MEMORY_TOKENS and not token.startswith("用户") and len(token) >= 2
    }
    left_polarity = preference_polarity(left_norm)
    right_polarity = preference_polarity(right_norm)
    if meaningful_overlap and left_polarity and left_polarity == right_polarity:
        score = max(score, 0.74)
    return score


def preference_polarity(value: str) -> int:
    if NEGATIVE_PREFERENCE_RE.search(value):
        return -1
    if POSITIVE_PREFERENCE_RE.search(value):
        return 1
    return 0


def encode_keywords(keywords: List[str]) -> str:
    return json.dumps(keywords, ensure_ascii=False, separators=(",", ":"))


def decode_keywords(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def recency_bonus(value: Any) -> float:
    try:
        updated_at = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return 0.0
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    age_days = max((datetime.now(timezone.utc) - updated_at).total_seconds() / 86400, 0)
    if age_days <= 1:
        return 8.0
    if age_days <= 7:
        return 6.0
    if age_days <= 30:
        return 3.0
    if age_days <= 120:
        return 1.0
    return 0.0


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
                    updated_at TEXT NOT NULL,
                    normalized_content TEXT NOT NULL DEFAULT '',
                    keywords TEXT NOT NULL DEFAULT '[]',
                    importance INTEGER NOT NULL DEFAULT 50,
                    access_count INTEGER NOT NULL DEFAULT 0,
                    last_accessed_at TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_user_memories_user_updated
                ON user_memories (user_id, updated_at DESC);

                CREATE INDEX IF NOT EXISTS idx_user_memories_user_category
                ON user_memories (user_id, category);
                """
            )
            self._migrate_schema_locked()
            self.conn.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_user_memories_user_active_score
                ON user_memories (user_id, is_active, importance DESC, updated_at DESC);

                CREATE INDEX IF NOT EXISTS idx_user_memories_user_normalized
                ON user_memories (user_id, normalized_content);
                """
            )
            self.conn.commit()
            self._harden_storage_files()

    def _migrate_schema_locked(self) -> None:
        columns = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(user_memories)").fetchall()
        }
        migrations = {
            "normalized_content": "ALTER TABLE user_memories ADD COLUMN normalized_content TEXT NOT NULL DEFAULT ''",
            "keywords": "ALTER TABLE user_memories ADD COLUMN keywords TEXT NOT NULL DEFAULT '[]'",
            "importance": "ALTER TABLE user_memories ADD COLUMN importance INTEGER NOT NULL DEFAULT 50",
            "access_count": "ALTER TABLE user_memories ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0",
            "last_accessed_at": "ALTER TABLE user_memories ADD COLUMN last_accessed_at TEXT NOT NULL DEFAULT ''",
        }
        for column, statement in migrations.items():
            if column not in columns:
                self.conn.execute(statement)

        rows = self.conn.execute(
            """
            SELECT id, category, content, reason, normalized_content, keywords, importance
            FROM user_memories
            WHERE normalized_content = '' OR keywords = '' OR keywords = '[]' OR importance < 1 OR importance > 100
            """
        ).fetchall()
        for row in rows:
            category = str(row["category"] or "").strip()
            content = str(row["content"] or "").strip()
            reason = str(row["reason"] or "").strip()
            self.conn.execute(
                """
                UPDATE user_memories
                SET normalized_content = ?, keywords = ?, importance = ?
                WHERE id = ?
                """,
                (
                    normalize_memory_text(content),
                    encode_keywords(extract_memory_keywords(content, category, reason)),
                    clamp_int(row["importance"], 50, 1, 100),
                    row["id"],
                ),
            )

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
            "normalized_content": row["normalized_content"],
            "keywords": decode_keywords(row["keywords"]),
            "importance": int(row["importance"] or 50),
            "access_count": int(row["access_count"] or 0),
            "last_accessed_at": row["last_accessed_at"],
        }

    def _fetch_memory_by_id(
        self,
        cur: sqlite3.Cursor,
        user_id: str,
        memory_id: str,
        *,
        include_inactive: bool = False,
    ) -> Dict[str, Any] | None:
        active_clause = "" if include_inactive else " AND is_active = 1"
        cur.execute(
            f"""
            SELECT {MEMORY_SELECT_COLUMNS}
            FROM user_memories
            WHERE user_id = ? AND id = ?{active_clause}
            LIMIT 1
            """,
            [user_id, memory_id],
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
            SELECT {MEMORY_SELECT_COLUMNS}
            FROM user_memories
            WHERE user_id = ? AND id IN ({placeholders}){active_clause}
            """,
            [user_id, *normalized_ids],
        )
        rows = {row["id"]: self._row_to_memory(row) for row in cur.fetchall()}
        return [rows[memory_id] for memory_id in normalized_ids if memory_id in rows]

    def _record_memory_access(self, cur: sqlite3.Cursor, user_id: str, memory_ids: List[str]) -> None:
        normalized_ids = [memory_id for memory_id in dict.fromkeys(memory_ids) if memory_id]
        if not normalized_ids:
            return
        placeholders = ",".join("?" for _ in normalized_ids)
        cur.execute(
            f"""
            UPDATE user_memories
            SET access_count = access_count + 1, last_accessed_at = ?
            WHERE user_id = ? AND id IN ({placeholders}) AND is_active = 1
            """,
            [now_iso(), user_id, *normalized_ids],
        )

    def _score_memory(self, memory: Dict[str, Any], query: str, category: str) -> float:
        score = 0.0
        query_norm = normalize_memory_text(query)
        category_norm = normalize_memory_text(category)
        content_norm = str(memory.get("normalized_content") or normalize_memory_text(memory.get("content")))
        memory_category_norm = normalize_memory_text(memory.get("category"))
        reason_norm = normalize_memory_text(memory.get("reason"))

        if category_norm:
            if category_norm == memory_category_norm:
                score += 28.0
            elif category_norm in memory_category_norm:
                score += 14.0
            else:
                score -= 12.0

        if query_norm:
            if query_norm == content_norm:
                score += 100.0
            elif query_norm in content_norm:
                score += 62.0
            elif content_norm and content_norm in query_norm:
                score += 40.0
            elif query_norm in memory_category_norm:
                score += 18.0
            elif query_norm in reason_norm:
                score += 8.0

            query_tokens = set(tokenize_memory_text(query))
            if query_tokens:
                memory_tokens = set(memory.get("keywords") or [])
                memory_tokens.update(tokenize_memory_text(memory.get("content")))
                memory_tokens.update(tokenize_memory_text(memory.get("category")))
                memory_tokens.update(tokenize_memory_text(memory.get("reason")))
                overlap = query_tokens & memory_tokens
                if overlap:
                    score += 52.0 * len(overlap) / len(query_tokens)
                keyword_overlap = query_tokens & set(memory.get("keywords") or [])
                if keyword_overlap:
                    score += 18.0 * len(keyword_overlap) / len(query_tokens)
        else:
            score += 18.0

        score += clamp_int(memory.get("importance"), 50, 1, 100) * 0.14
        score += min(int(memory.get("access_count") or 0), 20) * 0.35
        score += recency_bonus(memory.get("updated_at"))
        return score

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

        normalized_match = normalize_memory_text(normalized_content)
        with self._cursor() as cur:
            params: List[Any] = [user_id, normalized_content, normalized_match]
            category_clause = ""
            if category is not None:
                category_clause = " AND category = ?"
                params.append(str(category))
            active_clause = "" if include_inactive else " AND is_active = 1"
            cur.execute(
                f"""
                SELECT {MEMORY_SELECT_COLUMNS}
                FROM user_memories
                WHERE user_id = ? AND (content = ? OR normalized_content = ?){category_clause}{active_clause}
                ORDER BY updated_at DESC
                """,
                params,
            )
            return [self._row_to_memory(row) for row in cur.fetchall()]

    def find_exact_memory(self, user_id: str, content: str, category: str = "") -> Dict[str, Any] | None:
        memories = self.find_memories_by_content(user_id, content, category=category, include_inactive=False)
        return memories[0] if memories else None

    def find_similar_memory(
        self,
        user_id: str,
        content: str,
        category: str = "",
        *,
        threshold: float = 0.72,
        include_inactive: bool = False,
    ) -> Dict[str, Any] | None:
        normalized_content = str(content or "").strip()
        if not normalized_content:
            return None

        active_clause = "" if include_inactive else " AND is_active = 1"
        with self._cursor() as cur:
            cur.execute(
                f"""
                SELECT {MEMORY_SELECT_COLUMNS}
                FROM user_memories
                WHERE user_id = ?{active_clause}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (user_id, MAX_SEARCH_CANDIDATES),
            )
            candidates = [self._row_to_memory(row) for row in cur.fetchall()]

        best: Dict[str, Any] | None = None
        best_score = 0.0
        category_norm = normalize_memory_text(category)
        for memory in candidates:
            if memory is None:
                continue
            similarity = memory_similarity(normalized_content, str(memory.get("content") or ""))
            memory_category_norm = normalize_memory_text(memory.get("category"))
            if category_norm and memory_category_norm:
                if category_norm == memory_category_norm:
                    similarity += 0.05
                else:
                    similarity -= 0.08
            if similarity > best_score:
                best_score = similarity
                best = memory

        if best is None or best_score < threshold:
            return None
        best["similarity"] = round(min(best_score, 1.0), 4)
        return best

    def search_memories(
        self,
        user_id: str,
        query: str = "",
        limit: int = 5,
        category: str = "",
    ) -> List[Dict[str, Any]]:
        normalized_query = str(query or "").strip()
        normalized_category = str(category or "").strip()
        safe_limit = max(1, min(int(limit), 50))

        with self._cursor() as cur:
            if not normalized_query and not normalized_category:
                cur.execute(
                    f"""
                    SELECT {MEMORY_SELECT_COLUMNS}
                    FROM user_memories
                    WHERE user_id = ? AND is_active = 1
                    ORDER BY importance DESC,
                             COALESCE(NULLIF(last_accessed_at, ''), updated_at) DESC,
                             updated_at DESC
                    LIMIT ?
                    """,
                    (user_id, safe_limit),
                )
                memories = [self._row_to_memory(row) for row in cur.fetchall()]
                items = [memory for memory in memories if memory is not None]
                self._record_memory_access(cur, user_id, [item["id"] for item in items])
                return items

            params: List[Any] = [user_id]
            category_clause = ""
            if normalized_category:
                category_clause = " AND category = ?"
                params.append(normalized_category)
            params.append(MAX_SEARCH_CANDIDATES)
            cur.execute(
                f"""
                SELECT {MEMORY_SELECT_COLUMNS}
                FROM user_memories
                WHERE user_id = ? AND is_active = 1{category_clause}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                params,
            )
            candidates = [self._row_to_memory(row) for row in cur.fetchall()]
            scored: List[Dict[str, Any]] = []
            for memory in candidates:
                if memory is None:
                    continue
                score = self._score_memory(memory, normalized_query, normalized_category)
                if score < 12 and normalized_query:
                    continue
                memory["score"] = round(score, 2)
                scored.append(memory)

            scored.sort(key=lambda item: (item.get("score", 0), item.get("updated_at") or ""), reverse=True)
            items = scored[:safe_limit]
            self._record_memory_access(cur, user_id, [item["id"] for item in items])
            return items

    def get_context_memories(self, user_id: str, limit: int = 8) -> List[Dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 20))
        with self._cursor() as cur:
            cur.execute(
                f"""
                SELECT {MEMORY_SELECT_COLUMNS}
                FROM user_memories
                WHERE user_id = ? AND is_active = 1
                ORDER BY importance DESC,
                         COALESCE(NULLIF(last_accessed_at, ''), updated_at) DESC,
                         updated_at DESC
                LIMIT ?
                """,
                (user_id, safe_limit),
            )
            return [memory for memory in (self._row_to_memory(row) for row in cur.fetchall()) if memory is not None]

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
        importance: int = 50,
    ) -> Dict[str, Any]:
        normalized_content = str(content or "").strip()[:300]
        normalized_category = str(category or "").strip()[:40]
        normalized_reason = str(reason or "").strip()[:200]
        normalized_match = normalize_memory_text(normalized_content)
        safe_importance = clamp_int(importance, 50, 1, 100)
        timestamp = now_iso()

        existing = self.find_similar_memory(
            user_id,
            normalized_content,
            normalized_category,
            threshold=0.72,
            include_inactive=True,
        )
        if existing is not None:
            next_category = existing.get("category") or normalized_category
            next_content = existing.get("content") or normalized_content
            next_reason = existing.get("reason") or normalized_reason
            next_importance = max(clamp_int(existing.get("importance"), 50, 1, 100), safe_importance)
            next_keywords = encode_keywords(extract_memory_keywords(next_content, next_category, next_reason))
            with self._cursor() as cur:
                cur.execute(
                    """
                    UPDATE user_memories
                    SET category = ?,
                        content = ?,
                        reason = ?,
                        normalized_content = ?,
                        keywords = ?,
                        importance = ?,
                        source = ?,
                        is_active = 1,
                        updated_at = ?
                    WHERE user_id = ? AND id = ?
                    """,
                    (
                        next_category,
                        next_content,
                        next_reason,
                        normalize_memory_text(next_content),
                        next_keywords,
                        next_importance,
                        source or existing.get("source") or "assistant",
                        timestamp,
                        user_id,
                        existing["id"],
                    ),
                )
                cur.execute(
                    f"""
                    SELECT {MEMORY_SELECT_COLUMNS}
                    FROM user_memories
                    WHERE id = ?
                    """,
                    (existing["id"],),
                )
                row = cur.fetchone()
            payload = self._row_to_memory(row) or existing
            payload["duplicate"] = True
            payload["reactivated"] = not bool(existing.get("is_active"))
            payload["duplicate_similarity"] = existing.get("similarity", 1.0)
            return payload

        memory_id = str(uuid4())
        keywords = encode_keywords(extract_memory_keywords(normalized_content, normalized_category, normalized_reason))
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_memories (
                    id, user_id, category, content, reason, source, is_active,
                    created_at, updated_at, normalized_content, keywords, importance
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
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
                    normalized_match,
                    keywords,
                    safe_importance,
                ),
            )
            cur.execute(
                f"""
                SELECT {MEMORY_SELECT_COLUMNS}
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
