"""Daily pipeline: ingest → normalize → cluster → score → generate → publish.

Run:  python -m src.main
  or: python src/main.py

A straight top-to-bottom sequence — no framework, easy to debug.
"""

import logging
import sqlite3
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ingest.hackernews import fetch as hn_fetch
from src.ingest.arxiv import fetch as arxiv_fetch
from src.ingest.github_trending import fetch as gh_fetch
from src.ingest.reddit import fetch as rd_fetch
from src.ingest.normalize import normalize
from src.analysis.cluster import cluster
from src.analysis.score import score
from src.generate.draft_article import draft_article
from src.publish.site_publisher import site_publisher
from src.publish.bluesky_poster import bluesky_poster
from src.publish.telegram_poster import telegram_poster

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("main")

DB_PATH = Path(__file__).resolve().parent.parent / "trend_store.sqlite"
SITE_URL = ""  # set to your deployed URL for working links in posts


def _log_run(
    conn: sqlite3.Connection,
    trend: str,
    source: str,
    item_count: int,
    site_ok: bool,
    bluesky_ok: bool,
    telegram_ok: bool,
) -> None:
    """Write a run record to the run_log table."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS run_log (
               id         INTEGER PRIMARY KEY AUTOINCREMENT,
               timestamp  TEXT NOT NULL,
               trend      TEXT NOT NULL,
               source     TEXT NOT NULL,
               item_count INTEGER NOT NULL,
               site_ok    INTEGER NOT NULL,
               bluesky_ok INTEGER NOT NULL,
               telegram_ok INTEGER NOT NULL
           )"""
    )
    conn.execute(
        "INSERT INTO run_log "
        "(timestamp, trend, source, item_count, site_ok, bluesky_ok, telegram_ok) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            datetime.now(timezone.utc).isoformat(),
            trend,
            source,
            item_count,
            int(site_ok),
            int(bluesky_ok),
            int(telegram_ok),
        ),
    )
    conn.commit()


def main() -> None:
    now = datetime.now(timezone.utc)
    log.info("=== Pipeline started %s ===", now.strftime("%Y-%m-%d %H:%M:%S UTC"))

    # ------------------------------------------------------------------
    # 1. INGEST
    # ------------------------------------------------------------------
    log.info("Ingesting sources...")
    sources = {
        "hackernews": hn_fetch,
        "arxiv": arxiv_fetch,
        "github_trending": gh_fetch,
        "reddit": rd_fetch,
    }

    all_items: list[dict] = []
    for source_name, fetch_fn in sources.items():
        try:
            raw = fetch_fn()
            items = normalize(raw, source_name)
            log.info("  %s: %d raw → %d normalized", source_name, len(raw), len(items))
            all_items.extend(items)
        except Exception as exc:
            log.error("  %s fetch failed: %s", source_name, exc)

    if not all_items:
        log.warning("No items ingested — exiting cleanly.")
        return

    log.info("Total items: %d", len(all_items))

    # ------------------------------------------------------------------
    # 2. CLUSTER
    # ------------------------------------------------------------------
    log.info("Clustering...")
    clusters = cluster(all_items, threshold=0.45)
    log.info("  %d clusters formed", len(clusters))

    # ------------------------------------------------------------------
    # 3. SCORE
    # ------------------------------------------------------------------
    log.info("Scoring clusters...")
    ranked = score(clusters, top_n=10, db_path=DB_PATH)
    if not ranked:
        log.warning("No ranked clusters — exiting cleanly.")
        return

    top = ranked[0]
    log.info(
        "  #1 trend: score=%.2f vel=%.2f nov=%.1f items=%d | %s",
        top["score"], top["velocity"], top["novelty"],
        top["count"], top["label"][:60],
    )

    # ------------------------------------------------------------------
    # 4. GENERATE
    # ------------------------------------------------------------------
    log.info("Generating article...")
    article = draft_article(top["items"])

    if article is None:
        log.info("Not enough substance for an article — skipping day.")
        # Still log the run so we know it happened
        conn = sqlite3.connect(str(DB_PATH))
        _log_run(conn, top["label"], top["sources"], top["count"], False, False, False)
        conn.close()
        log.info("=== Pipeline finished (skipped) ===")
        return

    log.info("  Title: %s", article["title"])
    log.info("  Teaser (%d chars): %s", len(article["teaser"]), article["teaser"][:80])

    # ------------------------------------------------------------------
    # 5. PUBLISH TO SITE
    # ------------------------------------------------------------------
    log.info("Publishing to site...")
    post_path = site_publisher(article, date=now)
    site_ok = post_path is not None
    if site_ok:
        log.info("  Written: %s", post_path)
    else:
        log.warning("  Site publish failed")

    # ------------------------------------------------------------------
    # 6. POST TO BLUESKY
    # ------------------------------------------------------------------
    log.info("Posting to Bluesky...")
    bluesky_ok = bluesky_poster(article, site_url=SITE_URL)
    log.info("  Bluesky: %s", "OK" if bluesky_ok else "FAILED")

    # ------------------------------------------------------------------
    # 7. POST TO TELEGRAM
    # ------------------------------------------------------------------
    log.info("Posting to Telegram...")
    telegram_ok = telegram_poster(article, site_url=SITE_URL)
    log.info("  Telegram: %s", "OK" if telegram_ok else "FAILED")

    # ------------------------------------------------------------------
    # 8. LOG RUN
    # ------------------------------------------------------------------
    conn = sqlite3.connect(str(DB_PATH))
    _log_run(conn, top["label"], top["sources"], top["count"], site_ok, bluesky_ok, telegram_ok)
    conn.close()

    log.info(
        "=== Pipeline finished: site=%s bluesky=%s telegram=%s ===",
        "OK" if site_ok else "FAIL",
        "OK" if bluesky_ok else "FAIL",
        "OK" if telegram_ok else "FAIL",
    )


if __name__ == "__main__":
    main()
