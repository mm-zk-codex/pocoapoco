import asyncio
import json
import logging
import random
import signal
from collections import defaultdict, deque
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import INVITE_CODE, LOG_LEVEL, TELEGRAM_BOT_TOKEN
from conversation import (
    build_system_prompt,
    call_llm,
    format_for_telegram,
    get_session_message_count,
    is_new_session,
)
from database import (
    add_message,
    create_user,
    get_conversation_history,
    get_user,
    get_user_stats,
    init_db,
    set_user_premium,
    update_last_active,
    update_user_daily_time,
    update_user_interests,
)
from scheduler import setup_scheduler
from topics import TOPICS

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Rate limiting: per-user deque of message timestamps
_rate_limits: dict[int, deque] = defaultdict(deque)
RATE_LIMIT_MAX = 20
RATE_LIMIT_WINDOW = 3600  # seconds

WELCOME_MESSAGE = (
    "Hey! 👋 I'm PocoAPoco — I help you learn Spanish **poco a poco** (little by little) "
    "through conversation.\n\n"
    "Let me show you how it works. Here's a fun one:\n\n"
    "Did you know that **el café** is one of the most popular drinks in **el mundo**? "
    "People in Colombia grow some of the **mejor** coffee on the planet. "
    "**¿Te gusta el café**, or are you more of a tea person?"
)

INTERESTS = [
    ("⚽ Sports", "Sports"),
    ("💻 Tech", "Tech"),
    ("🎬 Movies & TV", "Movies & TV"),
    ("🍳 Food & Cooking", "Food & Cooking"),
    ("✈️ Travel", "Travel"),
    ("🔬 Science", "Science"),
    ("🎵 Music", "Music"),
    ("📰 News", "News & Current Events"),
]
_VALID_INTERESTS = {value for _, value in INTERESTS}

TIMES = [
    ("🌅 Morning (8:00)", "08:00"),
    ("☀️ Midday (12:00)", "12:00"),
    ("🌆 Evening (18:00)", "18:00"),
    ("🌙 Night (21:00)", "21:00"),
]
_VALID_TIMES = {value for _, value in TIMES}

# Each entry: (emoji, name, one-line description)
PREMIUM_FEATURES = [
    ("📰", "News fetching", "daily topics pulled from real news instead of a curated list"),
    ("📚", "Vocabulary tracking", "every Spanish word you encounter is saved to your personal list"),
    ("🔁", "Spaced repetition", "get quizzed on your vocab at just the right time"),
]


def _check_rate_limit(user_id: int) -> bool:
    now = datetime.now().timestamp()
    times = _rate_limits[user_id]
    while times and times[0] < now - RATE_LIMIT_WINDOW:
        times.popleft()
    if len(times) >= RATE_LIMIT_MAX:
        return False
    times.append(now)
    return True


