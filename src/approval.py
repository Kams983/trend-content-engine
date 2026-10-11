"""Handle approve/reject callbacks from the Telegram admin chat.

Stage A sends each draft to ``TELEGRAM_ADMIN_CHAT_ID`` with inline buttons
carrying ``approve:<article_id>`` / ``reject:<article_id>``. This module polls
``getUpdates``, checks the callback really came from the admin chat, updates the
article status and (on approval) publishes it.

The offset is persisted in ``schema_meta`` so we never process an update twice.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from .config import Settings
from .state import repo
from .util.logging_setup import kv

logger = logging.getLogger(__name__)

_OFFSET_KEY = "telegram_offset"


def get_offset(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT value FROM schema_meta WHERE key = ?", (_OFFSET_KEY,)).fetchone()
    if not row or not row[0]:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


def set_offset(conn: sqlite3.Connection, offset: int) -> None:
    conn.execute(
        "INSERT INTO schema_meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (_OFFSET_KEY, str(int(offset))),
    )
    conn.commit()


def is_authorized(update: dict, settings: Settings) -> bool:
    """True only when the callback came from the configured admin chat."""
    callback = update.get("callback_query") or {}
    message = callback.get("message") or {}
    chat_id = str((message.get("chat") or {}).get("id", ""))
    admin = str(settings.telegram_admin_chat_id or "")
    return bool(admin) and chat_id == admin


def parse_callback(data: str) -> tuple[str, int] | None:
    """Parse ``approve:12`` / ``reject:12`` into ``("approve", 12)``."""
    if not data or ":" not in data:
        return None
    action, _, raw_id = data.partition(":")
    action = action.strip().lower()
    if action not in {"approve", "reject"}:
        return None
    try:
        return action, int(raw_id)
    except ValueError:
        return None


def process_update(conn: sqlite3.Connection, update: dict, settings: Settings) -> str:
    """Apply one update. Returns a short status string for logging/tests."""
    from .publish import telegram_poster as tg

    callback = update.get("callback_query")
    if not callback:
        return "ignored"

    callback_id = callback.get("id", "")
    if not is_authorized(update, settings):
        logger.warning(kv("approval_unauthorized", chat_id=(callback.get("message") or {}).get("chat", {}).get("id")))
        tg.answer_callback(settings, callback_id, "Not authorized")
        return "unauthorized"

    parsed = parse_callback(callback.get("data", ""))
    if parsed is None:
        tg.answer_callback(settings, callback_id, "Unknown action")
        return "ignored"

    action, article_id = parsed
    article = repo.get_article(conn, article_id)
    if article is None:
        tg.answer_callback(settings, callback_id, "Article not found")
        return "missing"

    if article["status"] not in (repo.STATUS_PENDING, repo.STATUS_APPROVED):
        tg.answer_callback(settings, callback_id, f"Already {article['status']}")
        return "noop"

    if action == "reject":
        repo.set_article_status(conn, article_id, repo.STATUS_REJECTED)
        tg.answer_callback(settings, callback_id, "Rejected")
        _clear(settings, callback, f"🗑 Draft #{article_id} rejected")
        logger.info(kv("approval_rejected", article_id=article_id))
        return "rejected"

    repo.set_article_status(conn, article_id, repo.STATUS_APPROVED)
    tg.answer_callback(settings, callback_id, "Approved — publishing")
    _clear(settings, callback, f"✅ Draft #{article_id} approved")
    logger.info(kv("approval_approved", article_id=article_id))
    return "approved"


def _clear(settings: Settings, callback: dict, text: str) -> None:
    from .publish import telegram_poster as tg

    message = callback.get("message") or {}
    chat_id = str((message.get("chat") or {}).get("id", ""))
    message_id = message.get("message_id")
    if chat_id and message_id:
        tg.clear_approval_buttons(settings, chat_id, int(message_id), text=text)


def handle_approvals(conn: sqlite3.Connection, settings: Settings, timeout: int = 0) -> dict[str, int]:
    """Poll Telegram once and process any callbacks. Returns per-action counts."""
    from .publish import telegram_poster as tg

    if not settings.telegram_bot_token or not settings.telegram_admin_chat_id:
        return {}

    offset = get_offset(conn)
    updates: list[dict[str, Any]] = tg.get_updates(settings, offset=offset, timeout=timeout)
    counts: dict[str, int] = {}
    highest: int | None = None

    for update in updates:
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            highest = update_id
        status = process_update(conn, update, settings)
        counts[status] = counts.get(status, 0) + 1

    if highest is not None:
        set_offset(conn, highest + 1)
    if counts:
        logger.info(kv("approvals_processed", **counts))
    return counts
