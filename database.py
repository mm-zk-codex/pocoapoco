import logging
import re
from datetime import datetime, timedelta

import aiosqlite

from config import DATABASE_PATH

logger = logging.getLogger(__name__)

CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    language_level TEXT DEFAULT 'A1',
    spanish_ratio REAL DEFAULT 0.15,
    interests TEXT DEFAULT '[]',
    daily_time TEXT DEFAULT '08:00',
    timezone TEXT DEFAULT 'UTC',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_active TIMESTAMP
);
"""

CREATE_CONVERSATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER,
    role TEXT,
    content TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
);
"""


async def init_db():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(CREATE_USERS_TABLE)
        await db.execute(CREATE_CONVERSATIONS_TABLE)
        await db.commit()
    logger.info("Database initialized")


async def get_user(telegram_id: int) -> dict | None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def create_user(telegram_id: int, username: str | None, first_name: str | None):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """INSERT OR IGNORE INTO users (telegram_id, username, first_name, last_active)
               VALUES (?, ?, ?, ?)""",
            (telegram_id, username, first_name, datetime.now().isoformat()),
        )
        await db.commit()
    logger.info(f"Created user {telegram_id}")


async def update_user_interests(telegram_id: int, interests_json: str):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE users SET interests = ? WHERE telegram_id = ?",
            (interests_json, telegram_id),
        )
        await db.commit()


async def update_user_daily_time(telegram_id: int, daily_time: str):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE users SET daily_time = ? WHERE telegram_id = ?",
            (daily_time, telegram_id),
        )
        await db.commit()


async def get_conversation_history(telegram_id: int, limit: int = 10) -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT role, content, created_at FROM conversations
               WHERE telegram_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (telegram_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in reversed(rows)]


async def add_message(telegram_id: int, role: str, content: str):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO conversations (telegram_id, role, content) VALUES (?, ?, ?)",
            (telegram_id, role, content),
        )
        await db.commit()


async def cleanup_old_messages(days: int = 90):
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "DELETE FROM conversations WHERE created_at < ?", (cutoff,)
        )
        await db.commit()
    logger.info(f"Cleaned up messages older than {days} days")


async def get_users_for_time(current_time: str) -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE daily_time = ?", (current_time,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def update_last_active(telegram_id: int):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE users SET last_active = ? WHERE telegram_id = ?",
            (datetime.now().isoformat(), telegram_id),
        )
        await db.commit()


_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_TOKEN_STRIP_RE = re.compile(r"[^\w']", re.UNICODE)


def _extract_spanish_words(texts: list[str]) -> set[str]:
    words: set[str] = set()
    for text in texts:
        if not text:
            continue
        for match in _BOLD_RE.findall(text):
            for token in match.split():
                cleaned = _TOKEN_STRIP_RE.sub("", token).lower()
                if len(cleaned) >= 2:
                    words.add(cleaned)
    return words


async def get_user_stats(telegram_id: int) -> dict:
    """Compute progress stats for a user from stored conversations."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM conversations WHERE telegram_id = ? AND role = 'user'",
            (telegram_id,),
        ) as cur:
            (total_user_messages,) = await cur.fetchone()

        async with db.execute(
            "SELECT MIN(created_at) FROM conversations WHERE telegram_id = ?",
            (telegram_id,),
        ) as cur:
            (first_seen,) = await cur.fetchone()

        async with db.execute(
            """SELECT DISTINCT DATE(created_at) FROM conversations
               WHERE telegram_id = ? AND role = 'user'
               ORDER BY DATE(created_at) DESC""",
            (telegram_id,),
        ) as cur:
            day_rows = [r[0] for r in await cur.fetchall()]

        async with db.execute(
            "SELECT content FROM conversations WHERE telegram_id = ? AND role = 'assistant'",
            (telegram_id,),
        ) as cur:
            bot_texts = [r[0] for r in await cur.fetchall()]

    days_chatting = 0
    if first_seen:
        try:
            first_dt = datetime.fromisoformat(first_seen)
            days_chatting = max(1, (datetime.now() - first_dt).days + 1)
        except ValueError:
            days_chatting = 0

    streak = 0
    if day_rows:
        today = datetime.now().date()
        try:
            dates = [datetime.strptime(d, "%Y-%m-%d").date() for d in day_rows]
        except ValueError:
            dates = []
        if dates and dates[0] in (today, today - timedelta(days=1)):
            streak = 1
            for prev, curr in zip(dates, dates[1:]):
                if prev - curr == timedelta(days=1):
                    streak += 1
                else:
                    break

    spanish_words = _extract_spanish_words(bot_texts)

    return {
        "total_user_messages": total_user_messages,
        "days_chatting": days_chatting,
        "active_days": len(day_rows),
        "streak": streak,
        "spanish_words_seen": len(spanish_words),
    }
