"""Turn post traffic into per-source trust weights.

Run it after the site has some history::

    python -m src.learn.feedback [--traffic config/traffic.json] [--out config/settings.yaml]

Inputs
------
* **Traffic** — a JSON object mapping a published post's slug to its pageview
  count, e.g. ``{"2026-11-09-diffusion-models": 214}``. The site build has no
  analytics wired up, so this file is either exported from whatever counts the
  views or maintained by hand (``TRAFFIC_PATH``, default
  ``config/traffic.json``). A published post missing from the file counts as
  zero views — an ignored post.
* **The article store** — ``trend_store.sqlite``'s ``articles`` table, for each
  published post's date and the sources its cluster came from. (``run_log``
  records the same trend/source strings per stage, but only ``articles`` links a
  post to the views it earned.)

Output
------
``config/settings.yaml`` (``SOURCE_WEIGHTS_PATH``)::

    source_trust:
      arxiv: 0.86
      hackernews: 1.12

A source's weight is its mean attributed views divided by the mean views of
every post in the window, clamped to ``[0.5, 1.5]``. ``score.py`` multiplies a
cluster's score by the mean weight of its sources, so sources whose trends
produced posts people read get boosted and sources whose posts were ignored get
damped. With no traffic at all every weight is 1.0, leaving scoring unchanged.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from ..config import DEFAULT_DB_PATH, REPO_ROOT
from ..state import db, repo
from ..util.logging_setup import kv

logger = logging.getLogger(__name__)

#: How much history the signal looks at, and how far it may move a score.
WINDOW_DAYS = 30
MIN_WEIGHT = 0.5
MAX_WEIGHT = 1.5
NEUTRAL_WEIGHT = 1.0

DEFAULT_TRAFFIC_PATH = REPO_ROOT / "config" / "traffic.json"
DEFAULT_WEIGHTS_PATH = REPO_ROOT / "config" / "settings.yaml"


def traffic_path() -> Path:
    """Where the pageview counts live (``TRAFFIC_PATH`` overrides the default)."""
    return Path(os.environ.get("TRAFFIC_PATH") or DEFAULT_TRAFFIC_PATH)


def weights_path() -> Path:
    """Where the weights are written (``SOURCE_WEIGHTS_PATH`` overrides the default)."""
    return Path(os.environ.get("SOURCE_WEIGHTS_PATH") or DEFAULT_WEIGHTS_PATH)


# ---------------------------------------------------------------------------
# Traffic
# ---------------------------------------------------------------------------


def load_traffic(path: Path | str | None = None) -> dict[str, int]:
    """Read ``{slug: views}``. A missing or malformed file yields no data."""
    target = Path(path) if path is not None else traffic_path()
    if not target.exists():
        logger.warning(kv("traffic_missing", path=str(target)))
        return {}
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(kv("traffic_unreadable", path=str(target), error=str(exc)))
        return {}
    if not isinstance(raw, dict):
        logger.warning(kv("traffic_bad_shape", path=str(target), note="expected an object of slug→views"))
        return {}

    views: dict[str, int] = {}
    for slug, value in raw.items():
        try:
            views[str(slug)] = max(0, int(value))
        except (TypeError, ValueError):
            continue
    return views


# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------


def _published_at(value: object) -> datetime | None:
    try:
        when = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _sources_of(sources_json: object) -> list[str]:
    """Distinct source names in an article's stored cluster sources."""
    try:
        items = json.loads(str(sources_json or "[]"))
    except (json.JSONDecodeError, TypeError):
        return []
    names: list[str] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("source") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def source_trust(
    conn,
    traffic: dict[str, int],
    *,
    window_days: int = WINDOW_DAYS,
    now: datetime | None = None,
) -> dict[str, float]:
    """Mean attributed views per source, normalised against the window mean.

    A post's views are split evenly across the distinct sources in its cluster,
    so a post built from twelve sources does not credit each of them fully.
    """
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=window_days)
    rows = conn.execute(
        "SELECT slug, sources_json, published_at FROM articles WHERE status = ?",
        (repo.STATUS_PUBLISHED,),
    ).fetchall()

    credits: dict[str, float] = defaultdict(float)
    posts: dict[str, int] = defaultdict(int)
    total_views = 0
    considered = 0

    for row in rows:
        when = _published_at(row["published_at"])
        if when is None or when < since:
            continue
        sources = _sources_of(row["sources_json"])
        if not sources:
            continue
        views = int(traffic.get(row["slug"], 0))
        considered += 1
        total_views += views
        share = views / len(sources)
        for source in sources:
            credits[source] += share
            posts[source] += 1

    if considered == 0:
        return {}
    if total_views == 0:
        # Nothing was read (or analytics are not wired up yet): stay neutral
        # rather than punishing every source equally.
        return {source: NEUTRAL_WEIGHT for source in posts}

    mean_views = total_views / considered
    weights: dict[str, float] = {}
    for source, count in posts.items():
        raw = (credits[source] / count) / mean_views
        weights[source] = round(min(MAX_WEIGHT, max(MIN_WEIGHT, raw)), 3)
    return weights


