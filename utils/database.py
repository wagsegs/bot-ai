import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "conversations.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def save_message(user_id: str, channel_id: str, role: str, content: str) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT INTO conversations (user_id, channel_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, channel_id, role, content, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def get_recent_context(user_id: str, channel_id: str, limit: int = 8) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT role, content, created_at
        FROM conversations
        WHERE user_id = ? AND channel_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_id, channel_id, limit),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows][::-1]


def get_recent_channel_context(channel_id: str, limit: int = 60) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT user_id, role, content, created_at
        FROM conversations
        WHERE channel_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (channel_id, limit),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows][::-1]


def clear_all_conversations() -> None:
    conn = get_connection()
    conn.execute("DELETE FROM conversations")
    conn.commit()
    conn.close()


def prune_old_conversations(expire_minutes: int = 30) -> None:
    cutoff = datetime.utcnow() - timedelta(minutes=expire_minutes)
    conn = get_connection()
    conn.execute(
        "DELETE FROM conversations WHERE created_at < ?",
        (cutoff.isoformat(),),
    )
    conn.commit()
    conn.close()
