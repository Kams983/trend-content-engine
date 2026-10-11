"""One shared HTTP client for the whole engine.

Guarantees:
  * a descriptive ``User-Agent`` on every request,
  * an explicit timeout (never a hang),
  * exponential backoff **with jitter** on 429 and 5xx,
  * ``Retry-After`` honoured (both delta-seconds and HTTP-date),
  * at most ``attempts`` tries, then a loud ``HttpError``.

Every network call in the codebase goes through here so retry behaviour is
consistent and testable (``sleep`` is injectable).
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from typing import Any, Callable

import requests

from .logging_setup import kv

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "TrendContentEngine/1.0 (+https://github.com/trend-content-engine; contact: ops@example.com)"
)
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class HttpError(RuntimeError):
    """Raised when a request fails after exhausting retries."""


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    backoff_base: float = 0.5
    backoff_max: float = 30.0
    timeout: float = 15.0


DEFAULT_POLICY = RetryPolicy()

_session: requests.Session | None = None


def session() -> requests.Session:
    """Process-wide session (connection reuse) with a default User-Agent."""
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": DEFAULT_USER_AGENT, "Accept": "*/*"})
    return _session


def reset_session() -> None:
    """Drop the cached session (used by tests)."""
    global _session
    if _session is not None:
        _session.close()
    _session = None


def _backoff_seconds(attempt: int, policy: RetryPolicy) -> float:
    """Exponential backoff with full jitter, capped at ``backoff_max``."""
    ceiling = min(policy.backoff_max, policy.backoff_base * (2 ** attempt))
    return random.uniform(0.0, ceiling)


def _retry_after_seconds(response: requests.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    raw = raw.strip()
    if raw.isdigit():
        return float(raw)
    try:
        when = parsedate_to_datetime(raw)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None


def request(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    json: Any = None,
    data: Any = None,
    headers: dict[str, str] | None = None,
    policy: RetryPolicy | None = None,
    ok_statuses: frozenset[int] | None = None,
    raise_for_status: bool = True,
    sleep: Callable[[float], None] = time.sleep,
    http_session: requests.Session | None = None,
) -> requests.Response:
    """Perform an HTTP request with retry/backoff. Raises ``HttpError`` on failure."""
    policy = policy or DEFAULT_POLICY
    http = http_session or session()
    attempts = max(1, policy.attempts)
    last_error: str = "unknown"

    for attempt in range(attempts):
        try:
            response = http.request(
                method,
                url,
                params=params,
                json=json,
                data=data,
                headers=headers,
                timeout=policy.timeout,
            )
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                kv("http_transport_error", method=method, url=url, attempt=attempt + 1, error=last_error)
            )
            if attempt + 1 < attempts:
                sleep(_backoff_seconds(attempt, policy))
                continue
            break

        status = response.status_code
        retryable = status in RETRY_STATUSES
        if not retryable:
            if raise_for_status and status >= 400 and not (ok_statuses and status in ok_statuses):
                raise HttpError(f"{method} {url} → HTTP {status}")
            return response

        last_error = f"HTTP {status}"
        if attempt + 1 >= attempts:
            logger.warning(kv("http_retries_exhausted", method=method, url=url, status=status))
            break

        wait = _retry_after_seconds(response)
        if wait is None:
            wait = _backoff_seconds(attempt, policy)
        logger.warning(
            kv("http_retry", method=method, url=url, status=status, attempt=attempt + 1, wait=round(wait, 2))
        )
        sleep(wait)

    raise HttpError(f"{method} {url} failed after {attempts} attempts ({last_error})")


def get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    policy: RetryPolicy | None = None,
    **kwargs: Any,
) -> Any:
    response = request("GET", url, params=params, headers=headers, policy=policy, **kwargs)
    return response.json()


def get_text(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    policy: RetryPolicy | None = None,
    **kwargs: Any,
) -> str:
    response = request("GET", url, params=params, headers=headers, policy=policy, **kwargs)
    return response.text


def post_json(
    url: str,
    *,
    json: Any = None,
    data: Any = None,
    headers: dict[str, str] | None = None,
    policy: RetryPolicy | None = None,
    **kwargs: Any,
) -> requests.Response:
    return request("POST", url, json=json, data=data, headers=headers, policy=policy, **kwargs)