def _interests_keyboard(selected: list[str]) -> InlineKeyboardMarkup:
    rows = []
    row: list[InlineKeyboardButton] = []
    for label, value in INTERESTS:
        prefix = "✅ " if value in selected else ""
        row.append(InlineKeyboardButton(f"{prefix}{label}", callback_data=f"interest:{value}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("Done ✓", callback_data="interests_done")])
    return InlineKeyboardMarkup(rows)


def _time_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(label, callback_data=f"time:{value}")] for label, value in TIMES]
    )


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tg_user = update.effective_user
    telegram_id = tg_user.id

    db_user = await get_user(telegram_id)

    if db_user is None:
        provided = context.args[0] if context.args else None
        if not INVITE_CODE or provided != INVITE_CODE:
            logger.info(f"Rejected /start from {telegram_id} (invite code mismatch)")
            await update.message.reply_text(
                "This bot is invite-only. Tap your invite link, or send "
                "<code>/start your-invite-code</code> to join.",
                parse_mode="HTML",
            )
            return
        await create_user(telegram_id, tg_user.username, tg_user.first_name)
        await add_message(telegram_id, "assistant", WELCOME_MESSAGE)
        context.user_data["session_exchange_count"] = 0
        context.user_data.pop("setup_shown", None)
        await update.message.reply_text(
            format_for_telegram(WELCOME_MESSAGE), parse_mode="HTML"
        )
    else:
        await update_last_active(telegram_id)
        context.user_data["session_exchange_count"] = 0
        context.user_data.pop("setup_shown", None)
        name = db_user.get("first_name") or "amigo"
        greeting = (
            f"¡Hola, {name}! Welcome back! Ready for another <b>conversación</b>? "
            "What's been on your mind lately? 😊"
        )
        await add_message(telegram_id, "assistant", greeting)
        await update.message.reply_text(greeting, parse_mode="HTML")


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tg_user = update.effective_user
    telegram_id = tg_user.id
    user_text = update.message.text

    if not _check_rate_limit(telegram_id):
        await update.message.reply_text(
            "You're on fire! 🔥 But let's take a quick <b>descanso</b> (break). "
            "I'll be ready to chat again soon!",
            parse_mode="HTML",
        )
        return

    db_user = await get_user(telegram_id)
    if db_user is None:
        await update.message.reply_text(
            "You'll need an invite to chat. Send "
            "<code>/start your-invite-code</code> to join.",
            parse_mode="HTML",
        )
        return

    await update_last_active(telegram_id)
    await add_message(telegram_id, "user", user_text)

    history = await get_conversation_history(telegram_id)

    # Reset session state when conversation is new
    new_session = is_new_session(history[:-1])  # exclude the message we just added
    if new_session or "session_topic" not in context.user_data:
        interests = json.loads(db_user.get("interests", "[]"))
        if interests:
            cat = random.choice(interests)
            topic = random.choice(TOPICS.get(cat, ["everyday life"]))
        else:
            topic = "everyday life and getting to know each other"
        context.user_data["session_topic"] = topic
        context.user_data["session_exchange_count"] = 0

    context.user_data["session_exchange_count"] = (
        context.user_data.get("session_exchange_count", 0) + 1
    )
    exchange_count = context.user_data["session_exchange_count"]
    topic = context.user_data["session_topic"]

    interests = json.loads(db_user.get("interests", "[]"))
    system_prompt = build_system_prompt(
        spanish_ratio=int(db_user.get("spanish_ratio", 0.15) * 100),
        language_level=db_user.get("language_level", "A1"),
        topic=topic,
        interests=interests,
        message_number=exchange_count,
    )

    try:
        response = await call_llm(system_prompt, history)
    except Exception as e:
        logger.error(f"LLM call failed for user {telegram_id}: {e}")
        response = "Oops, my **cerebro** is a bit tired right now! Let's try again in a moment. 🧠"

    await add_message(telegram_id, "assistant", response)
    await update.message.reply_text(format_for_telegram(response), parse_mode="HTML")

    # Show setup buttons after 2 exchanges to anyone who hasn't picked
    # interests yet. Derived from the DB so it survives bot restarts.
    interests_unset = (db_user.get("interests") or "[]") == "[]"
    if (
        interests_unset
        and not context.user_data.get("setup_shown")
        and exchange_count >= 2
    ):
        context.user_data["setup_shown"] = True
        await asyncio.sleep(1)
        context.user_data["pending_interests"] = []
        await update.message.reply_text(
            "By the way — what topics would you like to chat about? Pick as many as you like!",
            reply_markup=_interests_keyboard([]),
        )


