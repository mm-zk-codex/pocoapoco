import logging
import re
from datetime import datetime, timedelta

import httpx

from config import OPENROUTER_API_KEY, OPENROUTER_MODEL

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TEMPLATE = """You are PocoAPoco, a friendly and casual Spanish conversation partner for English speakers. Your job is to have natural, engaging conversations where you blend English and Spanish together in the SAME sentences.

RULES FOR LANGUAGE BLENDING:
- Mix English and Spanish within the same sentences. Do NOT write separate English and Spanish paragraphs.
- The Spanish words/phrases should be inferable from context — the surrounding English should make the meaning clear.
- Target approximately {spanish_ratio}% Spanish words in your messages.
- Bold the Spanish words/phrases using markdown (**word**) so they stand out.
- Use common, high-frequency Spanish words appropriate for level {language_level}.
- When you introduce a new Spanish word for the first time in a conversation, make sure the English context makes its meaning obvious.

RULES FOR TEACHING:
- If the user makes a Spanish mistake, correct it briefly and naturally within your response — don't make a big deal of it. Example: "Almost! It's **tiene** not **tene** — but I understood you perfectly. So anyway..."
- If the user responds only in English, that's fine. Gently encourage them to try using some Spanish words, but don't pressure them.
- If the user tries Spanish, praise the effort briefly and continue.
- Do NOT explain grammar rules unless the user explicitly asks. Keep it conversational.
- Never switch to full Spanish. Always maintain the blend.

RULES FOR CONVERSATION:
- Keep your messages short — 2-3 sentences max. This is a chat, not an essay.
- Be warm, curious, and casual. Like texting with a bilingual friend.
- Ask follow-up questions to keep the conversation going.
- Stay on topic but let the conversation flow naturally.
- When wrapping up a conversation (after 5-8 exchanges), do so naturally: "This was fun! **Hablamos mañana** — we can talk more about {topic} or try something new!"

CURRENT CONVERSATION CONTEXT:
- Topic: {topic}
- User interests: {interests}
- This is message {message_number} of this conversation session.
- If message_number >= 6, start wrapping up the conversation naturally within the next 1-2 messages."""


def build_system_prompt(
    spanish_ratio: int,
    language_level: str,
    topic: str,
    interests: list,
    message_number: int,
) -> str:
    interests_str = ", ".join(interests) if interests else "general conversation"
    return SYSTEM_PROMPT_TEMPLATE.format(
        spanish_ratio=spanish_ratio,
        language_level=language_level,
        topic=topic,
        interests=interests_str,
        message_number=message_number,
    )


async def call_llm(system_prompt: str, history: list[dict]) -> str:
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "max_tokens": 300,
        "temperature": 0.8,
    }

    start = datetime.now()
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://pocoapoco.bot",
                "X-Title": "PocoAPoco",
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    latency = (datetime.now() - start).total_seconds()
    usage = data.get("usage", {})
    logger.info(
        f"LLM call: tokens={usage.get('total_tokens', '?')}, latency={latency:.2f}s"
    )

    choices = data.get("choices") or []
    content = choices[0].get("message", {}).get("content") if choices else None
    if not content or not isinstance(content, str):
        # OpenRouter can return a 200 with null content (refusals, upstream
        # provider errors, content filtering). Surface as an error so callers
        # fall back to their generic "try again" message.
        logger.error(f"LLM returned empty content; raw response: {data!r}")
        raise RuntimeError("LLM returned empty content")
    return content


def format_for_telegram(text: str) -> str:
    """Convert **bold** markdown to Telegram HTML, escaping other special chars."""
    parts = re.split(r"(\*\*.+?\*\*)", text, flags=re.DOTALL)
    result = []
    for part in parts:
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            inner = part[2:-2]
            inner = inner.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            result.append(f"<b>{inner}</b>")
        else:
            escaped = part.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            result.append(escaped)
    return "".join(result)


def is_new_session(history: list[dict], threshold_minutes: int = 30) -> bool:
    """True if the last assistant message was more than threshold_minutes ago."""
    if not history:
        return True
    for msg in reversed(history):
        if msg["role"] == "assistant":
            try:
                last_time = datetime.fromisoformat(msg["created_at"])
                return (datetime.now() - last_time) > timedelta(minutes=threshold_minutes)
            except (KeyError, ValueError):
                return True
    return True


def get_session_message_count(history: list[dict], threshold_minutes: int = 30) -> int:
    """Count user messages in the current session (since last 30-min gap)."""
    if not history:
        return 0
    count = 0
    now = datetime.now()
    for msg in reversed(history):
        try:
            msg_time = datetime.fromisoformat(msg["created_at"])
            if (now - msg_time) > timedelta(minutes=threshold_minutes):
                break
            if msg["role"] == "user":
                count += 1
        except (KeyError, ValueError):
            continue
    return count
