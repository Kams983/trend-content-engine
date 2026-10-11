"""Publish to Hashnode via its GraphQL API (optional, off by default).

Verified against Hashnode's GraphQL API:

* endpoint ``https://gql.hashnode.com``, header ``Authorization: Bearer <PAT>``
* mutation ``publishPost(input: PublishPostInput!)`` returning ``post { id url }``
* input fields: ``title``, ``contentMarkdown``, ``publicationId``,
  ``tags: [{name, slug}]``, ``originalArticleURL``, ``slug``

NOTE: since 2026-05-13 every Hashnode API request requires an active Pro plan
on the target publication. Enable this only if you have one.
"""

from __future__ import annotations

import logging
import re

from ..util.http import RetryPolicy, post_json
from ..util.text import slugify
from .base import PublishResult, cross_post_body, post_url

logger = logging.getLogger(__name__)

GQL_URL = "https://gql.hashnode.com/"
_POLICY = RetryPolicy(attempts=3, backoff_base=1.0, timeout=25.0)
MAX_TAGS = 5

MUTATION = """
mutation PublishPost($input: PublishPostInput!) {
  publishPost(input: $input) {
    post { id url }
  }
}
"""


def hashnode_tags(tags: list[str], limit: int = MAX_TAGS) -> list[dict]:
    out: list[dict] = []
    for tag in tags:
        slug = slugify(str(tag), max_len=30)
        if not slug or slug == "untitled":
            continue
        name = re.sub(r"\s+", " ", str(tag)).strip()[:30]
        if any(item["slug"] == slug for item in out):
            continue
        out.append({"name": name or slug, "slug": slug})
    return out[:limit]


def build_variables(article: dict, settings) -> dict:
    brand = (article.get("brand_name") or getattr(settings, "brand_name", "") or "").strip()
    canonical = article.get("url") or post_url(settings, article.get("slug", ""))
    payload = {
        "title": (article.get("title") or "")[:250],
        "contentMarkdown": cross_post_body(article.get("body_markdown") or "", canonical, brand),
        "publicationId": settings.hashnode_publication_id,
        "slug": article.get("slug") or "",
        "originalArticleURL": canonical,
    }
    tags = hashnode_tags(article.get("tags") or [])
    if tags:
        payload["tags"] = tags
    return {"input": payload}


def hashnode_poster(article: dict, settings) -> PublishResult:
    """Publish the article to Hashnode. Never raises."""
    if not settings.hashnode_api_key or not settings.hashnode_publication_id:
        return PublishResult(target="hashnode", ok=False, error="HASHNODE_API_KEY/HASHNODE_PUBLICATION_ID not set")

    headers = {"Authorization": f"Bearer {settings.hashnode_api_key}", "Content-Type": "application/json"}
    body = {"query": MUTATION, "variables": build_variables(article, settings)}
    try:
        response = post_json(GQL_URL, json=body, headers=headers, policy=_POLICY)
        data = response.json()
    except Exception as exc:
        logger.error("event=hashnode_failed error=%s", exc)
        return PublishResult(target="hashnode", ok=False, error=str(exc))

    if data.get("errors"):
        message = "; ".join(str(e.get("message", e)) for e in data["errors"])
        logger.error("event=hashnode_graphql_error error=%s", message)
        return PublishResult(target="hashnode", ok=False, error=message)

    post = (data.get("data") or {}).get("publishPost", {}).get("post") or {}
    url = str(post.get("url") or "")
    external_id = str(post.get("id") or "")
    if not url:
        return PublishResult(target="hashnode", ok=False, error="response missing post url")
    logger.info("event=hashnode_ok url=%s", url)
    return PublishResult(target="hashnode", ok=True, url=url, external_id=external_id)
