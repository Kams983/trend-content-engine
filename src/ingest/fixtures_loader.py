"""Load the frozen ingest fixtures instead of hitting the network.

``--use-fixtures`` swaps live ingest for these 120 items (4 sources × 30) so the
whole pipeline can be exercised offline and deterministically.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from ..util.logging_setup import kv

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
DEFAULT_SOURCES: tuple[str, ...] = ("hackernews", "arxiv", "github_trending", "reddit")


def _parse_timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def load_source(source: str, fixtures_dir: Path | None = None) -> list[dict]:
    """Load one source's fixture items, normalised to the common schema."""
    directory = fixtures_dir or FIXTURES_DIR
    path = directory / f"{source}.json"
    if not path.exists():
        logger.warning(kv("fixture_missing", source=source, path=str(path)))
        return []
    with path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    items: list[dict] = []
    for entry in raw:
        item = dict(entry)
        item["timestamp"] = _parse_timestamp(item.get("timestamp"))
        item["engagement"] = int(item.get("engagement") or 0)
        item["tags"] = list(item.get("tags") or [])
        items.append(item)
    return items


def load_fixtures(
    sources: Iterable[str] | None = None, fixtures_dir: Path | None = None
) -> dict[str, list[dict]]:
    """Return ``{source: [items]}`` for every requested fixture source."""
    result: dict[str, list[dict]] = {}
    for source in sources or DEFAULT_SOURCES:
        result[source] = load_source(source, fixtures_dir)
    total = sum(len(v) for v in result.values())
    logger.info(kv("fixtures_loaded", sources=len(result), items=total))
    return result
