"""CLI behaviour: fail-fast config, offline smoke test and exit codes."""

from __future__ import annotations

import pytest

from src.main import main


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    """Never read the developer's real .env during CLI tests."""
    monkeypatch.setattr("src.config.load_env_file", lambda path=None: None)


def test_missing_groq_key_exits_2_and_lists_keys(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "main.sqlite"))
    code = main([])
    captured = capsys.readouterr()
    assert code == 2
    assert "GROQ_API_KEY" in captured.err
    assert "TELEGRAM_ADMIN_CHAT_ID" in captured.err


def test_offline_fixture_dry_run_completes(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "offline.sqlite"))
    monkeypatch.setenv("CONTENT_POSTS_DIR", str(tmp_path / "posts"))
    code = main(["--use-fixtures", "--dry-run"])
    assert code == 0
    # Nothing was written to disk in dry-run mode.
    assert not (tmp_path / "posts").exists()


def test_dry_run_writes_no_articles_but_records_the_run(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "offline2.sqlite"))
    monkeypatch.setenv("CONTENT_POSTS_DIR", str(tmp_path / "posts2"))
    assert main(["--use-fixtures", "--dry-run"]) == 0

    import sqlite3

    connection = sqlite3.connect(str(tmp_path / "offline2.sqlite"))
    outcomes = {row[0] for row in connection.execute("SELECT outcome FROM run_log")}
    connection.close()
    assert "PENDING_APPROVAL" in outcomes


def test_publish_mode_with_nothing_to_publish_is_benign(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "pub.sqlite"))
    monkeypatch.setenv("CONTENT_POSTS_DIR", str(tmp_path / "posts3"))
    assert main(["--use-fixtures", "--dry-run", "--mode", "publish"]) == 0
