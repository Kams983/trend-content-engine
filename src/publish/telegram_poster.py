"""Telegram Bot API: channel posts, approval prompts, alerts and polling.

Verified against the Telegram Bot API:

* ``POST https://api.telegram.org/bot<token>/sendMessage`` with
  ``chat_id``, ``text``, ``parse_mode=HTML``, ``link_preview_options`` /
  ``disable_web_page_preview``
* inline keyboards via ``reply_markup={"inline_keyboard": [[{...}]]}``
* ``getUpdates`` / ``answerCallbackQuery`` / ``editMessageReplyMarkup``

HTML parse mode requires escaping ``&``, ``<`` and ``>`` in any user text.
"""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any

from ..util.http import RetryPolicy, post_json, request
from .base import PublishResult, build_description, post_url

logger = logging.getLogger(__name__)

API_TEMPLATE = "https://api.telegram.org/bot{token}/{method}"
_POLICY = RetryPolicy(attempts=3, backoff_base=1.0, timeout=15.0)

APPROVE_PREFIX = "approve:"
REJECT_PREFIX = "reject:"


def escape_html(text: str) -> str:
    """Escape text for ``parse_mode=HTML`` (order matters)."""
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def api_url(token: str, method: str) -> str:
    return API_TEMPLATE.format(token=token, method=method)


def build_channel_message(article: dict, settings) -> str:
    """Channel post: bold title, teaser, link."""
    parts: list[str] = []
    title = (article.get("title") or "").strip()
    if title:
        parts.append(f"<b>{escape_html(title)}</b>")
    teaser = (article.get("teaser") or "").strip()
    if teaser:
        parts.append(escape_html(teaser))
    link = article.get("url") or post_url(settings, article.get("slug", ""))
    if link:
        parts.append(f'<a href="{escape_html(link)}">Read the full article →</a>')
    return "\n\n".join(parts)


def build_approval_message(article: dict, article_id: int, settings) -> str:
    """Admin message previewing a draft awaiting approval."""
    title = (article.get("title") or "").strip()
    teaser = (article.get("teaser") or "").strip()
    body = (article.get("body_markdown") or "").strip()
    words = len(body.split())
    lines = [
        f"<b>Draft #{article_id} awaiting approval</b>",
        "",
        f"<b>{escape_html(title)}</b>",
        "",
        escape_html(build_description(teaser, 300)),
        "",
        f"<i>{words} words · topic {article.get('topic_id', '?')} · "
        f"targets: {', '.join(settings.enabled_targets)}</i>",
    ]
    return "\n".join(lines)


def build_approval_keyboard(article_id: int) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Approve & publish", "callback_data": f"{APPROVE_PREFIX}{article_id}"},
                {"text": "🗑 Reject", "callback_data": f"{REJECT_PREFIX}{article_id}"},
            ]
        ]
    }


def send_message(
    text: str,
    settings,
    chat_id: str | None = None,
    reply_markup: dict | None = None,
    disable_preview: bool = True,
) -> PublishResult:
    """Send a message via the bot. Returns a result (never raises)."""
    token = settings.telegram_bot_token
    target = chat_id or settings.telegram_channel_id
    if not token or not target:
        return PublishResult(target="telegram", ok=False, error="TELEGRAM_BOT_TOKEN/chat id not set")

    payload: dict[str, Any] = {
        "chat_id": target,
        "text": text,
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": bool(disable_preview)},
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        response = post_json(api_url(token, "sendMessage"), json=payload, policy=_POLICY)
        data = response.json()
    except Exception as exc:
        logger.error("event=telegram_send_failed error=%s", exc)
        return PublishResult(target="telegram", ok=False, error=str(exc))

    if not data.get("ok"):
        logger.error("event=telegram_api_error description=%s", data.get("description"))
        return PublishResult(target="telegram", ok=False, error=str(data.get("description")))

    message_id = str(data.get("result", {}).get("message_id", ""))
    logger.info("event=telegram_sent chat_id=%s message_id=%s", target, message_id)
    return PublishResult(target="telegram", ok=True, external_id=message_id)


def telegram_poster(article: dict, settings) -> PublishResult:
    """Channel post."""
    teaser = (article.get("teaser") or "").strip()
    if not teaser:
        return PublishResult(target="telegram", skipped=True, error="empty teaser")
    if not settings.telegram_channel_id:
        return PublishResult(target="telegram", ok=False, error="TELEGRAM_CHANNEL_ID not set")
    return send_message(build_channel_message(article, settings), settings, chat_id=settings.telegram_channel_id)


def send_approval_request(article: dict, article_id: int, settings) -> PublishResult:
    """Send a draft to the admin chat with Approve / Reject buttons."""
    if not settings.telegram_admin_chat_id:
        return PublishResult(target="telegram", ok=False, error="TELEGRAM_ADMIN_CHAT_ID not set")
    return send_message(
        build_approval_message(article, article_id, settings),
        settings,
        chat_id=settings.telegram_admin_chat_id,
        reply_markup=build_approval_keyboard(article_id),
    )


def send_alert(message: str, settings) -> bool:
    """Send an ops alert to the admin chat. Returns True on success."""
    if not settings.telegram_admin_chat_id or not settings.telegram_bot_token:
        logger.warning("event=alert_skipped reason=no_admin_chat message=%s", message[:200])
        return False
    result = send_message(f"⚠️ <b>TCE alert</b>\n\n{escape_html(message)}", settings, chat_id=settings.telegram_admin_chat_id)
    return result.ok


def get_updates(settings, offset: int | None = None, timeout: int = 0) -> list[dict]:
    """Long-poll for updates (used by the approval handler)."""
    token = settings.telegram_bot_token
    if not token:
        return []
    params: dict[str, Any] = {"timeout": timeout, "allowed_updates": '["callback_query"]'}
    if offset is not None:
        params["offset"] = offset
    try:
        query = urllib.parse.urlencode(params)
        response = request("GET", f"{api_url(token, 'getUpdates')}?{query}", policy=_POLICY)
        data = response.json()
    except Exception as exc:
        logger.warning("event=telegram_getupdates_failed error=%s", exc)
        return []
    if not data.get("ok"):
        return []
    return list(data.get("result") or [])


def answer_callback(settings, callback_query_id: str, text: str = "") -> bool:
    """Acknowledge a callback button press (stops the client spinner)."""
    token = settings.telegram_bot_token
    if not token:
        return False
    try:
        response = post_json(
            api_url(token, "answerCallbackQuery"),
            json={"callback_query_id": callback_query_id, "text": text},
            policy=_POLICY,
        )
        return bool(response.json().get("ok"))
    except Exception as exc:
        logger.warning("event=telegram_answer_callback_failed error=%s", exc)
        return False


def clear_approval_buttons(settings, chat_id: str, message_id: int, text: str = "") -> bool:
    """Remove the inline keyboard from an already-sent approval message."""
    token = settings.telegram_bot_token
    if not token:
        return False
    payload: dict[str, Any] = {"chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": []}}
    if text:
        payload["text"] = text
        payload["parse_mode"] = "HTML"
        method = "editMessageText"
    else:
        method = "editMessageReplyMarkup"
    try:
        response = post_json(api_url(token, method), json=payload, policy=_POLICY)
        return bool(response.json().get("ok"))
    except Exception as exc:
        logger.warning("event=telegram_clear_buttons_failed error=%s", exc)
        return False
