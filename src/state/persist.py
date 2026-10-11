"""Persist engine state to a single-commit orphan git branch.

The GitHub Actions runners are ephemeral, so the SQLite database and the
generated posts have to live somewhere durable. They live on a ``state`` branch
that always holds **exactly one commit**: each save builds a fresh tree from the
current files with plumbing commands (``hash-object``/``write-tree``/
``commit-tree``) and force-pushes it. History therefore never grows, and the
working tree, index and HEAD are left untouched.

Usage::

    python -m src.state.persist restore     # before the pipeline
    python -m src.state.persist save --message "post: <slug>"

Everything is stdlib + ``git``; no shell scripts.
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..util.logging_setup import kv, setup_logging

logger = logging.getLogger(__name__)

DEFAULT_BRANCH = "state"
BOT_NAME = "trend-content-engine[bot]"
BOT_EMAIL = "tce-bot@users.noreply.github.com"

#: Files/dirs (relative to the repo root) that make up the state.
STATE_PATHS = ("trend_store.sqlite", "site/content/posts")


@dataclass
class GitResult:
    returncode: int
    stdout: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_NAME": BOT_NAME,
            "GIT_AUTHOR_EMAIL": BOT_EMAIL,
            "GIT_COMMITTER_NAME": BOT_NAME,
            "GIT_COMMITTER_EMAIL": BOT_EMAIL,
        }
    )
    return env


def git(args: list[str], cwd: Path, *, check: bool = False, extra_env: dict | None = None) -> GitResult:
    """Run a git command. Never prints secrets (git args contain none)."""
    env = _env()
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return GitResult(result.returncode, result.stdout.strip())


def is_git_repo(repo_root: Path) -> bool:
    return git(["rev-parse", "--is-inside-work-tree"], repo_root).ok


def repo_root_for(path: Path) -> Path | None:
    """Directory of the enclosing git repo, or ``None``."""
    result = git(["rev-parse", "--show-toplevel"], path)
    return Path(result.stdout) if result.ok and result.stdout else None


def _relative(repo_root: Path, path: Path) -> str | None:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return None


def checkpoint_sqlite(db_path: Path) -> None:
    """Fold the WAL back into the database file so the committed file is complete."""
    if not db_path.exists():
        return
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
    except sqlite3.DatabaseError as exc:  # pragma: no cover - defensive
        logger.warning(kv("checkpoint_failed", error=str(exc)))


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------


def branch_exists(repo_root: Path, branch: str) -> bool:
    return git(["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], repo_root).ok


def remote_branch_exists(repo_root: Path, branch: str, remote: str = "origin") -> bool:
    result = git(["ls-remote", "--heads", remote, branch], repo_root)
    return result.ok and bool(result.stdout)


def fetch_branch(repo_root: Path, branch: str, remote: str = "origin") -> bool:
    """Fetch ``<remote>/<branch>`` into a local branch. Returns success."""
    result = git(["fetch", "--depth=1", remote, f"{branch}:{branch}"], repo_root)
    return result.ok


def tracked_paths(repo_root: Path, branch: str) -> set[str]:
    result = git(["ls-tree", "-r", "--name-only", branch], repo_root)
    if not result.ok or not result.stdout:
        return set()
    return set(result.stdout.splitlines())


def restore_state(
    repo_root: Path,
    branch: str = DEFAULT_BRANCH,
    paths: tuple[str, ...] = STATE_PATHS,
    remote: str = "origin",
) -> list[str]:
    """Copy the persisted state from *branch* into the working tree.

    First run (branch does not exist) is not an error: it is logged and nothing
    is restored. Returns the list of paths actually restored.
    """
    if not is_git_repo(repo_root):
        logger.warning(kv("restore_skipped", reason="not_a_git_repo", repo_root=str(repo_root)))
        return []

    if not branch_exists(repo_root, branch):
        if remote_branch_exists(repo_root, branch, remote):
            if not fetch_branch(repo_root, branch, remote):
                logger.warning(kv("restore_skipped", reason="fetch_failed", branch=branch))
                return []
        else:
            logger.info(kv("restore_skipped", reason="first_run_no_state_branch", branch=branch))
            return []

    available = tracked_paths(repo_root, branch)
    restored: list[str] = []
    for path in paths:
        if path in available or any(item.startswith(path.rstrip("/") + "/") for item in available):
            result = git(["restore", f"--source={branch}", "--", path], repo_root)
            if result.ok:
                restored.append(path)
            else:
                logger.warning(kv("restore_path_failed", path=path))
    logger.info(kv("restore_done", branch=branch, restored=restored))
    return restored


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------


def save_state(
    repo_root: Path,
    branch: str = DEFAULT_BRANCH,
    paths: tuple[str, ...] = STATE_PATHS,
    message: str | None = None,
    push: bool = True,
    remote: str = "origin",
) -> str | None:
    """Write a fresh single-commit ``branch`` and force-push it.

    Returns the commit sha, or ``None`` when there is nothing to save.
    """
    if not is_git_repo(repo_root):
        logger.warning(kv("save_skipped", reason="not_a_git_repo", repo_root=str(repo_root)))
        return None

    relative: list[str] = []
    for path in paths:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = repo_root / candidate
        rel = _relative(repo_root, candidate)
        if rel and candidate.exists():
            relative.append(rel)
    if not relative:
        logger.info(kv("save_skipped", reason="no_state_files"))
        return None

    # Build the tree in a throwaway index so the real index/HEAD stay untouched.
    with tempfile.TemporaryDirectory() as tmp:
        index_path = Path(tmp) / "index"
        extra_env = {"GIT_INDEX_FILE": str(index_path)}
        if not git(["read-tree", "--empty"], repo_root, check=True, extra_env=extra_env).ok:
            return None

        # `-f` is required because some state (e.g. the DB) is gitignored.
        add = git(["add", "-f", "--", *relative], repo_root, extra_env=extra_env)
        if not add.ok:
            logger.error(kv("save_add_failed", error=add.stdout))
            return None

        tree = git(["write-tree"], repo_root, extra_env=extra_env)
        if not tree.ok or not tree.stdout:
            logger.error(kv("save_write_tree_failed"))
            return None

        commit_message = message or f"state: {datetime.now(timezone.utc).isoformat()}"
        commit = git(["commit-tree", tree.stdout, "-m", commit_message], repo_root)
        if not commit.ok or not commit.stdout:
            logger.error(kv("save_commit_tree_failed"))
            return None
        sha = commit.stdout

    if not git(["update-ref", f"refs/heads/{branch}", sha], repo_root, check=True).ok:
        return None

    pushed = False
    if push:
        # Force-push: the branch is intentionally a single commit, so its history
        # is replaced every time rather than growing.
        pushed = git(["push", "--force", remote, f"refs/heads/{branch}:refs/heads/{branch}"], repo_root).ok
        if not pushed:
            logger.warning(kv("save_push_failed", branch=branch, remote=remote))

    logger.info(kv("save_done", branch=branch, commit=sha[:12], pushed=pushed, paths=len(relative)))
    return sha


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.state.persist")
    parser.add_argument("action", choices=("restore", "save"))
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--message", default=None)
    parser.add_argument("--no-push", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    setup_logging(args.log_level)

    root = Path(args.repo_root) if args.repo_root else repo_root_for(Path.cwd())
    if root is None:
        print("not inside a git repository", file=sys.stderr)
        return 2

    if args.action == "restore":
        restore_state(root, branch=args.branch)
        return 0

    # checkpoint the sqlite files we are about to commit (repo root only)
    for candidate in sorted(root.glob("*.sqlite")):
        checkpoint_sqlite(candidate)
    sha = save_state(root, branch=args.branch, message=args.message, push=not args.no_push)
    return 0 if sha else 1


if __name__ == "__main__":
    raise SystemExit(main())
