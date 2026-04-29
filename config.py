import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "qwen/qwen3-30b-a3b-instruct-2507")
DATABASE_PATH = os.getenv("DATABASE_PATH", "./pocoapoco.db")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
INVITE_CODE = os.getenv("INVITE_CODE")
# Weekly price for Premium in Telegram Stars. 0 keeps current beta-free toggle.
# Telegram Stars subscriptions are 30-day only, so this value is multiplied by 4
# to compute the actual recurring invoice (displayed as "X⭐/week, Y⭐/30 days").
PREMIUM_PRICE_STARS_PER_WEEK = int(os.getenv("PREMIUM_PRICE_STARS_PER_WEEK", "0"))
