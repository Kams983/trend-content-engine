"""Typed configuration for the Trend Content Engine.

* Loads ``.env`` (via python-dotenv) without overriding real process env.
* Exposes a frozen :class:`Settings` object.
* Validates that **every** key required by an *enabled* feature is present and
  raises :class:`ConfigError` listing all problems at once, so a single run
  tells the operator everything they need to fix.

Nothing here ever prints a secret value.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = REPO_ROOT / "trend_store.sqlite"
DEFAULT_CONTENT_DIR = REPO_ROOT / "site" / "content" / "posts"

#: Model names are configuration, not constants — Groq retires models often.
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
DEFAULT_GROQ_MODEL_FALLBACK = "openai/gpt-oss-20b"


class ConfigError(RuntimeError):
    """Raised at startup when required configuration is missing or invalid."""


# ---------------------------------------------------------------------------
# Env parsing helpers
# ---------------------------------------------------------------------------


def load_env_file(path: Path | None = None) -> None:
    """Load ``.env`` if present; never override variables already in the env."""
    target = path or REPO_ROOT / ".env"
    if not target.exists():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - python-dotenv is a declared dep
        return
    load_dotenv(dotenv_path=target, override=False)


def _raw(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value if value else None


def _str(name: str, default: str = "") -> str:
    return _raw(name) or default


def _bool(name: str, default: bool) -> bool:
    value = _raw(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "y", "on"}


def _int(name: str, default: int) -> int:
    value = _raw(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        raise ConfigError(f"{name} must be an integer, got {value!r}") from None


def _float(name: str, default: float) -> float:
    value = _raw(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {value!r}") from None


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Settings:
    """Immutable, validated runtime configuration."""

    # --- run mode -------------------------------------------------------
    dry_run: bool = False
    use_fixtures: bool = False
    offline: bool = False  # derived: dry_run + use_fixtures, no Groq key
    mode: str = "full"  # draft | publish | full

    # --- paths ----------------------------------------------------------
    repo_root: Path = REPO_ROOT
    db_path: Path = DEFAULT_DB_PATH
    content_posts_dir: Path = DEFAULT_CONTENT_DIR

    # --- LLM ------------------------------------------------------------
    groq_api_key: str = ""
    groq_model: str = DEFAULT_GROQ_MODEL
    groq_model_fallback: str = DEFAULT_GROQ_MODEL_FALLBACK
    groq_timeout: float = 60.0
    groq_temperature: float = 0.7
    groq_max_tokens: int = 2048
    groq_max_attempts: int = 3

    # --- site -----------------------------------------------------------
    site_url: str = ""

    # --- feature flags --------------------------------------------------
    require_approval: bool = True
    enable_bluesky: bool = False
    enable_telegram_channel: bool = False
    enable_devto: bool = False
    enable_hashnode: bool = False
    enable_mastodon: bool = False

    # --- ingest ---------------------------------------------------------
    user_agent: str = "TrendContentEngine/1.0"
    github_token: str = ""
    hn_limit: int = 30
    arxiv_limit: int = 30
    arxiv_politeness_delay: float = 3.0
    github_limit: int = 30
    reddit_limit: int = 30
    min_sources_with_data: int = 2

    # --- analysis -------------------------------------------------------
    cluster_threshold: float = 0.45
    topic_similarity_threshold: float = 0.6
    topic_lookback_days: int = 14
    topic_retention_days: int = 60
    min_cluster_items: int = 3
    min_cluster_sources: int = 2
    cooldown_days: int = 7
    cooldown_velocity_override: float = 2.0
    top_clusters: int = 10
    max_draft_attempts: int = 3
    w_velocity: float = 1.0
    w_novelty: float = 1.2
    w_size: float = 1.0
    w_sources: float = 1.0
    w_engagement: float = 0.8

    # --- validation -----------------------------------------------------
    article_min_words: int = 400
    article_max_words: int = 800
    title_max_len: int = 120
    teaser_max_len: int = 280

    # --- social ---------------------------------------------------------
    bluesky_handle: str = ""
    bluesky_app_password: str = ""
    telegram_bot_token: str = ""
    telegram_channel_id: str = ""
    telegram_admin_chat_id: str = ""
    devto_api_key: str = ""
    hashnode_api_key: str = ""
    hashnode_publication_id: str = ""
    mastodon_instance: str = ""
    mastodon_access_token: str = ""

    extra_warnings: tuple[str, ...] = field(default_factory=tuple)

    # ------------------------------------------------------------------
    @property
    def enabled_targets(self) -> tuple[str, ...]:
        """Names of publishing targets that are switched on."""
        targets = ["site"]
        if self.enable_bluesky:
            targets.append("bluesky")
        if self.enable_telegram_channel:
            targets.append("telegram")
        if self.enable_devto:
            targets.append("devto")
        if self.enable_hashnode:
            targets.append("hashnode")
        if self.enable_mastodon:
            targets.append("mastodon")
        return tuple(targets)

    def score_weights(self) -> dict[str, float]:
        return {
            "velocity": self.w_velocity,
            "novelty": self.w_novelty,
            "size": self.w_size,
            "sources": self.w_sources,
            "engagement": self.w_engagement,
        }


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_settings(
    *,
    dry_run: bool | None = None,
    use_fixtures: bool | None = None,
    mode: str | None = None,
    env_file: Path | None = None,
    validate: bool = True,
) -> Settings:
    """Build :class:`Settings` from ``.env`` + process env.

    CLI flags (``dry_run``/``use_fixtures``/``mode``) win over env vars.
    """
    load_env_file(env_file)

    dry = _bool("DRY_RUN", False) if dry_run is None else dry_run
    fixtures = _bool("USE_FIXTURES", False) if use_fixtures is None else use_fixtures
    run_mode = mode or _str("RUN_MODE", "full")

    groq_key = _str("GROQ_API_KEY")

    # Offline mode: fixtures + dry run *and* no key available → deterministic
    # stub LLM. This is the only path that does not need a Groq key, and it is
    # logged loudly by the orchestrator.
    offline = bool(fixtures and dry and not groq_key)

    settings = Settings(
        dry_run=dry,
        use_fixtures=fixtures,
        offline=offline,
        mode=run_mode,
        repo_root=REPO_ROOT,
        db_path=Path(_str("DB_PATH", str(DEFAULT_DB_PATH))),
        content_posts_dir=Path(_str("CONTENT_POSTS_DIR", str(DEFAULT_CONTENT_DIR))),
        groq_api_key=groq_key,
        groq_model=_str("GROQ_MODEL", DEFAULT_GROQ_MODEL),
        groq_model_fallback=_str("GROQ_MODEL_FALLBACK", DEFAULT_GROQ_MODEL_FALLBACK),
        groq_timeout=_float("GROQ_TIMEOUT", 60.0),
        groq_temperature=_float("GROQ_TEMPERATURE", 0.7),
        groq_max_tokens=_int("GROQ_MAX_TOKENS", 2048),
        groq_max_attempts=_int("GROQ_MAX_ATTEMPTS", 3),
        site_url=_str("SITE_URL", "").rstrip("/"),
        require_approval=_bool("REQUIRE_APPROVAL", True),
        enable_bluesky=_bool("ENABLE_BLUESKY", False),
        enable_telegram_channel=_bool("ENABLE_TELEGRAM_CHANNEL", False),
        enable_devto=_bool("ENABLE_DEVTO", False),
        enable_hashnode=_bool("ENABLE_HASHNODE", False),
        enable_mastodon=_bool("ENABLE_MASTODON", False),
        user_agent=_str("USER_AGENT", "TrendContentEngine/1.0"),
        github_token=_str("GITHUB_TOKEN"),
        hn_limit=_int("HN_LIMIT", 30),
        arxiv_limit=_int("ARXIV_LIMIT", 30),
        arxiv_politeness_delay=_float("ARXIV_POLITENESS_DELAY", 3.0),
        github_limit=_int("GITHUB_LIMIT", 30),
        reddit_limit=_int("REDDIT_LIMIT", 30),
        min_sources_with_data=_int("MIN_SOURCES_WITH_DATA", 2),
        cluster_threshold=_float("CLUSTER_THRESHOLD", 0.45),
        topic_similarity_threshold=_float("TOPIC_SIMILARITY_THRESHOLD", 0.6),
        topic_lookback_days=_int("TOPIC_LOOKBACK_DAYS", 14),
        topic_retention_days=_int("TOPIC_RETENTION_DAYS", 60),
        min_cluster_items=_int("MIN_CLUSTER_ITEMS", 3),
        min_cluster_sources=_int("MIN_CLUSTER_SOURCES", 2),
        cooldown_days=_int("COOLDOWN_DAYS", 7),
        cooldown_velocity_override=_float("COOLDOWN_VELOCITY_OVERRIDE", 2.0),
        top_clusters=_int("TOP_CLUSTERS", 10),
        max_draft_attempts=_int("MAX_DRAFT_ATTEMPTS", 3),
        w_velocity=_float("SCORE_W_VELOCITY", 1.0),
        w_novelty=_float("SCORE_W_NOVELTY", 1.2),
        w_size=_float("SCORE_W_SIZE", 1.0),
        w_sources=_float("SCORE_W_SOURCES", 1.0),
        w_engagement=_float("SCORE_W_ENGAGEMENT", 0.8),
        article_min_words=_int("ARTICLE_MIN_WORDS", 400),
        article_max_words=_int("ARTICLE_MAX_WORDS", 800),
        title_max_len=_int("TITLE_MAX_LEN", 120),
        teaser_max_len=_int("TEASER_MAX_LEN", 280),
        bluesky_handle=_str("BLUESKY_HANDLE"),
        bluesky_app_password=_str("BLUESKY_APP_PASSWORD"),
        telegram_bot_token=_str("TELEGRAM_BOT_TOKEN"),
        telegram_channel_id=_str("TELEGRAM_CHANNEL_ID"),
        telegram_admin_chat_id=_str("TELEGRAM_ADMIN_CHAT_ID"),
        devto_api_key=_str("DEVTO_API_KEY"),
        hashnode_api_key=_str("HASHNODE_API_KEY"),
        hashnode_publication_id=_str("HASHNODE_PUBLICATION_ID"),
        mastodon_instance=_str("MASTODON_INSTANCE").rstrip("/"),
        mastodon_access_token=_str("MASTODON_ACCESS_TOKEN"),
    )

    if validate:
        validate_settings(settings)
    return settings


def missing_keys(settings: Settings) -> list[str]:
    """Return a list of ``KEY: reason`` strings for every missing/invalid key."""
    problems: list[str] = []

    def require(condition: bool, key: str, reason: str) -> None:
        if not condition:
            problems.append(f"{key}: {reason}")

    # The LLM is required unless we are in explicit offline mode.
    require(
        bool(settings.groq_api_key) or settings.offline,
        "GROQ_API_KEY",
        "required to draft articles (set it, or run with --use-fixtures --dry-run for an offline smoke test)",
    )

    if settings.require_approval:
        require(
            bool(settings.telegram_bot_token),
            "TELEGRAM_BOT_TOKEN",
            "required when REQUIRE_APPROVAL=true (approval arrives via Telegram)",
        )
        require(
            bool(settings.telegram_admin_chat_id),
            "TELEGRAM_ADMIN_CHAT_ID",
            "required when REQUIRE_APPROVAL=true (destination for approval prompts)",
        )

    if settings.enable_bluesky:
        require(bool(settings.bluesky_handle), "BLUESKY_HANDLE", "required when ENABLE_BLUESKY=true")
        require(
            bool(settings.bluesky_app_password),
            "BLUESKY_APP_PASSWORD",
            "required when ENABLE_BLUESKY=true (use an app password, never the account password)",
        )
    if settings.enable_telegram_channel:
        require(bool(settings.telegram_bot_token), "TELEGRAM_BOT_TOKEN", "required when ENABLE_TELEGRAM_CHANNEL=true")
        require(bool(settings.telegram_channel_id), "TELEGRAM_CHANNEL_ID", "required when ENABLE_TELEGRAM_CHANNEL=true")
    if settings.enable_devto:
        require(bool(settings.devto_api_key), "DEVTO_API_KEY", "required when ENABLE_DEVTO=true")
    if settings.enable_hashnode:
        require(bool(settings.hashnode_api_key), "HASHNODE_API_KEY", "required when ENABLE_HASHNODE=true")
        require(
            bool(settings.hashnode_publication_id),
            "HASHNODE_PUBLICATION_ID",
            "required when ENABLE_HASHNODE=true",
        )
    if settings.enable_mastodon:
        require(bool(settings.mastodon_instance), "MASTODON_INSTANCE", "required when ENABLE_MASTODON=true")
        require(
            bool(settings.mastodon_access_token),
            "MASTODON_ACCESS_TOKEN",
            "required when ENABLE_MASTODON=true",
        )

    # Sanity checks on ranges.
    if settings.article_min_words <= 0 or settings.article_max_words <= settings.article_min_words:
        problems.append("ARTICLE_MIN_WORDS/ARTICLE_MAX_WORDS: max must be greater than min")
    if not 0.0 <= settings.topic_similarity_threshold <= 1.0:
        problems.append("TOPIC_SIMILARITY_THRESHOLD: must be between 0.0 and 1.0")
    if not 0.0 <= settings.cluster_threshold <= 1.0:
        problems.append("CLUSTER_THRESHOLD: must be between 0.0 and 1.0")
    if settings.max_draft_attempts < 1:
        problems.append("MAX_DRAFT_ATTEMPTS: must be at least 1")
    if settings.mode not in {"draft", "publish", "full"}:
        problems.append("RUN_MODE: must be one of 'draft', 'publish', 'full'")

    return problems


def validate_settings(settings: Settings) -> None:
    """Raise :class:`ConfigError` listing *all* missing keys at once."""
    problems = missing_keys(settings)
    if not problems:
        return
    listing = "\n".join(f"  - {p}" for p in problems)
    raise ConfigError(
        f"Configuration is incomplete — {len(problems)} problem(s):\n{listing}\n"
        f"Copy .env.example to .env and fill in the values, or set them in the environment."
    )
