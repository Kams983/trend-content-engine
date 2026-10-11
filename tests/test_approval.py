"""Telegram approval callbacks: authorization, parsing and state changes."""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.approval import is_authorized, parse_callback, process_update
from src.publish import telegram_poster as tg
from src.state import repo


@pytest.fixture
def admin_settings(settings):
    return replace(
        settings,
        telegram_bot_token="123:abc",
        telegram_admin_chat_id="42",
        telegram_channel_id="@channel",
    )


@pytest.fixture
def stub_telegram(monkeypatch):
    """Replace the outbound Telegram calls with recorders."""
    calls = {"answered": [], "cleared": []}
    monkeypatch.setattr(tg, "answer_callback", lambda settings, cid, text="": calls["answered"].append((cid, text)) or True)
    monkeypatch.setattr(
        tg, "clear_approval_buttons", lambda settings, chat_id, message_id, text="": calls["cleared"].append(text) or True
    )
    return calls


def _update(chat_id: str, data: str) -> dict:
    return {
        "update_id": 1,
        "callback_query": {
            "id": "cb1",
            "data": data,
            "message": {"message_id": 7, "chat": {"id": chat_id}},
        },
    }


def _make_article(conn) -> int:
    return repo.insert_article(
        conn, slug="s", title="T", teaser="", body="b", topic_id=1, cluster_label="", sources=[], tags=[]
    )


def test_is_authorized_only_for_admin_chat(admin_settings) -> None:
    assert is_authorized(_update("42", "approve:1"), admin_settings) is True
    assert is_authorized(_update("999", "approve:1"), admin_settings) is False


def test_is_authorized_false_without_admin_configured(settings) -> None:
    assert is_authorized(_update("42", "approve:1"), replace(settings, telegram_admin_chat_id="")) is False


@pytest.mark.parametrize(
    ("data", "expected"),
    [("approve:12", ("approve", 12)), ("reject:3", ("reject", 3)), ("bogus:x", None), ("", None), ("approve:", None)],
)
def test_parse_callback(data, expected) -> None:
    assert parse_callback(data) == expected


def test_non_admin_callback_is_rejected(conn, admin_settings, stub_telegram) -> None:
    article_id = _make_article(conn)
    status = process_update(conn, _update("999", f"approve:{article_id}"), admin_settings)
    assert status == "unauthorized"
    assert repo.get_article(conn, article_id)["status"] == repo.STATUS_PENDING
    assert any("Not authorized" in text for _, text in stub_telegram["answered"])


def test_admin_approval_sets_status_approved(conn, admin_settings, stub_telegram) -> None:
    article_id = _make_article(conn)
    status = process_update(conn, _update("42", f"approve:{article_id}"), admin_settings)
    assert status == "approved"
    assert repo.get_article(conn, article_id)["status"] == repo.STATUS_APPROVED
    assert stub_telegram["cleared"]


def test_admin_rejection_sets_status_rejected(conn, admin_settings, stub_telegram) -> None:
    article_id = _make_article(conn)
    status = process_update(conn, _update("42", f"reject:{article_id}"), admin_settings)
    assert status == "rejected"
    assert repo.get_article(conn, article_id)["status"] == repo.STATUS_REJECTED


def test_approval_for_missing_article_returns_missing(conn, admin_settings, stub_telegram) -> None:
    assert process_update(conn, _update("42", "approve:9999"), admin_settings) == "missing"


def test_double_approval_is_a_noop(conn, admin_settings, stub_telegram) -> None:
    article_id = _make_article(conn)
    process_update(conn, _update("42", f"approve:{article_id}"), admin_settings)
    repo.set_article_status(conn, article_id, repo.STATUS_PUBLISHED)
    assert process_update(conn, _update("42", f"approve:{article_id}"), admin_settings) == "noop"


def test_non_callback_update_is_ignored(conn, admin_settings, stub_telegram) -> None:
    assert process_update(conn, {"update_id": 2}, admin_settings) == "ignored"
