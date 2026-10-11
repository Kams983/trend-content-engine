"""Post an article teaser + link to Bluesky via the AT Protocol.

Authenticates with BLUESKY_HANDLE and BLUESKY_APP_PASSWORD from
environment variables.  Returns True on success, False on failure —
never raises.
"""

import logging
import os

logger = logging.getLogger(__name__)

FEED_URL = "https://bsky.app/profile/{handle}/post/{rkey}"


def bluesky_poster(article: dict, site_url: str = "") -> bool:
    """Post a teaser card to Bluesky.

    Args:
        article: dict with at least 'title' and 'teaser'.
        site_url: base URL of the site (e.g. "https://example.com").
                  If empty, only the teaser is posted without a link.

    Returns True if the post was created, False otherwise.
    """
    handle = os.environ.get("BLUESKY_HANDLE", "")
    password = os.environ.get("BLUESKY_APP_PASSWORD", "")

    if not handle or not password:
        logger.error("BLUESKY_HANDLE or BLUESKY_APP_PASSWORD not set")
        return False

    title = article.get("title", "")
    teaser = article.get("teaser", "")

    if not teaser:
        logger.warning("Empty teaser — skipping Bluesky post")
        return False

    text = teaser
    if site_url and title:
        slug = title.lower().replace(" ", "-")
        slug = "".join(c if c.isalnum() or c == "-" else "" for c in slug)
        slug = slug[:80]
        from datetime import datetime, timezone
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        link = f"{site_url.rstrip('/')}/posts/{date_str}-{slug}"
        # Bluesky has a 300-char limit
        if len(text) + len(link) + 1 <= 300:
            text = f"{text}\n\n{link}"

    try:
        from atproto import Client

        client = Client()
        client.login(handle, password)
        resp = client.send_post(text)
        rkey = resp.uri.split("/")[-1]
        post_url = FEED_URL.format(handle=handle, rkey=rkey)
        logger.info("Bluesky post: %s", post_url)
        return True
    except Exception as exc:
        logger.error("Bluesky post failed: %s", exc)
        return False
