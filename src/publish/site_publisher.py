"""Write an article to ``site/content/posts/<slug>.md`` with full frontmatter.

The Astro content schema (see ``site/src/content.config.ts``) requires
``title``, ``description``, ``tags``, ``ai_assisted``, ``sources``, ``slug`` and
``topic_id``; a malformed post fails the site build, which is intentional.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .base import PublishResult, as_publication_article, post_url

logger = logging.getLogger(__name__)


def _yaml_str(value: str) -> str:
    """A double-quoted YAML scalar (JSON strings are valid YAML)."""
    return json.dumps(str(value), ensure_ascii=False)


def build_frontmatter(article: dict, date: datetime | None = None) -> str:
    """Render YAML frontmatter for the Astro content collection."""
    dt = date or article.get("date") or datetime.now(timezone.utc)
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    tags = [str(t) for t in (article.get("tags") or [])]
    lines = [
        "---",
        f"title: {_yaml_str(article.get('title', ''))}",
        f"description: {_yaml_str(article.get('description', ''))}",
        f"date: {dt.isoformat()}",
        f"slug: {_yaml_str(article.get('slug', ''))}",
        f"topic_id: {int(article.get('topic_id') or 0)}",
        "ai_assisted: true",
        "tags:",
    ]
    if tags:
        lines.extend(f"  - {_yaml_str(t)}" for t in tags)
    else:
        lines.append("  - untagged")
    lines.append("sources:")
    sources = article.get("sources") or []
    if sources:
        for item in sources:
            lines.append(f"  - title: {_yaml_str(item.get('title', ''))}")
            lines.append(f"    url: {_yaml_str(item.get('url', ''))}")
            lines.append(f"    source: {_yaml_str(item.get('source', ''))}")
    else:
        lines.append("  - title: \"Unknown\"")
        lines.append("    url: \"\"")
        lines.append("    source: \"\"")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def write_post(article: dict, settings, date: datetime | None = None) -> Path | None:
    """Write the markdown file. Returns its path, or ``None`` on failure."""
    title = (article.get("title") or "").strip()
    body = (article.get("body_markdown") or "").strip()
    slug = (article.get("slug") or "").strip()
    if not title or not body or not slug:
        logger.warning("event=site_publish_skipped reason=empty_fields title=%s slug=%s", bool(title), bool(slug))
        return None

    posts_dir = Path(settings.content_posts_dir)
    try:
        posts_dir.mkdir(parents=True, exist_ok=True)
        path = posts_dir / f"{slug}.md"
        path.write_text(build_frontmatter(article, date) + body + "\n", encoding="utf-8")
    except OSError as exc:
        logger.error("event=site_publish_failed error=%s", exc)
        return None
    logger.info("event=site_publish_ok path=%s", path)
    return path


def site_publisher(article: dict, settings) -> PublishResult:
    """Publisher entry point: write the post file for the static site."""
    slug = article.get("slug") or ""
    enriched = as_publication_article(article, slug, settings)
    path = write_post(enriched, settings)
    if path is None:
        return PublishResult(target="site", ok=False, error="could not write post file")
    return PublishResult(target="site", ok=True, url=post_url(settings, slug), external_id=str(path))
