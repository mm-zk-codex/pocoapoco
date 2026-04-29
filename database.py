import logging
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
        # Keep only the last 10 messages per user
        await db.execute(
            """DELETE FROM conversations
               WHERE telegram_id = ? AND id NOT IN (
                   SELECT id FROM conversations
                   WHERE telegram_id = ?
                   ORDER BY created_at DESC
                   LIMIT 10
               )""",
            (telegram_id, telegram_id),
        )
        await db.commit()


async def cleanup_old_messages(days: int = 7):
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
