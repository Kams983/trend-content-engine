"""Ops alerting.

Alerts go to the Telegram admin chat when it is configured. When it is not
(typical for local runs and the offline smoke test) the alert is written to the
log as a warning so it is never silently lost.
"""

from __future__ import annotations

import logging

from .config import Settings
from .outcomes import is_failure
from .util.logging_setup import kv

logger = logging.getLogger(__name__)


def alert(message: str, settings: Settings) -> bool:
    """Send *message* to the admin chat (or log it). Returns True if delivered."""
    if settings.dry_run:
        logger.info(kv("alert_dry_run", message=message[:300]))
        return False
    if not settings.telegram_bot_token or not settings.telegram_admin_chat_id:
        logger.warning(kv("alert_not_delivered", reason="telegram_not_configured", message=message[:300]))
        return False
    # Imported lazily so this module stays cheap for tests that patch it.
    from .publish.telegram_poster import send_alert

    delivered = send_alert(message, settings)
    if not delivered:
        logger.warning(kv("alert_not_delivered", message=message[:300]))
    return delivered


def alert_failure(outcome: str, reason: str, settings: Settings, stage: str = "") -> bool:
    """Alert on a ``FAILED_*`` outcome. No-ops for benign outcomes."""
    if not is_failure(outcome):
        return False
    return alert(f"{outcome}: {reason}" + (f" (stage={stage})" if stage else ""), settings)
