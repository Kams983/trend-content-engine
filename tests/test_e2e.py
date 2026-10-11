"""End-to-end: the whole pipeline on fixtures with mocked LLM and publishers."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from src.orchestrator import run
from src.publish.base import PublishResult
from src.state import repo
from src.state.db import init_db

NOW = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)


def make_publishers(calls: list[str]):
    def site(payload, settings):
        calls.append("site")
        return PublishResult(target="site", ok=True, url=f"/posts/{payload['slug']}", external_id="path")

    def bluesky(payload, settings):
        calls.append("bluesky")
        return PublishResult(target="bluesky", ok=True, url="https://bsky.app/x", external_id="rkey")

    return [("site", site), ("bluesky", bluesky)]


def test_full_pipeline_publishes_once_and_reruns_are_noops(tmp_path, fake_llm) -> None:
    settings = _settings(tmp_path)
    conn = init_db(settings.db_path)
    calls: list[str] = []

    results = run(settings, conn, llm=fake_llm, publishers=make_publishers(calls), now=NOW)

    assert results[-1].outcome == "PUBLISHED"
    assert calls == ["site", "bluesky"]

    published = repo.articles_by_status(conn, repo.STATUS_PUBLISHED)
    assert len(published) == 1
    article = published[0]

    # Phase 2 acceptance: the drafted cluster was rich and cross-source.
    sources = json.loads(article["sources_json"])
    assert len(sources) >= 3
    assert len({item["source"] for item in sources}) >= 2
    assert article["topic_id"] is not None

    publications = repo.publications_for(conn, int(article["id"]))
    assert {row["target"] for row in publications} == {"site", "bluesky"}

    outcomes = {row["outcome"] for row in repo.last_runs(conn, 100)}
    assert "PUBLISHED" in outcomes

    # --- same-day rerun: nothing published twice, no second article ---------
    calls.clear()
    rerun = run(settings, conn, llm=fake_llm, publishers=make_publishers(calls), now=NOW + timedelta(hours=3))

    assert calls == []
    assert len(repo.articles_by_status(conn, repo.STATUS_PUBLISHED)) == 1
    assert conn.execute("SELECT COUNT(*) FROM publications").fetchone()[0] == 2
    assert rerun[0].outcome == "PUBLISHED"  # same-day guard reports the existing article

    conn.close()


def test_dry_run_sends_nothing_and_records_nothing(tmp_path, fake_llm) -> None:
    settings = _settings(tmp_path, dry_run=True)
    conn = init_db(settings.db_path)
    calls: list[str] = []

    run(settings, conn, llm=fake_llm, publishers=make_publishers(calls), now=NOW)

    assert calls == []
    assert conn.execute("SELECT COUNT(*) FROM publications").fetchone()[0] == 0
    assert repo.articles_by_status(conn, repo.STATUS_PUBLISHED) == []
    conn.close()


def test_publish_stage_retries_only_failed_targets(tmp_path, fake_llm) -> None:
    settings = _settings(tmp_path)
    conn = init_db(settings.db_path)
    state = {"bluesky_fails": True}

    def site(payload, settings):
        return PublishResult(target="site", ok=True, url="u")

    def bluesky(payload, settings):
        if state["bluesky_fails"]:
            return PublishResult(target="bluesky", ok=False, error="502")
        return PublishResult(target="bluesky", ok=True, url="b")

    publishers = [("site", site), ("bluesky", bluesky)]
    first = run(settings, conn, llm=fake_llm, publishers=publishers, now=NOW)
    assert first[-1].outcome == "FAILED_PUBLISH"
    article = repo.articles_by_status(conn, repo.STATUS_APPROVED)[0]
    assert repo.get_publication(conn, int(article["id"]), "site")["status"] == "ok"

    # Second attempt with working Bluesky: only the failed target is retried.
    state["bluesky_fails"] = False
    calls: list[str] = []

    def tracking_site(payload, settings):
        calls.append("site")
        return PublishResult(target="site", ok=True, url="u")

    def tracking_bluesky(payload, settings):
        calls.append("bluesky")
        return PublishResult(target="bluesky", ok=True, url="b")

    second = run(
        settings,
        conn,
        llm=fake_llm,
        publishers=[("site", tracking_site), ("bluesky", tracking_bluesky)],
        now=NOW + timedelta(minutes=30),
    )
    assert second[-1].outcome == "PUBLISHED"
    assert calls == ["bluesky"]  # site was already recorded as ok
    assert len(repo.articles_by_status(conn, repo.STATUS_PUBLISHED)) == 1
    conn.close()


def _settings(tmp_path, dry_run: bool = False):
    from src.config import Settings

    return Settings(
        db_path=tmp_path / "e2e.sqlite",
        content_posts_dir=tmp_path / "posts",
        use_fixtures=True,
        dry_run=dry_run,
        require_approval=False,
        site_url="https://example.test",
    )
