"""Configuration loading and fail-fast validation."""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.config import ConfigError, load_settings, missing_keys


def _env_file(tmp_path):
    return tmp_path / "does-not-exist.env"


def test_missing_keys_lists_every_problem_at_once(tmp_path) -> None:
    with pytest.raises(ConfigError) as excinfo:
        load_settings(env_file=_env_file(tmp_path))
    message = str(excinfo.value)
    assert "GROQ_API_KEY" in message
    assert "TELEGRAM_BOT_TOKEN" in message
    assert "TELEGRAM_ADMIN_CHAT_ID" in message
    # Fail fast with *all* problems, not just the first.
    assert message.count("\n  - ") >= 3


def test_offline_mode_does_not_require_groq_or_telegram(tmp_path) -> None:
    settings = load_settings(dry_run=True, use_fixtures=True, env_file=_env_file(tmp_path))
    assert settings.offline is True
    assert settings.groq_api_key == ""


def test_forcing_offline_via_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TCE_OFFLINE", "1")
    monkeypatch.setenv("REQUIRE_APPROVAL", "false")
    settings = load_settings(env_file=_env_file(tmp_path))
    assert settings.offline is True
    assert settings.groq_api_key == ""


def test_enabled_social_target_requires_its_keys(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("ENABLE_BLUESKY", "true")
    with pytest.raises(ConfigError) as excinfo:
        load_settings(env_file=_env_file(tmp_path))
    message = str(excinfo.value)
    assert "BLUESKY_HANDLE" in message
    assert "BLUESKY_APP_PASSWORD" in message


def test_dry_run_relaxes_approval_requirements(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    settings = load_settings(dry_run=True, env_file=_env_file(tmp_path))
    # require_approval defaults to true but a dry run sends nothing.
    assert settings.require_approval is True
    assert missing_keys(settings) == []


def test_groq_model_is_configurable(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("GROQ_MODEL_FALLBACK", "openai/gpt-oss-20b")
    settings = load_settings(dry_run=True, env_file=_env_file(tmp_path))
    assert settings.groq_model == "openai/gpt-oss-120b"
    assert settings.groq_model_fallback == "openai/gpt-oss-20b"


def test_default_flags_match_the_spec(tmp_path) -> None:
    settings = load_settings(dry_run=True, use_fixtures=True, env_file=_env_file(tmp_path))
    assert settings.require_approval is True
    assert settings.enable_bluesky is False
    assert settings.enable_telegram_channel is False
    assert settings.enable_devto is False
    assert settings.enable_hashnode is False
    assert settings.enable_mastodon is False


def test_enabled_targets_reflects_flags(settings) -> None:
    assert settings.enabled_targets == ("site",)
    flagged = replace(settings, enable_bluesky=True, enable_devto=True)
    assert flagged.enabled_targets == ("site", "bluesky", "devto")


def test_invalid_numeric_setting_is_reported(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTICLE_MIN_WORDS", "600")
    monkeypatch.setenv("ARTICLE_MAX_WORDS", "500")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    with pytest.raises(ConfigError) as excinfo:
        load_settings(env_file=_env_file(tmp_path))
    assert "ARTICLE_MIN_WORDS" in str(excinfo.value)


def test_invalid_mode_is_rejected(tmp_path) -> None:
    with pytest.raises(ConfigError) as excinfo:
        load_settings(mode="sideways", env_file=_env_file(tmp_path))
    assert "RUN_MODE" in str(excinfo.value)
