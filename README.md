# PocoAPoco

A Telegram bot that teaches English speakers Spanish through blended daily conversations.

## Setup

```bash
# 1. Clone / copy the project
cd pocoapoco

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env and fill in your tokens (see below)

# 5. Run
python bot.py
```

## Getting the tokens

**Telegram bot token**
1. Open Telegram and message `@BotFather`
2. Send `/newbot`, follow the prompts
3. Copy the token into `.env` as `TELEGRAM_BOT_TOKEN`

**OpenRouter API key**
1. Sign up at https://openrouter.ai
2. Add a small amount of credit ($5 lasts months of testing)
3. Copy your API key into `.env` as `OPENROUTER_API_KEY`

## Running as a systemd service

```bash
# Edit the service file — replace placeholders with real paths and username
nano systemd/pocoapoco.service

sudo cp systemd/pocoapoco.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable pocoapoco
sudo systemctl start pocoapoco

# Check status
sudo systemctl status pocoapoco
sudo journalctl -u pocoapoco -f
```

## Testing

1. Start the bot: `python bot.py`
2. Open Telegram, find your bot, send `/start`
3. Verify the hardcoded welcome message appears
4. Reply a couple of times — verify LLM blended responses
5. After 2 exchanges the topic/time selection buttons appear
6. Select interests and a daily time
7. To test scheduled messages immediately, temporarily change the `daily_time`
   for your test user in the SQLite DB to the current HH:MM

## Project structure

```
bot.py            Main entry point and all Telegram handlers
conversation.py   LLM calls, system prompt, HTML formatting helper
scheduler.py      APScheduler setup for daily messages
database.py       SQLite schema and all read/write functions
config.py         Environment variable loading
topics.py         Curated topic list (8 categories × 10 sub-topics)
requirements.txt
.env.example
systemd/          systemd unit file template
```