def trust_for(sources: list[str] | tuple[str, ...], weights: dict[str, float]) -> float:
    """Mean trust of a cluster's sources (1.0 per unknown source)."""
    if not sources or not weights:
        return NEUTRAL_WEIGHT
    return sum(weights.get(source, NEUTRAL_WEIGHT) for source in sources) / len(sources)


# ---------------------------------------------------------------------------
# Persistence (config/settings.yaml)
# ---------------------------------------------------------------------------


def load_weights(path: Path | str | None = None) -> dict[str, float]:
    """Read ``source_trust`` from the weights file. Missing file → ``{}``."""
    target = Path(path) if path is not None else weights_path()
    if not target.exists():
        return {}
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning(kv("weights_unreadable", path=str(target), error=str(exc)))
        return {}
    raw = data.get("source_trust") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return {}

    weights: dict[str, float] = {}
    for source, value in raw.items():
        try:
            weights[str(source)] = float(value)
        except (TypeError, ValueError):
            continue
    return weights


def write_weights(
    weights: dict[str, float],
    *,
    path: Path | str | None = None,
    window_days: int = WINDOW_DAYS,
    articles_considered: int = 0,
    now: datetime | None = None,
) -> Path:
    """Write the weights file, replacing any previous one."""
    target = Path(path) if path is not None else weights_path()
    now = now or datetime.now(timezone.utc)
    payload = {
        "generated_at": now.isoformat(timespec="seconds"),
        "window_days": int(window_days),
        "articles_considered": int(articles_considered),
        "source_trust": {source: round(float(weight), 3) for source, weight in sorted(weights.items())},
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(payload, sort_keys=False, default_flow_style=False, allow_unicode=True)
    target.write_text(
        "# Generated by `python -m src.learn.feedback`; rewritten on every run.\n" + body,
        encoding="utf-8",
    )
    return target


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.learn.feedback",
        description="Compute per-source trust weights from post traffic.",
    )
    parser.add_argument("--traffic", default=None, help=f"pageview JSON (default: {DEFAULT_TRAFFIC_PATH})")
    parser.add_argument("--out", default=None, help=f"weights YAML (default: {DEFAULT_WEIGHTS_PATH})")
    parser.add_argument("--db", default=None, help="SQLite database (default: DB_PATH or trend_store.sqlite)")
    parser.add_argument("--window-days", type=int, default=WINDOW_DAYS, help="history window (default: 30)")
    args = parser.parse_args(argv)

    db_file = Path(args.db) if args.db else Path(os.environ.get("DB_PATH") or DEFAULT_DB_PATH)
    now = datetime.now(timezone.utc)
    traffic = load_traffic(args.traffic)

    conn = db.init_db(db_file)
    try:
        weights = source_trust(conn, traffic, window_days=args.window_days, now=now)
        since = (now - timedelta(days=args.window_days)).isoformat()
        considered = conn.execute(
            "SELECT COUNT(*) FROM articles WHERE status = ? AND published_at >= ?",
            (repo.STATUS_PUBLISHED, since),
        ).fetchone()[0]
    finally:
        conn.close()

    target = write_weights(
        weights,
        path=args.out,
        window_days=args.window_days,
        articles_considered=considered,
        now=now,
    )

    print(f"read {len(traffic)} traffic row(s); {considered} post(s) published in the last {args.window_days}d")
    print(f"wrote {len(weights)} source weight(s) to {target}")
    for source, weight in sorted(weights.items()):
        print(f"  {source:<16} {weight:.3f}")
    if not weights:
        print("note: no published posts in the window — every source stays at 1.0")
    elif all(weight == NEUTRAL_WEIGHT for weight in weights.values()):
        print("note: no views recorded — weights are neutral (1.0)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
