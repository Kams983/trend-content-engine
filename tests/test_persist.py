"""State persistence on a single-commit orphan branch."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.state.persist import DEFAULT_BRANCH, restore_state, save_state, tracked_paths

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "README.md").write_text("hi\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-q", "-m", "init")
    return root


def _write_state(root: Path, text: str) -> None:
    (root / "trend_store.sqlite").write_bytes(b"SQLite format 3\x00" + text.encode())
    posts = root / "site" / "content" / "posts"
    posts.mkdir(parents=True, exist_ok=True)
    (posts / "2026-01-01-hello.md").write_text(f"---\ntitle: hi\n---\n{text}\n", encoding="utf-8")


def test_save_creates_single_commit_branch(repo) -> None:
    _write_state(repo, "one")
    sha = save_state(repo, push=False)
    assert sha
    assert _git(repo, "rev-list", "--count", DEFAULT_BRANCH) == "1"
    assert "trend_store.sqlite" in tracked_paths(repo, DEFAULT_BRANCH)
    assert "site/content/posts/2026-01-01-hello.md" in tracked_paths(repo, DEFAULT_BRANCH)


def test_save_keeps_history_at_one_commit(repo) -> None:
    _write_state(repo, "one")
    save_state(repo, push=False)
    _write_state(repo, "two")
    save_state(repo, push=False, message="post: hello")
    # History never grows and HEAD/working tree are untouched.
    assert _git(repo, "rev-list", "--count", DEFAULT_BRANCH) == "1"
    assert _git(repo, "log", "-1", "--pretty=%s", DEFAULT_BRANCH) == "post: hello"
    assert (repo / "trend_store.sqlite").read_bytes().endswith(b"two")
    assert (repo / "README.md").exists()
    # HEAD is still on the original branch — only the state ref moved.
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") != DEFAULT_BRANCH


def test_save_force_includes_gitignored_files(repo) -> None:
    (repo / ".gitignore").write_text("*.sqlite\n", encoding="utf-8")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-q", "-m", "ignore db")
    _write_state(repo, "three")
    save_state(repo, push=False)
    assert "trend_store.sqlite" in tracked_paths(repo, DEFAULT_BRANCH)


def test_restore_round_trips_state(repo) -> None:
    _write_state(repo, "round-trip")
    save_state(repo, push=False)

    (repo / "trend_store.sqlite").unlink()
    shutil.rmtree(repo / "site")

    restored = restore_state(repo, branch=DEFAULT_BRANCH)
    assert "trend_store.sqlite" in restored
    assert (repo / "trend_store.sqlite").read_bytes().endswith(b"round-trip")
    assert (repo / "site" / "content" / "posts" / "2026-01-01-hello.md").exists()


def test_first_run_restore_is_not_an_error(repo) -> None:
    # No state branch and no origin: this must be a clean no-op.
    assert restore_state(repo, branch=DEFAULT_BRANCH) == []


def test_save_with_no_state_files_is_a_noop(repo) -> None:
    assert save_state(repo, push=False) is None
