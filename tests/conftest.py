"""Shared test fixtures.

The suite is hermetic: no network, no model download. The embedding model is
replaced by the committed deterministic fixture encoder, and every environment
variable the engine reads is cleared so a developer's real ``.env`` cannot leak
into assertions.
"""

from __future__ import annotations

import json

import pytest

from src.analysis import embed
from src.analysis.fixture_encoder import install_fixture_encoder
from src.config import Settings
from src.ingest.fixtures_loader import DEFAULT_SOURCES, load_fixtures
from src.state.db import init_db

#: Every environment variable the engine reads. Cleared before each test.
ENV_KEYS = (
    "GROQ_API_KEY",
    "GROQ_MODEL",
    "GROQ_MODEL_FALLBACK",
    "REQUIRE_APPROVAL",
    "DRY_RUN",
    "USE_FIXTURES",
    "RUN_MODE",
    "TCE_OFFLINE",
    "DB_PATH",
    "CONTENT_POSTS_DIR",
    "SITE_URL",
    "ENABLE_BLUESKY",
    "ENABLE_TELEGRAM_CHANNEL",
    "ENABLE_DEVTO",
    "ENABLE_HASHNODE",
    "ENABLE_MASTODON",
    "BLUESKY_HANDLE",
    "BLUESKY_APP_PASSWORD",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHANNEL_ID",
    "TELEGRAM_ADMIN_CHAT_ID",
    "DEVTO_API_KEY",
    "HASHNODE_API_KEY",
    "HASHNODE_PUBLICATION_ID",
    "MASTODON_INSTANCE",
    "MASTODON_ACCESS_TOKEN",
    "GITHUB_TOKEN",
    "MIN_SOURCES_WITH_DATA",
    "MIN_CLUSTER_ITEMS",
    "MIN_CLUSTER_SOURCES",
    "TOPIC_SIMILARITY_THRESHOLD",
    "CLUSTER_THRESHOLD",
    "ARXIV_POLITENESS_DELAY",
    "ARTICLE_MIN_WORDS",
    "ARTICLE_MAX_WORDS",
    "MAX_DRAFT_ATTEMPTS",
    "COOLDOWN_DAYS",
    "USER_AGENT",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Make sure no ambient .env values bleed into a test."""
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield


@pytest.fixture(autouse=True)
def fixture_encoder():
    """Use the committed deterministic embeddings (never the real model)."""
    install_fixture_encoder()
    yield
    embed.reset_encoder()


@pytest.fixture
def settings(tmp_path) -> Settings:
    """A fully self-contained Settings pointing at tmp paths."""
    return Settings(
        db_path=tmp_path / "test.sqlite",
        content_posts_dir=tmp_path / "posts",
        use_fixtures=True,
        dry_run=False,
        require_approval=False,
        site_url="https://example.test",
    )


@pytest.fixture
def conn(settings):
    """A migrated, empty SQLite database."""
    connection = init_db(settings.db_path)
    yield connection
    connection.close()


@pytest.fixture
def fixture_items() -> list[dict]:
    """All 120 frozen fixture items in one flat list."""
    fixtures = load_fixtures()
    return [item for source in DEFAULT_SOURCES for item in fixtures[source]]


class FakeLLM:
    """Deterministic LLM that returns a valid, grounded article.

    ``decline=True`` reproduces the model returning the empty JSON object.
    """

    name = "fake"

    def __init__(self, decline: bool = False, title: str = "Fake grounded article") -> None:
        self.decline = decline
        self.title = title
        self.calls: list[str] = []

    def complete(self, system: str, user: str, cluster: list[dict] | None = None) -> str:
        self.calls.append(user)
        if self.decline:
            return json.dumps({"title": "", "body_markdown": "", "teaser": "", "tags": []})
        cluster = cluster or []
        urls = [item["url"] for item in cluster if item.get("url")]
        filler = " ".join(f"w{i}" for i in range(max(1, 450 - len(urls))))
        body = f"{filler} {' '.join(urls)}".strip()
        return json.dumps(
            {
                "title": self.title[:110],
                "body_markdown": body,
                "teaser": "A deterministic teaser about the trend.",
                "tags": ["ai", "research"],
            }
        )


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def declining_llm() -> FakeLLM:
    """An LLM that returns the empty JSON object (sources too thin)."""
    return FakeLLM(decline=True)
