"""Post an article teaser + link to a Telegram channel via Bot API.

Authenticates with TELEGRAM_BOT_TOKEN and posts to TELEGRAM_CHANNEL_ID
from environment variables.  Returns True on success, False on failure
— never raises.
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def telegram_poster(article: dict, site_url: str = "") -> bool:
    """Post a teaser card to a Telegram channel.

    Args:
        article: dict with at least 'title' and 'teaser'.
        site_url: base URL of the site.  If empty, only the teaser is posted.

    Returns True if the message was sent, False otherwise.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    channel_id = os.environ.get("TELEGRAM_CHANNEL_ID", "")

    if not token or not channel_id:
        logger.error("TELEGRAM_BOT_TOKEN or TELEGRAM_CHANNEL_ID not set")
        return False

    title = article.get("title", "")
    teaser = article.get("teaser", "")

    if not teaser:
        logger.warning("Empty teaser — skipping Telegram post")
        return False

    # Build message: bold title + teaser + optional link
    parts: list[str] = []
    if title:
        parts.append(f"<b>{title}</b>")
    parts.append(teaser)

    if site_url and title:
        slug = title.lower().replace(" ", "-")
        slug = "".join(c if c.isalnum() or c == "-" else "" for c in slug)
        slug = slug[:80]
        from datetime import datetime, timezone
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        link = f"{site_url.rstrip('/')}/posts/{date_str}-{slug}"
        parts.append(f'\n<a href="{link}">Read full article →</a>')

    text = "\n\n".join(parts)

    url = TELEGRAM_API.format(token=token, method="sendMessage")
    payload = {
        "chat_id": channel_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("ok"):
            msg_id = data["result"]["message_id"]
            logger.info("Telegram post: message %s to %s", msg_id, channel_id)
            return True
        else:
            logger.error("Telegram API error: %s", data.get("description"))
            return False
    except Exception as exc:
        logger.error("Telegram post failed: %s", exc)
        return False
