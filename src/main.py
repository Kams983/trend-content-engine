"""CLI entry point.

    python -m src.main --use-fixtures --dry-run    # offline smoke test
    python -m src.main --mode draft                # stage A only
    python -m src.main --mode publish              # stage B only
    python -m src.main                             # full (stage A + B)

Exit codes: 0 = success or a benign skip, 1 = a FAILED_* stage, 2 = bad config.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import ConfigError, load_settings
from .orchestrator import run
from .state.db import init_db
from .util.logging_setup import kv, setup_logging

logger = logging.getLogger("src.main")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.main", description="Trend Content Engine")
    parser.add_argument(
        "--mode",
        choices=("draft", "publish", "full"),
        default=None,
        help="which stage(s) to run (default: RUN_MODE env or 'full')",
    )
    parser.add_argument(
        "--use-fixtures",
        action="store_true",
        default=None,
        help="read src/ingest/fixtures instead of live sources (offline)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=None,
        help="run the pipeline but send/write nothing; print what would be sent",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="logging verbosity (default INFO)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.log_level)

    try:
        settings = load_settings(dry_run=args.dry_run, use_fixtures=args.use_fixtures, mode=args.mode)
    except ConfigError as exc:
        # A missing key must be loud and list every problem at once.
        print(f"\nConfiguration error\n{exc}\n", file=sys.stderr)
        logger.error(kv("config_invalid", problems=len(str(exc).splitlines()) - 1))
        return 2

    if settings.use_fixtures:
        from .analysis.fixture_encoder import install_fixture_encoder

        install_fixture_encoder()

    if settings.offline:
        logger.warning(
            kv(
                "offline_mode",
                note="no GROQ_API_KEY / TCE_OFFLINE: deterministic stub LLM output",
            )
        )
    elif not settings.groq_api_key:
        # Should not happen (validation catches it) but be explicit.
        print("Configuration error\n  - GROQ_API_KEY: required", file=sys.stderr)
        return 2

    conn = init_db(settings.db_path)
    try:
        results = run(settings, conn)
    finally:
        conn.close()

    failed = False
    for result in results:
        line = kv(
            "stage_result",
            outcome=result.outcome,
            stage=result.stage or "-",
            reason=result.reason[:300],
            article_id=result.article_id if result.article_id is not None else "-",
        )
        if result.failed:
            failed = True
            logger.error(line)
        else:
            logger.info(line)

    if failed:
        logger.error(kv("run_failed", note="one or more stages failed; see run_log for details"))
        return 1

    logger.info(kv("run_ok", dry_run=settings.dry_run, mode=settings.mode, offline=settings.offline))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
