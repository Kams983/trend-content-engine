"""The shared HTTP helper: retries, backoff, Retry-After and failure modes."""

from __future__ import annotations

import json

import pytest
import requests

from src.util import http as http_mod
from src.util.http import HttpError, RetryPolicy, request


def make_response(status: int, headers: dict | None = None, body: dict | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.headers.update(headers or {})
    response._content = json.dumps(body or {}).encode()
    return response


class FakeSession:
    """Returns queued items in order; any item can be an exception to raise."""

    def __init__(self, queue: list):
        self.queue = list(queue)
        self.calls: list[dict] = []

    def request(self, method, url, **kwargs):  # noqa: ANN001
        self.calls.append({"method": method, "url": url, **kwargs})
        item = self.queue[min(len(self.calls) - 1, len(self.queue) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


def test_success_returns_response_without_sleeping() -> None:
    session = FakeSession([make_response(200, body={"ok": True})])
    slept: list[float] = []
    response = request("GET", "https://x.test", http_session=session, sleep=slept.append)
    assert response.status_code == 200
    assert slept == []
    assert len(session.calls) == 1


def test_retries_on_500_then_succeeds() -> None:
    session = FakeSession([make_response(500), make_response(200, body={"ok": 1})])
    slept: list[float] = []
    response = request(
        "GET", "https://x.test", http_session=session, sleep=slept.append, policy=RetryPolicy(attempts=3)
    )
    assert response.status_code == 200
    assert len(session.calls) == 2
    assert len(slept) == 1


def test_retries_on_429_honours_retry_after() -> None:
    session = FakeSession([make_response(429, headers={"Retry-After": "7"}), make_response(200)])
    slept: list[float] = []
    request("GET", "https://x.test", http_session=session, sleep=slept.append, policy=RetryPolicy(attempts=2))
    assert slept == [7.0]


def test_exhausted_retries_raises_http_error() -> None:
    session = FakeSession([make_response(503)] * 3)
    with pytest.raises(HttpError):
        request("GET", "https://x.test", http_session=session, sleep=lambda _: None, policy=RetryPolicy(attempts=3))
    assert len(session.calls) == 3


def test_transport_error_is_retried() -> None:
    session = FakeSession([requests.ConnectionError("boom"), make_response(200)])
    slept: list[float] = []
    response = request("GET", "https://x.test", http_session=session, sleep=slept.append, policy=RetryPolicy(attempts=2))
    assert response.status_code == 200
    assert len(slept) == 1


def test_backoff_is_jittered_and_capped() -> None:
    policy = RetryPolicy(attempts=3, backoff_base=1.0, backoff_max=5.0)
    values = [http_mod._backoff_seconds(attempt, policy) for attempt in range(8)]
    assert all(0.0 <= value <= 5.0 for value in values)


def test_client_error_is_not_retried() -> None:
    session = FakeSession([make_response(400)])
    with pytest.raises(HttpError):
        request("GET", "https://x.test", http_session=session, sleep=lambda _: None)
    assert len(session.calls) == 1


def test_ok_statuses_suppresses_raise() -> None:
    session = FakeSession([make_response(404)])
    response = request("GET", "https://x.test", http_session=session, ok_statuses=frozenset({404}))
    assert response.status_code == 404


def test_session_has_descriptive_user_agent() -> None:
    http_mod.reset_session()
    assert "TrendContentEngine" in http_mod.session().headers["User-Agent"]
    http_mod.reset_session()
