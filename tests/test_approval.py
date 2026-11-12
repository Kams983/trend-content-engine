"""Telegram approval callbacks: authorization, parsing and state changes."""

from __future__ import annotations

from dataclasses import replace

import pytest

from src import approval
from src.approval import apply_decision, dispatch_workflow, is_authorized, parse_callback, process_update
from src.approval import watch_for_approvals
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


def _make_article(conn, slug: str = "s") -> int:
    return repo.insert_article(
        conn, slug=slug, title="T", teaser="", body="b", topic_id=1, cluster_label="", sources=[], tags=[]
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


# --- decisions, dispatch and the listener ----------------------------------


def test_apply_decision_approves_and_rejects(conn) -> None:
    first = _make_article(conn, "first")
    second = _make_article(conn, "second")
    assert apply_decision(conn, "approve", first) == "approved"
    assert repo.get_article(conn, first)["status"] == repo.STATUS_APPROVED
    assert apply_decision(conn, "reject", second) == "rejected"
    assert repo.get_article(conn, second)["status"] == repo.STATUS_REJECTED


def test_apply_decision_is_idempotent_and_reports_missing(conn) -> None:
    article_id = _make_article(conn)
    assert apply_decision(conn, "reject", article_id) == "rejected"
    assert apply_decision(conn, "approve", article_id) == "noop"
    assert apply_decision(conn, "approve", 9999) == "missing"


def test_dispatch_workflow_sends_the_decision_as_inputs(monkeypatch) -> None:
    seen: dict = {}

    def fake_request(method, url, **kwargs):
        seen.update(method=method, url=url, kwargs=kwargs)
        return object()

    monkeypatch.setattr(approval, "request", fake_request)
    ok = dispatch_workflow(
        "publish.yml",
        inputs={"action": "approve", "article_id": "15"},
        token="t0ken",
        repo="owner/repo",
    )
    assert ok is True
    assert seen["method"] == "POST"
    assert seen["url"] == (
        "https://api.github.com/repos/owner/repo/actions/workflows/publish.yml/dispatches"
    )
    assert seen["kwargs"]["json"] == {
        "ref": "main",
        "inputs": {"action": "approve", "article_id": "15"},
    }
    assert seen["kwargs"]["headers"]["Authorization"] == "Bearer t0ken"


def test_dispatch_without_token_or_repository_fails(monkeypatch) -> None:
    monkeypatch.delenv("GH_DISPATCH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert dispatch_workflow("publish.yml") is False


def test_listener_dispatches_each_admin_tap_once(admin_settings) -> None:
    dispatched: list[tuple[str, int]] = []
    ticks = {"now": 0.0}

    def clock() -> float:
        ticks["now"] += 1.0
        return ticks["now"]

    real = _update("42", "approve:15")
    intruder = _update("999", "approve:15")
    intruder["update_id"] = 2

    counts = watch_for_approvals(
        admin_settings,
        duration=4,
        updates=lambda: [real, intruder],
        dispatch=lambda action, article_id: dispatched.append((action, article_id)) or True,
        clock=clock,
        pause=lambda seconds: None,
    )

    assert dispatched == [("approve", 15)]
    assert counts["dispatched"] == 1
    assert counts["ignored"] >= 1
    assert counts["duplicate"] >= 1


def test_listener_without_telegram_config_reports_error(settings) -> None:
    counts = watch_for_approvals(replace(settings, telegram_bot_token=""), duration=5, clock=lambda: 0.0)
    assert counts == {"error": 1}
