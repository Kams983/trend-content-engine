"""Telegram approve/reject decisions, and getting a tap published immediately.

Stage A sends each draft to ``TELEGRAM_ADMIN_CHAT_ID`` with inline buttons
carrying ``approve:<article_id>`` / ``reject:<article_id>``. Two paths turn a
tap into a post:

* **The listener** — ``python -m src.approval --watch`` long-polls Telegram and,
  on a tap, dispatches the ``publish-approved`` workflow with that article id and
  action. It never confirms the update, so the publish run still receives it and
  can answer the button and edit the message. This is what makes a tap publish
  within a couple of minutes instead of waiting for the hourly cron, which
  GitHub often delays by hours (Telegram forgets updates after 24 hours).
* **A publish run** — ``handle_approvals`` polls the callbacks itself, which is
  the fallback when no listener is running and how a queued tap is confirmed.

Both paths converge on :func:`apply_decision`, and the dispatch carries the
decision as workflow inputs so publishing does not depend on the tap still being
inside Telegram's update window.
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import time
from typing import Any, Callable

from .config import Settings, load_settings
from .state import repo
from .util.http import request
from .util.logging_setup import kv, setup_logging

logger = logging.getLogger(__name__)

_OFFSET_KEY = "telegram_offset"

#: GitHub API root, and the workflows this module dispatches.
GITHUB_API = "https://api.github.com"
PUBLISH_WORKFLOW = "publish.yml"
LISTENER_WORKFLOW = "approval-listener.yml"


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


def apply_decision(conn: sqlite3.Connection, action: str, article_id: int) -> str:
    """Apply one decision without touching Telegram.

    Returns ``approved``, ``rejected``, ``missing`` or ``noop`` (already
    published/rejected). Used by the callback handler and by
    ``python -m src.main --mode publish --approval approve:15``.
    """
    article = repo.get_article(conn, int(article_id))
    if article is None:
        return "missing"
    if article["status"] not in (repo.STATUS_PENDING, repo.STATUS_APPROVED):
        return "noop"
    if action == "reject":
        repo.set_article_status(conn, int(article_id), repo.STATUS_REJECTED)
        logger.info(kv("approval_rejected", article_id=int(article_id)))
        return "rejected"
    repo.set_article_status(conn, int(article_id), repo.STATUS_APPROVED)
    logger.info(kv("approval_approved", article_id=int(article_id)))
    return "approved"


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

    status = apply_decision(conn, action, article_id)
    if status == "noop":
        tg.answer_callback(settings, callback_id, f"Already {article['status']}")
        return "noop"
    if status == "rejected":
        tg.answer_callback(settings, callback_id, "Rejected")
        _clear(settings, callback, f"🗑 Draft #{article_id} rejected")
        return "rejected"

    tg.answer_callback(settings, callback_id, "Approved — publishing")
    _clear(settings, callback, f"✅ Draft #{article_id} approved")
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


# ---------------------------------------------------------------------------
# Dispatch: make GitHub start the publish workflow right away
# ---------------------------------------------------------------------------


def _dispatch_token() -> str:
    """Token that may trigger workflows: a PAT if provided, else GITHUB_TOKEN."""
    return (os.environ.get("GH_DISPATCH_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()


def _repository() -> str:
    return (os.environ.get("GITHUB_REPOSITORY") or "").strip()


def dispatch_workflow(
    workflow: str,
    *,
    inputs: dict[str, str] | None = None,
    token: str | None = None,
    repo: str | None = None,
    ref: str = "main",
) -> bool:
    """Trigger *workflow* on GitHub. Returns True when the API accepted it."""
    token = token or _dispatch_token()
    repository = repo or _repository()
    if not token or not repository:
        logger.error(
            kv(
                "dispatch_missing_config",
                workflow=workflow,
                token=bool(token),
                repository=bool(repository),
                note="set GITHUB_REPOSITORY and GITHUB_TOKEN (or a GH_DISPATCH_TOKEN secret)",
            )
        )
        return False

    url = f"{GITHUB_API}/repos/{repository}/actions/workflows/{workflow}/dispatches"
    payload: dict[str, Any] = {"ref": ref}
    if inputs:
        payload["inputs"] = inputs
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        request("POST", url, json=payload, headers=headers)
    except Exception as exc:  # network, auth or a rejected payload
        logger.error(kv("dispatch_failed", workflow=workflow, error=str(exc)[:200]))
        return False
    logger.info(kv("dispatch_ok", workflow=workflow, ref=ref, inputs=sorted((inputs or {}).keys())))
    return True


def dispatch_publish(action: str, article_id: int) -> bool:
    """Start ``publish-approved`` for one decision."""
    return dispatch_workflow(PUBLISH_WORKFLOW, inputs={"action": action, "article_id": str(int(article_id))})


def watch_for_approvals(
    settings: Settings,
    *,
    duration: float,
    poll_timeout: int = 25,
    updates: Callable[[], list[dict]] | None = None,
    dispatch: Callable[[str, int], bool] | None = None,
    clock: Callable[[], float] = time.monotonic,
    pause: Callable[[float], None] = time.sleep,
    pending_pause: float = 5.0,
) -> dict[str, int]:
    """Long-poll Telegram for *duration* seconds and dispatch each tap once.

    Deliberately does **not** confirm updates (no offset): the publish run owns
    the offset, so it still receives the callback, answers the button and edits
    the message. The ids already dispatched are remembered so a tap is not
    dispatched again while it waits to be confirmed.
    """
    from .publish import telegram_poster as tg

    if not settings.telegram_bot_token or not settings.telegram_admin_chat_id:
        logger.error(kv("approval_watch_unconfigured", note="TELEGRAM_BOT_TOKEN / TELEGRAM_ADMIN_CHAT_ID"))
        return {"error": 1}

    fetch = updates or (lambda: tg.get_updates(settings, offset=None, timeout=poll_timeout))
    send = dispatch or dispatch_publish
    counts = {"dispatched": 0, "ignored": 0, "duplicate": 0, "failed": 0}
    seen: set[int] = set()
    deadline = clock() + max(0.0, float(duration))
    next_pause = pending_pause

    while clock() < deadline:
        next_pause = pending_pause
        batch = fetch()
        if not batch:
            continue
        for update in batch:
            update_id = update.get("update_id")
            parsed = parse_callback((update.get("callback_query") or {}).get("data") or "")
            if parsed is None or not is_authorized(update, settings):
                counts["ignored"] += 1
                continue
            if isinstance(update_id, int) and update_id in seen:
                counts["duplicate"] += 1
                continue
            action, article_id = parsed
            if send(action, article_id):
                counts["dispatched"] += 1
                if isinstance(update_id, int):
                    seen.add(update_id)
            else:
                # Keep the tap unconfirmed so it is retried, but back off: a
                # misconfigured token would otherwise retry every few seconds.
                counts["failed"] += 1
                next_pause = 60.0
        # Those updates stay unconfirmed until a publish run handles them, so
        # the next poll returns them again; wait instead of hammering the API.
        pause(next_pause)

    logger.info(kv("approval_watch_done", **counts))
    return counts


def main(argv: list[str] | None = None) -> int:
    """``python -m src.approval --watch`` — the approval listener."""
    parser = argparse.ArgumentParser(
        prog="python -m src.approval",
        description="Dispatch publishing as soon as a Telegram approval lands",
    )
    parser.add_argument("--watch", action="store_true", help="long-poll Telegram for approvals")
    parser.add_argument(
        "--duration",
        type=int,
        default=19_500,
        help="seconds to listen for (default 19500 = 5h25m, inside GitHub's 6h job limit)",
    )
    parser.add_argument("--poll-timeout", type=int, default=25, help="Telegram long-poll timeout")
    parser.add_argument(
        "--redispatch",
        action="store_true",
        help="dispatch this listener again before exiting, so it stays running without cron",
    )
    args = parser.parse_args(argv)
    setup_logging("INFO")
    if not args.watch:
        parser.error("--watch is required (use `python -m src.main --mode publish --approval approve:N` to apply one decision)")

    # The listener only needs Telegram; drafting keys are not required here.
    settings = load_settings(validate=False)
    counts = watch_for_approvals(settings, duration=args.duration, poll_timeout=args.poll_timeout)
    failed = counts.get("error", 0) > 0

    if args.redispatch:
        if not dispatch_workflow(LISTENER_WORKFLOW):
            failed = True

    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
