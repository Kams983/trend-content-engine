"""Stage A behaviour: non-fatal source failures, skips, failures and the guard."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from src.generate.llm import LLMError
from src.orchestrator import stage_a
from src.state import repo

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
SHARED = "shared topic about vector database indexing performance and latency"


@pytest.fixture
def live_settings(settings):
    """Settings that take the live-ingest path so injected fetchers are used."""
    return replace(settings, use_fixtures=False)


def hn_raw(count: int, text: str) -> list[dict]:
    return [
        {"id": i, "time": 1700000000 + i, "title": text, "text": text, "score": 10 * (i + 1), "type": "story"}
        for i in range(count)
    ]


def rd_raw(count: int, text: str) -> list[dict]:
    return [
        {"title": text, "url": f"https://reddit.test/{i}", "updated": "2026-01-01T00:00:00Z", "content": text}
        for i in range(count)
    ]


def healthy_fetchers():
    def boom(_settings):
        raise RuntimeError("source is down")

    return {
        "hackernews": lambda s: hn_raw(3, SHARED),
        "reddit": lambda s: rd_raw(3, SHARED),
        "arxiv": boom,
    }


def test_single_source_failure_is_non_fatal(conn, live_settings, fake_llm) -> None:
    result = stage_a(live_settings, conn, llm=fake_llm, fetchers=healthy_fetchers(), now=NOW)
    assert result.outcome == "DRAFTED"
    rows = repo.last_runs(conn, 50)
    assert any(row["outcome"] == "SOURCE_FAILED" and row["source"] == "arxiv" for row in rows)
    assert any(row["outcome"] == "SOURCE_OK" for row in rows)
    # The run still produced exactly one article.
    assert len(repo.articles_by_status(conn, repo.STATUS_APPROVED)) == 1


def test_fewer_than_two_sources_skips_no_data_and_alerts(conn, live_settings, fake_llm, monkeypatch) -> None:
    alerts: list[str] = []
    monkeypatch.setattr("src.orchestrator.alert", lambda message, s: alerts.append(message) or True)

    def boom(_settings):
        raise RuntimeError("down")

    fetchers = {"hackernews": boom, "reddit": boom, "arxiv": boom}
    result = stage_a(live_settings, conn, llm=fake_llm, fetchers=fetchers, now=NOW)

    assert result.outcome == "SKIPPED_NO_DATA"
    assert alerts and "SKIPPED_NO_DATA" in alerts[0]
    assert not repo.articles_by_status(conn, repo.STATUS_APPROVED)


def test_no_eligible_cluster_is_skipped_thin(conn, live_settings, fake_llm) -> None:
    fetchers = {
        "hackernews": lambda s: [
            {"id": 1, "time": 1700000000, "title": "Alpha beta gamma unique topic", "score": 3, "type": "story"}
        ],
        "reddit": lambda s: [
            {"title": "Completely unrelated zeta quantum lute", "url": "https://r.test/1", "updated": "2026-01-01T00:00:00Z", "content": "body"}
        ],
    }
    result = stage_a(live_settings, conn, llm=fake_llm, fetchers=fetchers, now=NOW)
    assert result.outcome == "SKIPPED_THIN"
    assert "eligible" in result.reason


def test_declining_model_across_all_clusters_is_skipped_thin(conn, live_settings, declining_llm) -> None:
    result = stage_a(live_settings, conn, llm=declining_llm, fetchers=healthy_fetchers(), now=NOW)
    assert result.outcome == "SKIPPED_THIN"
    assert not repo.articles_by_status(conn, repo.STATUS_APPROVED)


def test_llm_error_is_a_failed_draft_and_alerts(conn, live_settings, monkeypatch) -> None:
    alerts: list[str] = []
    monkeypatch.setattr("src.orchestrator.alert_failure", lambda o, r, s, stage="": alerts.append(o) or True)

    class BoomLLM:
        def complete(self, *args, **kwargs):
            raise LLMError("groq is down")

    result = stage_a(live_settings, conn, llm=BoomLLM(), fetchers=healthy_fetchers(), now=NOW)
    assert result.outcome == "FAILED_DRAFT"
    assert alerts == ["FAILED_DRAFT"]
    assert any(row["stage"].startswith("draft_attempt") for row in repo.last_runs(conn, 50))


def test_every_attempt_is_recorded(conn, live_settings, declining_llm) -> None:
    stage_a(live_settings, conn, llm=declining_llm, fetchers=healthy_fetchers(), now=NOW)
    stages = [row["stage"] for row in repo.last_runs(conn, 50)]
    assert any(stage.startswith("draft_attempt_1") for stage in stages)


def test_second_run_on_the_same_day_does_not_draft_again(conn, live_settings, fake_llm) -> None:
    first = stage_a(live_settings, conn, llm=fake_llm, fetchers=healthy_fetchers(), now=NOW)
    assert first.outcome == "DRAFTED"
    second = stage_a(live_settings, conn, llm=fake_llm, fetchers=healthy_fetchers(), now=NOW)
    assert second.outcome == "DRAFTED"
    assert len(repo.articles_by_status(conn, repo.STATUS_APPROVED)) == 1
    assert "already drafted today" in second.reason


def test_requires_approval_sets_pending(conn, live_settings, fake_llm) -> None:
    approving = replace(live_settings, require_approval=True, telegram_bot_token="", telegram_admin_chat_id="")
    result = stage_a(approving, conn, llm=fake_llm, fetchers=healthy_fetchers(), now=NOW)
    assert result.outcome == "PENDING_APPROVAL"
    assert len(repo.articles_by_status(conn, repo.STATUS_PENDING)) == 1
