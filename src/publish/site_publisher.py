"""Write an article dict to site/content/posts/YYYY-MM-DD-slug.md.

Slug is derived from the title: lowercase, non-alphanumeric → hyphen,
collapsed, trimmed.  Frontmatter includes title, date, and tags.
"""

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

POSTS_DIR = Path(__file__).resolve().parent.parent.parent / "site" / "content" / "posts"


def _slugify(title: str) -> str:
    """Convert title to a URL-friendly slug."""
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:80]


def site_publisher(article: dict, date: datetime | None = None) -> Path | None:
    """Write article as a markdown file with frontmatter.

    Returns the path written, or None on failure.
    """
    title = article.get("title", "")
    body = article.get("body_markdown", "")
    tags = article.get("tags", [])

    if not title or not body:
        logger.warning("Empty title or body — skipping site publish")
        return None

    dt = date or datetime.now(timezone.utc)
    date_str = dt.strftime("%Y-%m-%d")
    slug = _slugify(title)
    filename = f"{date_str}-{slug}.md"

    try:
        POSTS_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error("Could not create posts dir: %s", exc)
        return None

    tag_line = ", ".join(f'"{t}"' for t in tags) if tags else ""
    frontmatter = (
        f"---\n"
        f'title: "{title}"\n'
        f"date: {dt.isoformat()}\n"
        f"tags: [{tag_line}]\n"
        f"---\n\n"
    )

    path = POSTS_DIR / filename
    try:
        path.write_text(frontmatter + body, encoding="utf-8")
        logger.info("Wrote %s", path)
        return path
    except OSError as exc:
        logger.error("Failed to write %s: %s", path, exc)
        return None
