"""Validate an LLM draft and finalise it with a code-built Sources section.

Checks performed (all failures are returned as human-readable strings so they
can be fed back to the model for one regeneration):

* schema: title / body_markdown / teaser present and non-empty strings,
* title length within ``TITLE_MAX_LEN``,
* word count inside ``[ARTICLE_MIN_WORDS, ARTICLE_MAX_WORDS]``,
* teaser within ``TEASER_MAX_LEN`` graphemes,
* every URL in the body appears in the supplied source URLs,
* no placeholders or boilerplate,
* tags non-empty and slug-safe,
* title is not a duplicate of an existing post.

The Sources section is always appended by code — never by the model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..config import Settings
from ..util.text import count_words, grapheme_len, slugify

#: Case-insensitive markers of placeholder/boilerplate text.
PLACEHOLDER_MARKERS = (
    "[todo]",
    "lorem ipsum",
    "as an ai",
    "as a language model",
    "{{",
    "}}",
)

_URL_RE = re.compile(r"https?://[^\s)\]<>\"'`,]+")
_TAG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def normalise_url(url: str) -> str:
    """Lower-case scheme+host, drop a trailing slash, strip trailing punctuation."""
    url = (url or "").strip().rstrip(".,;:!?)]}\"'")
    if "://" in url:
        scheme, rest = url.split("://", 1)
        if "/" in rest:
            host, path = rest.split("/", 1)
            url = f"{scheme.lower()}://{host.lower()}/{path}"
        else:
            url = f"{scheme.lower()}://{rest.lower()}"
    return url.rstrip("/")


def extract_urls(text: str) -> list[str]:
    return [normalise_url(m) for m in _URL_RE.findall(text or "")]


def derive_tags(cluster: list[dict], limit: int = 6) -> list[str]:
    """Deterministic, slug-safe tags from the cluster's own tags and sources."""
    tags: list[str] = []
    for item in cluster:
        for raw in list(item.get("tags") or []) + [item.get("source", "")]:
            slug = slugify(str(raw), max_len=30)
            if slug and slug != "untitled" and slug not in tags:
                tags.append(slug)
    return tags[:limit]


def build_sources_section(cluster: list[dict]) -> str:
    """Markdown Sources section built from the cluster (title + URL)."""
    lines = ["", "## Sources", ""]
    for index, item in enumerate(cluster, 1):
        title = (item.get("title") or "Untitled").strip().replace("[", "(").replace("]", ")")
        url = (item.get("url") or "").strip()
        source = item.get("source") or "unknown"
        lines.append(f"{index}. [{title}]({url}) — {source}")
    lines.append("")
    return "\n".join(lines)


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_feedback(self) -> str:
        return "The previous draft was rejected for these reasons:\n" + "\n".join(
            f"- {e}" for e in self.errors
        )


def validate_article(
    article: dict,
    cluster: list[dict],
    settings: Settings,
    existing_titles: set[str] | None = None,
) -> ValidationResult:
    """Validate *article* against the sources in *cluster*. Never raises."""
    errors: list[str] = []

    title = article.get("title")
    body = article.get("body_markdown")
    teaser = article.get("teaser")
    tags = article.get("tags")

    if not isinstance(title, str) or not title.strip():
        errors.append("title must be a non-empty string")
    elif len(title.strip()) > settings.title_max_len:
        errors.append(f"title is {len(title.strip())} chars, max {settings.title_max_len}")

    if not isinstance(body, str) or not body.strip():
        errors.append("body_markdown must be a non-empty string")
    else:
        words = count_words(body)
        if words < settings.article_min_words:
            errors.append(
                f"body has {words} words, below the minimum of {settings.article_min_words}"
            )
        if words > settings.article_max_words:
            errors.append(
                f"body has {words} words, above the maximum of {settings.article_max_words}"
            )

    if not isinstance(teaser, str) or not teaser.strip():
        errors.append("teaser must be a non-empty string")
    elif grapheme_len(teaser) > settings.teaser_max_len:
        errors.append(f"teaser is {grapheme_len(teaser)} graphemes, max {settings.teaser_max_len}")

    if not isinstance(tags, list) or not tags:
        errors.append("tags must be a non-empty list")
    else:
        for tag in tags:
            if not isinstance(tag, str) or not _TAG_RE.match(tag):
                errors.append(f"tag {tag!r} is not slug-safe (lowercase a-z0-9 with hyphens)")

    if isinstance(body, str) and isinstance(title, str):
        haystack = f"{title}\n{body}".lower()
        for marker in PLACEHOLDER_MARKERS:
            if marker in haystack:
                errors.append(f"contains placeholder/boilerplate text: {marker!r}")

    # URL provenance: everything cited must be a supplied source.
    source_urls = {normalise_url(it.get("url", "")) for it in cluster if it.get("url")}
    for url in extract_urls(body or ""):
        if url not in source_urls:
            errors.append(f"body cites a URL that is not in the supplied sources: {url}")

    if existing_titles and isinstance(title, str) and title.strip().lower() in existing_titles:
        errors.append("title duplicates an existing post")

    return ValidationResult(errors=errors)


def finalize_article(article: dict, cluster: list[dict]) -> dict:
    """Return a copy of *article* with the code-built Sources section appended."""
    finalised = dict(article)
    body = (finalised.get("body_markdown") or "").rstrip()
    finalised["body_markdown"] = body + "\n" + build_sources_section(cluster)
    finalised["sources"] = [
        {"title": (it.get("title") or "").strip(), "url": (it.get("url") or "").strip(), "source": it.get("source", "")}
        for it in cluster
    ]
    return finalised
