"""Validate that every fixture file contains well-formed normalized items.

Run:  python -m src.ingest.fixtures.test_fixtures
  or: python src/ingest/fixtures/test_fixtures.py
"""

import json
import sys
from datetime import datetime
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent
REQUIRED = ["source", "title", "content", "url", "engagement", "timestamp", "tags"]
SOURCES = ["arxiv", "github_trending", "reddit", "hackernews"]


def _validate_item(item: dict, source: str, idx: int) -> list[str]:
    errors: list[str] = []
    for field in REQUIRED:
        if field not in item:
            errors.append(f"  [{source}][{idx}] missing field '{field}'")
    if not item.get("title"):
        errors.append(f"  [{source}][{idx}] empty title")
    if not item.get("url"):
        errors.append(f"  [{source}][{idx}] empty url")
    if not isinstance(item.get("engagement"), int):
        errors.append(f"  [{source}][{idx}] engagement is {type(item.get('engagement')).__name__}")
    # timestamp: datetime in memory, ISO string in JSON fixtures
    ts = item.get("timestamp")
    if isinstance(ts, str):
        try:
            datetime.fromisoformat(ts)
        except ValueError:
            errors.append(f"  [{source}][{idx}] timestamp is not valid ISO: {ts!r}")
    elif not hasattr(ts, "isoformat"):
        errors.append(f"  [{source}][{idx}] timestamp is {type(ts).__name__}")
    if not isinstance(item.get("tags"), list):
        errors.append(f"  [{source}][{idx}] tags is {type(item.get('tags')).__name__}")
    if item.get("source") != source:
        errors.append(f"  [{source}][{idx}] source is '{item.get('source')}', expected '{source}'")
    return errors


def _load_json(path: Path) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def _load_jsonl(path: Path) -> list[dict]:
    items = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def main() -> int:
    total_items = 0
    all_errors: list[str] = []

    for source in SOURCES:
        # --- JSON ---
        json_path = FIXTURES_DIR / f"{source}.json"
        if not json_path.exists():
            all_errors.append(f"  MISSING {json_path}")
            continue
        items = _load_json(json_path)
        for idx, item in enumerate(items):
            all_errors.extend(_validate_item(item, source, idx))
        total_items += len(items)
        print(f"  {source}.json:  {len(items)} items OK")

        # --- JSONL ---
        jsonl_path = FIXTURES_DIR / f"{source}.jsonl"
        if not jsonl_path.exists():
            all_errors.append(f"  MISSING {jsonl_path}")
            continue
        items_l = _load_jsonl(jsonl_path)
        if len(items_l) != len(items):
            all_errors.append(
                f"  {source}: JSON has {len(items)} items, JSONL has {len(items_l)}"
            )
        for idx, item in enumerate(items_l):
            all_errors.extend(_validate_item(item, source, idx))
        print(f"  {source}.jsonl: {len(items_l)} items OK")

    print(f"\nTotal: {total_items} items across {len(SOURCES)} sources")
    if all_errors:
        print(f"\n{len(all_errors)} ERRORS:")
        for e in all_errors[:20]:
            print(e)
        if len(all_errors) > 20:
            print(f"  ... and {len(all_errors) - 20} more")
        return 1

    print("\nALL FIXTURES VALID")
    return 0


if __name__ == "__main__":
    sys.exit(main())