async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tg_user = update.effective_user
    telegram_id = tg_user.id

    db_user = await get_user(telegram_id)
    if db_user is None:
        await update.message.reply_text(
            "You'll need an invite to chat first. Send "
            "<code>/start your-invite-code</code> to join.",
            parse_mode="HTML",
        )
        return

    stats = await get_user_stats(telegram_id)
    name = db_user.get("first_name") or "amigo"

    interests = json.loads(db_user.get("interests") or "[]")
    daily_time_set = bool(db_user.get("daily_time_set"))
    daily_time = db_user.get("daily_time") if daily_time_set else None

    if interests:
        interests_line = f"Topics: {', '.join(interests)}"
    else:
        interests_line = "Topics: <i>not set yet</i> — type /setup to pick"
    if daily_time:
        daily_line = f"Daily check-in: {daily_time}"
    else:
        daily_line = "Daily check-in: <i>not set yet</i> — type /setup to pick"

    is_premium = bool(db_user.get("premium"))
    if is_premium:
        premium_line = "Premium: ✅ ON"
    else:
        feature_names = ", ".join(f[1] for f in PREMIUM_FEATURES)
        premium_line = (
            f"Premium: OFF — <i>{feature_names} disabled</i>\n"
            "  → /premium to unlock"
        )

    if stats["total_user_messages"] == 0:
        lines = [
            f"¡Hola, {name}! No <b>conversaciones</b> yet — say something and "
            "your stats will start filling up. 🌱",
            "",
            interests_line,
            daily_line,
            "",
            premium_line,
        ]
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
        return

    streak = stats["streak"]
    if streak == 0:
        streak_line = "Current streak: 0 days — chat today to start a new one!"
    elif streak == 1:
        streak_line = "Current streak: 1 day"
    else:
        streak_line = f"Current streak: {streak} days 🔥"

    lines = [
        f"<b>Tu progreso, {name}:</b>",
        "",
        f"Days since first chat: {stats['days_chatting']}",
        f"Active days: {stats['active_days']}",
        streak_line,
        f"Messages sent: {stats['total_user_messages']}",
        f"Spanish <b>palabras</b> you've seen: {stats['spanish_words_seen']}",
        "",
        interests_line,
        daily_line,
        "",
        premium_line,
        "",
        "¡Sigue así! Keep going. 🌱",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def setup_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tg_user = update.effective_user
    telegram_id = tg_user.id

    db_user = await get_user(telegram_id)
    if db_user is None:
        await update.message.reply_text(
            "You'll need an invite to chat first. Send "
            "<code>/start your-invite-code</code> to join.",
            parse_mode="HTML",
        )
        return

    interests_unset = (db_user.get("interests") or "[]") == "[]"
    if interests_unset:
        context.user_data["pending_interests"] = []
        context.user_data["setup_shown"] = True
        await update.message.reply_text(
            "What topics would you like to chat about? Pick as many as you like!",
            reply_markup=_interests_keyboard([]),
        )
        return

    if not db_user.get("daily_time_set"):
        await update.message.reply_text(
            "When should I message you each day for our <b>conversación</b>?",
            reply_markup=_time_keyboard(),
            parse_mode="HTML",
        )
        return

    interests = json.loads(db_user.get("interests") or "[]")
    daily_time = db_user.get("daily_time")
    await update.message.reply_text(
        "You're all set! Topics: <b>"
        + ", ".join(interests)
        + f"</b>. Daily check-in at <b>{daily_time}</b>.\n"
        "Type /stats to see your progress.",
        parse_mode="HTML",
    )


def _premium_text(is_premium: bool) -> str:
    if is_premium:
        header = "✅ <b>Premium is ON</b> (beta — enjoy the ride!)\n\nYou have access to:\n"
        lines = [f"  {e} <b>{name}</b> — {desc}" for e, name, desc in PREMIUM_FEATURES]
        footer = "\n\nTap below if you want to turn it off."
        button_label = "Disable Premium"
    else:
        header = "🔒 <b>Premium is OFF</b>\n\nUnlock these features:\n"
        lines = [f"  {e} <b>{name}</b> — {desc}" for e, name, desc in PREMIUM_FEATURES]
        footer = "\n\nTap below to enable (free during beta)."
        button_label = "Enable Premium ✨"
    return header + "\n".join(lines) + footer, button_label


async def premium_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    db_user = await get_user(telegram_id)
    if db_user is None:
        await update.message.reply_text(
            "You'll need an invite first. Send <code>/start your-invite-code</code>.",
            parse_mode="HTML",
        )
        return

    is_premium = bool(db_user.get("premium"))
    text, button_label = _premium_text(is_premium)
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(button_label, callback_data="premium_toggle")]]
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "<b>PocoAPoco commands</b>\n\n"
        "/start — restart the bot or say hello again\n"
        "/setup — change your topics or daily message time\n"
        "/stats — see your progress (days active, streak, Spanish words seen)\n"
        "/premium — enable or disable premium features\n"
        "/help — show this message\n\n"
        "Otherwise just <b>type anything</b> and we'll chat! 💬",
        parse_mode="HTML",
    )


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    telegram_id = query.from_user.id
    data = query.data

    if data.startswith("interest:"):
        topic = data[len("interest:"):]
        if topic not in _VALID_INTERESTS:
            logger.warning(f"Rejected interest callback from {telegram_id}: {topic!r}")
            return
        pending: list[str] = context.user_data.get("pending_interests", [])
        if topic in pending:
            pending.remove(topic)
        else:
            pending.append(topic)
        context.user_data["pending_interests"] = pending
        await query.edit_message_reply_markup(reply_markup=_interests_keyboard(pending))

    elif data == "interests_done":
        interests: list[str] = context.user_data.get("pending_interests", [])
        if not interests:
            await query.answer("Please select at least one topic!", show_alert=True)
            return
        # Defense-in-depth: drop anything not in the known set before persisting.
        interests = [i for i in interests if i in _VALID_INTERESTS]
        await update_user_interests(telegram_id, json.dumps(interests))
        selected_str = ", ".join(interests)
        await query.edit_message_text(f"Great choices! We'll talk about: {selected_str} 🎉")
        await query.message.reply_text(
            "And when should I message you each day for our <b>conversación</b>?",
            reply_markup=_time_keyboard(),
            parse_mode="HTML",
        )

    elif data.startswith("time:"):
        time_value = data[len("time:"):]
        if time_value not in _VALID_TIMES:
            logger.warning(f"Rejected time callback from {telegram_id}: {time_value!r}")
            return
        await update_user_daily_time(telegram_id, time_value)
        time_labels = {v: l for l, v in TIMES}
        label = time_labels.get(time_value, time_value)
        await query.edit_message_text(
            f"Perfect! I'll send you a daily <b>conversación</b> starter at {label}. "
            "See you <b>mañana</b>! 👋",
            parse_mode="HTML",
        )

    elif data == "premium_toggle":
        db_user = await get_user(telegram_id)
        if db_user is None:
            return
        new_value = not bool(db_user.get("premium"))
        await set_user_premium(telegram_id, new_value)
        text, button_label = _premium_text(new_value)
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton(button_label, callback_data="premium_toggle")]]
        )
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)


async def post_init(application: Application) -> None:
    await init_db()
    setup_scheduler(application)
    from telegram import BotCommand
    await application.bot.set_my_commands([
        BotCommand("start", "Start or restart the bot"),
        BotCommand("setup", "Change your topics or daily message time"),
        BotCommand("stats", "See your progress"),
        BotCommand("premium", "Manage premium features"),
        BotCommand("help", "Show available commands"),
    ])
    logger.info("Bot ready")


async def post_shutdown(application: Application) -> None:
    logger.info("Bot shutting down")


def main() -> None:
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("stats", stats_handler))
    app.add_handler(CommandHandler("setup", setup_handler))
    app.add_handler(CommandHandler("premium", premium_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CallbackQueryHandler(callback_query_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    logger.info("Starting PocoAPoco bot (polling)...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
