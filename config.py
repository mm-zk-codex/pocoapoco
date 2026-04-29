import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "qwen/qwen-2.5-72b-instruct")
DATABASE_PATH = os.getenv("DATABASE_PATH", "./pocoapoco.db")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
INVITE_CODE = os.getenv("INVITE_CODE")
