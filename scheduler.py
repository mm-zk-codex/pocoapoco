import json
import logging
import random
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from conversation import build_system_prompt, call_llm, format_for_telegram
from database import add_message, cleanup_old_messages, get_users_for_time
from topics import TOPICS

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def send_daily_messages(app) -> None:
    current_time = datetime.now().strftime("%H:%M")
    users = await get_users_for_time(current_time)

    if not users:
        return

    logger.info(f"Sending daily messages to {len(users)} users at {current_time}")

    for user in users:
        try:
            await _send_to_user(app, user)
        except Exception as e:
            logger.error(f"Failed to send daily message to {user['telegram_id']}: {e}")


async def _send_to_user(app, user: dict) -> None:
    telegram_id = user["telegram_id"]
    interests = json.loads(user.get("interests", "[]"))

    if not interests:
        interests = list(TOPICS.keys())

    topic_category = random.choice(interests)
    topic = random.choice(TOPICS.get(topic_category, ["everyday life"]))

    system_prompt = build_system_prompt(
        spanish_ratio=int(user.get("spanish_ratio", 0.15) * 100),
        language_level=user.get("language_level", "A1"),
        topic=topic,
        interests=interests,
        message_number=1,
    )

    opening = await call_llm(system_prompt, [])
    await add_message(telegram_id, "assistant", opening)
    await app.bot.send_message(
        chat_id=telegram_id,
        text=format_for_telegram(opening),
        parse_mode="HTML",
    )
    logger.info(f"Sent daily message to {telegram_id}: topic={topic_category}/{topic}")


async def _daily_cleanup() -> None:
    await cleanup_old_messages(days=90)


def setup_scheduler(app) -> None:
    scheduler.add_job(
        send_daily_messages,
        "cron",
        minute="*",
        args=[app],
        id="daily_messages",
        replace_existing=True,
    )
    scheduler.add_job(
        _daily_cleanup,
        "cron",
        hour=0,
        minute=0,
        id="daily_cleanup",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started")
