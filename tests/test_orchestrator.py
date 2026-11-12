"""Stage A behaviour (source failures, skips, drafting) and Stage B logging."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from src.generate.llm import LLMError
from src.orchestrator import stage_a, stage_b
from src.publish.base import PublishResult
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


# ---------------------------------------------------------------------------
# Stage B: per-channel logging, idempotency, and the decline path
# ---------------------------------------------------------------------------

CHANNELS = ("site", "bluesky", "telegram")


class Recorder:
    """Fake publishers that count calls and return a scripted result per channel."""

    def __init__(self, **behaviour: str) -> None:
        self.behaviour = {name: behaviour.get(name, "ok") for name in CHANNELS}
        self.calls = {name: 0 for name in CHANNELS}

    def publishers(self) -> list[tuple[str, object]]:
        pairs: list[tuple[str, object]] = []
        for name in CHANNELS:

            def publish(payload, settings, name=name):
                self.calls[name] += 1
                state = self.behaviour[name]
                return PublishResult(
                    target=name,
                    ok=state == "ok",
                    skipped=state == "skipped",
                    url=f"https://example.test/{name}",
                )

            pairs.append((name, publish))
        return pairs


def approved_article(conn, *, label: str = "Diffusion language models") -> int:
    return repo.insert_article(
        conn,
        slug="2026-05-01-vector-search-at-scale",
        title="Vector search at scale",
        teaser="A deterministic teaser.",
        body="A body.",
        topic_id=1,
        cluster_label=label,
        sources=[{"title": "s", "url": "https://example.test/s"}],
        tags=["ai"],
        status=repo.STATUS_APPROVED,
        created_at=NOW.isoformat(),
    )


def test_stage_b_logs_per_channel_success_and_trend(conn, settings) -> None:
    article_id = approved_article(conn)
    recorder = Recorder()

    result = stage_b(settings, conn, publishers=recorder.publishers(), now=NOW)

    assert result.outcome == "PUBLISHED"
    row = repo.last_runs(conn, 1)[0]
    assert row["outcome"] == "PUBLISHED"
    assert (row["site_ok"], row["bluesky_ok"], row["telegram_ok"]) == (1, 1, 1)
    assert row["trend"] == "Diffusion language models"
    assert repo.get_article(conn, article_id)["status"] == repo.STATUS_PUBLISHED
    assert recorder.calls == {"site": 1, "bluesky": 1, "telegram": 1}


def test_stage_b_logs_partial_failure_per_channel(conn, settings) -> None:
    article_id = approved_article(conn)
    recorder = Recorder(bluesky="failed")

    result = stage_b(settings, conn, publishers=recorder.publishers(), now=NOW)

    assert result.outcome == "FAILED_PUBLISH"
    row = repo.last_runs(conn, 1)[0]
    assert (row["site_ok"], row["bluesky_ok"], row["telegram_ok"]) == (1, 0, 1)
    assert row["trend"] == "Diffusion language models"
    # The article stays approved so the next run can retry the failed channel.
    assert repo.get_article(conn, article_id)["status"] == repo.STATUS_APPROVED


def test_stage_b_skipped_channel_is_not_a_success(conn, settings) -> None:
    approved_article(conn)
    recorder = Recorder(bluesky="skipped")

    stage_b(settings, conn, publishers=recorder.publishers(), now=NOW)

    row = repo.last_runs(conn, 1)[0]
    assert (row["site_ok"], row["bluesky_ok"], row["telegram_ok"]) == (1, 0, 1)


def test_stage_b_rerun_retries_only_the_failed_channel(conn, settings) -> None:
    article_id = approved_article(conn)
    recorder = Recorder(bluesky="failed")
    first = stage_b(settings, conn, publishers=recorder.publishers(), now=NOW)
    assert first.outcome == "FAILED_PUBLISH"

    recorder.behaviour["bluesky"] = "ok"
    second = stage_b(settings, conn, publishers=recorder.publishers(), now=NOW)

    assert second.outcome == "PUBLISHED"
    assert recorder.calls == {"site": 1, "bluesky": 2, "telegram": 1}
    assert len(repo.publications_for(conn, article_id)) == 3
    row = repo.last_runs(conn, 1)[0]
    assert (row["site_ok"], row["bluesky_ok"], row["telegram_ok"]) == (1, 1, 1)


def test_stage_b_does_not_republish_an_already_published_article(conn, settings) -> None:
    article_id = approved_article(conn)
    recorder = Recorder()
    stage_b(settings, conn, publishers=recorder.publishers(), now=NOW)

    rerun = stage_b(settings, conn, publishers=recorder.publishers(), now=NOW)

    assert rerun.outcome == "SKIPPED_THIN"
    assert recorder.calls == {"site": 1, "bluesky": 1, "telegram": 1}
    assert len(repo.publications_for(conn, article_id)) == 3


def test_declined_generation_publishes_nothing(conn, live_settings, declining_llm) -> None:
    drafted = stage_a(live_settings, conn, llm=declining_llm, fetchers=healthy_fetchers(), now=NOW)
    assert drafted.outcome == "SKIPPED_THIN"

    recorder = Recorder()
    published = stage_b(live_settings, conn, publishers=recorder.publishers(), now=NOW)

    assert published.outcome == "SKIPPED_THIN"
    assert recorder.calls == {"site": 0, "bluesky": 0, "telegram": 0}
    assert conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM publications").fetchone()[0] == 0
