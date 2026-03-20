import sqlite3
from pathlib import Path
from typing import Callable


class ConversationMemoryStore:
    def __init__(
        self,
        db_path: str,
        recent_turns: int = 4,
        summary_max_chars: int = 3000,
        item_max_chars: int = 220,
        llm_summarizer: Callable[[str, list[tuple[int, str, str]], int], str] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.recent_turns = recent_turns
        self.summary_max_chars = summary_max_chars
        self.item_max_chars = item_max_chars
        self.llm_summarizer = llm_summarizer

    def init_db(self) -> None:
        with self._db() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS summaries (
                    session_id TEXT PRIMARY KEY,
                    summary TEXT NOT NULL DEFAULT '',
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id, id)"
            )

    def compact_session_history(self, session_id: str) -> None:
        messages = self._fetch_messages(session_id)
        keep_count = max(2, self.recent_turns * 2)
        if len(messages) <= keep_count:
            return

        old_items = messages[:-keep_count]
        recent_items = messages[-keep_count:]
        old_summary = self._fetch_summary(session_id)
        merged_summary = ""

        if self.llm_summarizer:
            merged_summary = self.llm_summarizer(old_summary, old_items, self.summary_max_chars).strip()

        if not merged_summary:
            chunk = self._summarize_messages(old_items)
            if chunk:
                merged_summary = self._merge_summary(old_summary, chunk)

        if merged_summary:
            self._upsert_summary(session_id, merged_summary)

        min_keep_id = recent_items[0][0]
        with self._db() as conn:
            conn.execute(
                "DELETE FROM messages WHERE session_id = ? AND id < ?",
                (session_id, min_keep_id),
            )

    def build_input_messages(self, session_id: str, latest_user_message: str) -> list[dict[str, str]]:
        payload: list[dict[str, str]] = []
        summary = self._fetch_summary(session_id)
        if summary:
            payload.append(
                {
                    "role": "system",
                    "content": (
                        "以下为该用户较早对话摘要，仅用于保持上下文连续性；"
                        "若与用户当前新指令冲突，请以当前新指令为准。\n"
                        f"{summary}"
                    ),
                }
            )

        for _, role, content in self._fetch_messages(session_id):
            payload.append({"role": role, "content": content})

        payload.append({"role": "user", "content": latest_user_message})
        return payload

    def append_turn(self, session_id: str, user_message: str, assistant_reply: str) -> None:
        with self._db() as conn:
            conn.execute(
                "INSERT INTO messages(session_id, role, content) VALUES (?, ?, ?)",
                (session_id, "user", user_message),
            )
            conn.execute(
                "INSERT INTO messages(session_id, role, content) VALUES (?, ?, ?)",
                (session_id, "assistant", assistant_reply),
            )

    def _db(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def _normalize_text(self, text: str) -> str:
        cleaned = " ".join((text or "").split())
        if len(cleaned) <= self.item_max_chars:
            return cleaned
        return cleaned[: self.item_max_chars - 1].rstrip() + "…"

    def _fetch_messages(self, session_id: str) -> list[tuple[int, str, str]]:
        with self._db() as conn:
            rows = conn.execute(
                "SELECT id, role, content FROM messages WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        return [(int(row[0]), str(row[1]), str(row[2])) for row in rows]

    def _fetch_summary(self, session_id: str) -> str:
        with self._db() as conn:
            row = conn.execute(
                "SELECT summary FROM summaries WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return str(row[0]) if row and row[0] else ""

    def _upsert_summary(self, session_id: str, summary: str) -> None:
        with self._db() as conn:
            conn.execute(
                """
                INSERT INTO summaries(session_id, summary, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(session_id) DO UPDATE
                SET summary = excluded.summary, updated_at = CURRENT_TIMESTAMP
                """,
                (session_id, summary),
            )

    def _merge_summary(self, old_summary: str, new_chunk: str) -> str:
        combined = f"{old_summary}\n{new_chunk}".strip() if old_summary else new_chunk
        if len(combined) <= self.summary_max_chars:
            return combined
        return combined[-self.summary_max_chars :]

    def _summarize_messages(self, items: list[tuple[int, str, str]]) -> str:
        lines: list[str] = []
        for _, role, content in items:
            label = "用户" if role == "user" else "助手"
            lines.append(f"- {label}：{self._normalize_text(content)}")
        body = "\n".join(lines).strip()
        if not body:
            return ""
        return f"历史对话要点：\n{body}"
