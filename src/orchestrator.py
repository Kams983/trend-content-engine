"""Two-stage orchestrator.

**Stage A** (daily): ingest → cluster → score → draft → validate → store the
draft in the ``articles`` table (pending approval, or approved when
``REQUIRE_APPROVAL=false``).

**Stage B** (after approval): publish every approved article to every enabled
target exactly once, guarded by the ``publications`` table.

Every terminal state is an explicit :class:`~src.outcomes.Outcome` recorded in
``run_log`` with a reason. Every stage failure is caught, recorded and alerted.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from .alerting import alert, alert_failure
from .analysis.cluster import cluster
from .analysis.score import eligible_clusters, score_clusters
from .config import Settings
from .generate.draft_article import DraftOutcome, produce_article
from .generate.llm import build_llm
from .ingest import arxiv, github_trending, hackernews, reddit
from .ingest.fixtures_loader import DEFAULT_SOURCES, load_fixtures
from .ingest.normalize import normalize
from .outcomes import Outcome, Stage, as_outcome, is_failure
from .publish import get_publishers, preview_publication
from .publish.base import build_description
from .state import repo
from .util.logging_setup import kv
from .util.text import slugify

logger = logging.getLogger(__name__)

SOURCE_FETCHERS: dict[str, Callable[[Settings], list[dict]]] = {
    "hackernews": hackernews.fetch,
    "arxiv": arxiv.fetch,
    "github_trending": github_trending.fetch,
    "reddit": reddit.fetch,
}

#: Recorded for individual ingest failures. Deliberately NOT prefixed with
#: ``FAILED_`` so source-level problems stay non-fatal and do not alert.
SOURCE_FAILED = "SOURCE_FAILED"
SOURCE_OK = "SOURCE_OK"


@dataclass
class IngestResult:
    items: list[dict] = field(default_factory=list)
    per_source: dict[str, int] = field(default_factory=dict)
    failed: list[str] = field(default_factory=list)

    @property
    def sources_with_data(self) -> int:
        return sum(1 for count in self.per_source.values() if count > 0)


@dataclass
class StageResult:
    outcome: str
    reason: str = ""
    stage: str = ""
    details: str = ""
    article_id: int | None = None
    attempts: int = 0

    def __post_init__(self) -> None:
        # Normalise Outcome members to their plain string value.
        self.outcome = as_outcome(self.outcome)
        self.stage = as_outcome(self.stage)

    @property
    def failed(self) -> bool:
        return is_failure(self.outcome)


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


def ingest(settings: Settings, fetchers: dict | None = None) -> IngestResult:
    """Collect and normalise items. Individual source failures are non-fatal."""
    result = IngestResult()

    if settings.use_fixtures:
        fixtures = load_fixtures()
        for source, items in fixtures.items():
            result.per_source[source] = len(items)
            result.items.extend(items)
        logger.info(kv("ingest_fixtures", sources=len(fixtures), items=len(result.items)))
        return result

    fetchers = fetchers or SOURCE_FETCHERS
    for name, fetch_fn in fetchers.items():
        try:
            raw = fetch_fn(settings)
            items = normalize(raw, name)
        except Exception as exc:  # a single source must never kill the run
            logger.warning(kv("source_failed", source=name, error=str(exc)))
            result.per_source[name] = 0
            result.failed.append(name)
            continue
        result.per_source[name] = len(items)
        result.items.extend(items)
        logger.info(kv("source_ok", source=name, raw=len(raw), normalized=len(items)))

    return result


# ---------------------------------------------------------------------------
# Stage A
# ---------------------------------------------------------------------------


def make_slug(title: str, now: datetime, conn: sqlite3.Connection) -> str:
    """``YYYY-MM-DD-<slug>``, de-duplicated against existing posts."""
    base = f"{now.strftime('%Y-%m-%d')}-{slugify(title, max_len=60)}"
    slug = base
    counter = 2
    while repo.slug_exists(conn, slug):
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def article_payload(row: sqlite3.Row, settings: Settings) -> dict:
    """Article row → publisher payload."""
    try:
        sources = json.loads(row["sources_json"] or "[]")
    except (json.JSONDecodeError, TypeError):
        sources = []
    try:
        tags = json.loads(row["tags_json"] or "[]")
    except (json.JSONDecodeError, TypeError):
        tags = []
    return {
        "slug": row["slug"],
        "title": row["title"],
        "teaser": row["teaser"],
        "body_markdown": row["body"],
        "tags": tags,
        "sources": sources,
        "topic_id": row["topic_id"],
        "description": build_description(row["teaser"]),
    }


def stage_a(
    settings: Settings,
    conn: sqlite3.Connection,
    *,
    llm=None,
    fetchers: dict | None = None,
    now: datetime | None = None,
) -> StageResult:
    """Ingest → cluster → score → draft → store."""
    now = now or datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%SZ")

    def record(outcome: str, reason: str, stage: str, **extra) -> None:
        repo.record_run(
            conn, outcome=outcome, reason=reason, stage=stage, timestamp=now.isoformat(), **extra
        )

    # ---- same-day guard: never draft a second article for the same UTC day --
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    existing_today = [
        row
        for row in repo.articles_created_since(conn, day_start)
        if row["status"] in (repo.STATUS_PENDING, repo.STATUS_APPROVED, repo.STATUS_PUBLISHED)
    ]
    if existing_today:
        row = existing_today[0]
        outcome = {
            repo.STATUS_PENDING: Outcome.PENDING_APPROVAL,
            repo.STATUS_APPROVED: Outcome.DRAFTED,
            repo.STATUS_PUBLISHED: Outcome.PUBLISHED,
        }.get(row["status"], Outcome.PENDING_APPROVAL)
        reason = f"already drafted today: article #{row['id']} ({row['slug']}) status={row['status']}"
        record(outcome, reason, Stage.DRAFT)
        logger.info(kv("stage_a_skipped_same_day", article_id=int(row["id"]), status=row["status"]))
        return StageResult(outcome, reason, Stage.DRAFT, article_id=int(row["id"]))

    # ---- ingest -------------------------------------------------------
    try:
        ing = ingest(settings, fetchers)
    except Exception as exc:  # pragma: no cover - defensive
        reason = f"ingest crashed: {exc}"
        record(Outcome.failed(Stage.INGEST), reason, Stage.INGEST)
        alert_failure(Outcome.failed(Stage.INGEST), reason, settings, Stage.INGEST)
        return StageResult(Outcome.failed(Stage.INGEST), reason, Stage.INGEST)

    for name in ing.failed:
        record(SOURCE_FAILED, f"{name} returned no data", "ingest", source=name)
    for name, count in ing.per_source.items():
        record(SOURCE_OK, f"{count} items", "ingest", source=name, item_count=count)

    if ing.sources_with_data < settings.min_sources_with_data:
        reason = (
            f"only {ing.sources_with_data} source(s) returned data "
            f"(need {settings.min_sources_with_data}); failed={ing.failed}"
        )
        record(Outcome.SKIPPED_NO_DATA, reason, Stage.INGEST, item_count=len(ing.items))
        alert(f"{Outcome.SKIPPED_NO_DATA}: {reason}", settings)
        return StageResult(Outcome.SKIPPED_NO_DATA, reason, Stage.INGEST)

    if not ing.items:
        reason = "no items ingested"
        record(Outcome.SKIPPED_NO_DATA, reason, Stage.INGEST)
        alert(f"{Outcome.SKIPPED_NO_DATA}: {reason}", settings)
        return StageResult(Outcome.SKIPPED_NO_DATA, reason, Stage.INGEST)

    # ---- cluster ------------------------------------------------------
    try:
        clusters = cluster(ing.items, threshold=settings.cluster_threshold)
    except Exception as exc:
        reason = f"clustering failed: {exc}"
        record(Outcome.failed(Stage.CLUSTER), reason, Stage.CLUSTER, item_count=len(ing.items))
        alert_failure(Outcome.failed(Stage.CLUSTER), reason, settings, Stage.CLUSTER)
        return StageResult(Outcome.failed(Stage.CLUSTER), reason, Stage.CLUSTER)

    # ---- score --------------------------------------------------------
    try:
        ranked = score_clusters(conn, clusters, ing.items, settings, now=now)
    except Exception as exc:
        reason = f"scoring failed: {exc}"
        record(Outcome.failed(Stage.SCORE), reason, Stage.SCORE, item_count=len(ing.items))
        alert_failure(Outcome.failed(Stage.SCORE), reason, settings, Stage.SCORE)
        return StageResult(Outcome.failed(Stage.SCORE), reason, Stage.SCORE)

    eligible = eligible_clusters(ranked, limit=settings.max_draft_attempts)
    if not eligible:
        best = ranked[0] if ranked else None
        reason = (
            f"no eligible cluster (need >= {settings.min_cluster_items} items from "
            f">= {settings.min_cluster_sources} sources); best={best['label'][:60]!r} "
            f"items={best['count']} sources={len(best['sources'])} reason={best['ineligibility_reason']}"
            if best
            else "no clusters"
        )
        record(Outcome.SKIPPED_THIN, reason, Stage.SCORE, item_count=len(ing.items),
               trend=(best["label"] if best else ""), source=",".join(best["sources"]) if best else "")
        return StageResult(Outcome.SKIPPED_THIN, reason, Stage.SCORE)

    # ---- draft --------------------------------------------------------
    llm = llm or build_llm(settings)
    existing_titles = repo.existing_titles(conn)
    last_reason = "no attempt made"
    all_declined = True

    for attempt, entry in enumerate(eligible, 1):
        try:
            outcome: DraftOutcome = produce_article(entry["items"], settings, llm, existing_titles)
        except Exception as exc:  # pragma: no cover - defensive
            outcome = DraftOutcome(errors=[f"drafting crashed: {exc}"], attempts=attempt)

        if outcome.ok and outcome.article:
            all_declined = False
            article = outcome.article
            slug = make_slug(article["title"], now, conn)
            status = repo.STATUS_APPROVED if not settings.require_approval else repo.STATUS_PENDING
            article_id = repo.insert_article(
                conn,
                slug=slug,
                title=article["title"],
                teaser=article.get("teaser", ""),
                body=article.get("body_markdown", ""),
                topic_id=entry["topic_id"],
                cluster_label=entry["label"],
                sources=article.get("sources") or [],
                tags=article.get("tags") or [],
                status=status,
                run_id=run_id,
                created_at=now.isoformat(),
            )
            result_outcome = (
                Outcome.PENDING_APPROVAL if settings.require_approval else Outcome.DRAFTED
            )
            record(
                result_outcome,
                f"drafted from topic {entry['topic_id']} ({entry['count']} items / {len(entry['sources'])} sources)",
                "draft",
                trend=entry["label"],
                source=",".join(entry["sources"]),
                item_count=entry["count"],
            )
            if settings.require_approval and not settings.dry_run:
                from .publish.telegram_poster import send_approval_request

                payload = article_payload(repo.get_article(conn, article_id), settings)
                send_approval_request(payload, article_id, settings)
            logger.info(kv("stage_a_done", outcome=result_outcome, article_id=article_id, slug=slug))
            return StageResult(result_outcome, f"article #{article_id} ({slug})", "draft", article_id=article_id, attempts=attempt)

        if outcome.declined:
            last_reason = f"topic {entry['topic_id']}: model declined (sources too thin)"
            record(SOURCE_FAILED, last_reason, f"draft_attempt_{attempt}", trend=entry["label"], item_count=entry["count"])
        else:
            all_declined = False
            last_reason = f"topic {entry['topic_id']}: " + "; ".join(outcome.errors)[:400]
            record(
                Outcome.failed(Stage.DRAFT),
                last_reason,
                f"draft_attempt_{attempt}",
                trend=entry["label"],
                item_count=entry["count"],
            )

    final = Outcome.SKIPPED_THIN if all_declined else Outcome.failed(Stage.DRAFT)
    record(final, last_reason, Stage.DRAFT)
    alert_failure(final, last_reason, settings, Stage.DRAFT)
    logger.warning(kv("stage_a_finished", outcome=final, attempts=len(eligible)))
    return StageResult(final, last_reason, Stage.DRAFT, attempts=len(eligible))


# ---------------------------------------------------------------------------
# Stage B
# ---------------------------------------------------------------------------


def stage_b(
    settings: Settings,
    conn: sqlite3.Connection,
    *,
    publishers=None,
    article_ids: list[int] | None = None,
    now: datetime | None = None,
) -> StageResult:
    """Publish every approved article to every enabled target, exactly once."""
    now = now or datetime.now(timezone.utc)
    publishers = publishers or get_publishers(settings)

    approved = repo.articles_by_status(conn, repo.STATUS_APPROVED)
    if article_ids is not None:
        wanted = set(article_ids)
        approved = [row for row in approved if int(row["id"]) in wanted]

    if not approved:
        pending = repo.articles_by_status(conn, repo.STATUS_PENDING)
        if pending:
            reason = f"{len(pending)} article(s) awaiting approval"
            repo.record_run(conn, outcome=Outcome.PENDING_APPROVAL, reason=reason, stage=Stage.PUBLISH, timestamp=now.isoformat())
            return StageResult(Outcome.PENDING_APPROVAL, reason, Stage.PUBLISH)
        reason = "no approved articles to publish"
        repo.record_run(conn, outcome=Outcome.SKIPPED_THIN, reason=reason, stage=Stage.PUBLISH, timestamp=now.isoformat())
        return StageResult(Outcome.SKIPPED_THIN, reason, Stage.PUBLISH)

    published_any = False
    failed_any = False
    details: list[str] = []

    for row in approved:
        payload = article_payload(row, settings)
        article_ok = True
        for name, publish_fn in publishers:
            existing = repo.get_publication(conn, int(row["id"]), name)
            if existing is not None and existing["status"] == repo.PUB_OK:
                continue
            if settings.dry_run:
                logger.info(kv("dry_run_publish", article_id=int(row["id"]), preview=preview_publication(payload, settings, name)))
                continue
            try:
                result = publish_fn(payload, settings)
            except Exception as exc:  # a publisher must never raise, but be safe
                from .publish.base import PublishResult

                result = PublishResult(target=name, ok=False, error=str(exc))
            repo.record_publication(
                conn,
                article_id=int(row["id"]),
                target=name,
                status=result.status,
                external_id=result.external_id or "",
                url=result.url or "",
                error=result.error or "",
            )
            logger.info(
                kv("publish_result", article_id=int(row["id"]), target=name, status=result.status, url=result.url)
            )
            if result.ok:
                details.append(f"{name}:ok")
            elif result.skipped:
                details.append(f"{name}:skipped")
            else:
                article_ok = False
                details.append(f"{name}:failed")

        if settings.dry_run:
            continue
        if article_ok:
            repo.mark_published(conn, int(row["id"]), when=now.isoformat())
            published_any = True
        else:
            failed_any = True

    if settings.dry_run:
        reason = "dry run: nothing sent"
        repo.record_run(conn, outcome=Outcome.PENDING_APPROVAL, reason=reason, stage=Stage.PUBLISH, timestamp=now.isoformat())
        return StageResult(Outcome.PENDING_APPROVAL, reason, Stage.PUBLISH)

    if failed_any:
        reason = "some targets failed: " + ", ".join(details)
        repo.record_run(conn, outcome=Outcome.failed(Stage.PUBLISH), reason=reason, stage=Stage.PUBLISH, timestamp=now.isoformat())
        alert_failure(Outcome.failed(Stage.PUBLISH), reason, settings, Stage.PUBLISH)
        return StageResult(Outcome.failed(Stage.PUBLISH), reason, Stage.PUBLISH)

    reason = f"published {len(approved)} article(s): " + ", ".join(details)
    repo.record_run(conn, outcome=Outcome.PUBLISHED, reason=reason, stage=Stage.PUBLISH, timestamp=now.isoformat())
    logger.info(kv("stage_b_done", outcome=Outcome.PUBLISHED, details=reason[:200]))
    return StageResult(Outcome.PUBLISHED, reason, Stage.PUBLISH)


# ---------------------------------------------------------------------------
# Full run
# ---------------------------------------------------------------------------


def run(
    settings: Settings,
    conn: sqlite3.Connection,
    *,
    mode: str | None = None,
    llm=None,
    fetchers: dict | None = None,
    publishers=None,
    now: datetime | None = None,
) -> list[StageResult]:
    """Run the requested stage(s): ``draft``, ``publish`` or ``full``."""
    now = now or datetime.now(timezone.utc)
    mode = mode or settings.mode
    results: list[StageResult] = []

    if mode in {"draft", "full"}:
        results.append(stage_a(settings, conn, llm=llm, fetchers=fetchers, now=now))

    if mode in {"publish", "full"}:
        if settings.require_approval and not settings.dry_run:
            from .approval import handle_approvals

            handle_approvals(conn, settings)
        results.append(stage_b(settings, conn, publishers=publishers, now=now))

    return results
