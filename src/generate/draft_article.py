"""Draft an article from a cluster, validate it, and finalise it.

Flow::

    build prompt → LLM → parse JSON → validate
        ├─ ok           → append code-built Sources section → DraftOutcome(article)
        ├─ invalid      → regenerate ONCE with the validation errors fed back
        └─ still bad    → DraftOutcome(errors, declined=False)

A model that returns the empty JSON object (sources too thin) yields
``DraftOutcome(declined=True)`` so the orchestrator can try the next cluster
without treating it as a failure.

The model is configurable via ``GROQ_MODEL`` / ``GROQ_MODEL_FALLBACK`` and the
client handles 429s/timeouts with backoff before switching model (see
:mod:`src.generate.llm`).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Settings
from ..util.logging_setup import kv
from ..util.text import extract_json_object
from .llm import LLM, LLMError
from .validate import derive_tags, finalize_article, validate_article

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "article_prompt.txt"


@dataclass
class DraftOutcome:
    """Result of one cluster's drafting attempt(s)."""

    article: dict | None = None
    errors: list[str] = field(default_factory=list)
    attempts: int = 0
    declined: bool = False

    @property
    def ok(self) -> bool:
        return self.article is not None


def load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8").strip()


def build_source_block(cluster: list[dict]) -> str:
    """Format cluster items into a source block for the LLM."""
    parts: list[str] = []
    for index, item in enumerate(cluster, 1):
        parts.append(
            f"[{index}] ({item.get('source', '')}) {item.get('title', '')}\n"
            f"{item.get('content', '')[:500]}\n"
            f"URL: {item.get('url', '')}"
        )
    return "\n\n".join(parts)


def build_user_prompt(cluster: list[dict], feedback: str | None = None) -> str:
    """User prompt with the JSON contract, source block and optional feedback."""
    source_block = build_source_block(cluster)
    empty_json = json.dumps({"title": "", "body_markdown": "", "teaser": "", "tags": []})
    prompt = (
        f"Write a 400-600 word article about the trend represented by these "
        f"{len(cluster)} source items.\n\n"
        f"SOURCE ITEMS:\n\n{source_block}\n\n"
        f"Return your response as a JSON object with exactly these keys:\n"
        f'  "title": a short, specific headline (max 120 characters)\n'
        f'  "body_markdown": the article body in Markdown (400-600 words)\n'
        f'  "teaser": a standalone social post under 200 characters\n'
        f'  "tags": 2-5 lowercase hyphenated topic tags (a-z, 0-9, hyphens only)\n\n'
        f"Cite each source by putting its exact URL inline where you use it, and "
        f"use no URLs other than the ones listed above.\n\n"
        f"If the source material is too thin for a 400-word grounded article, "
        f"return {empty_json} — an empty object with all empty strings.\n"
        f"Return ONLY the JSON object, no markdown fences, no commentary."
    )
    if feedback:
        prompt += f"\n\n{feedback}"
    return prompt


def parse_draft(text: str) -> dict | None:
    """Extract the draft dict from raw LLM output (fences tolerated)."""
    data = extract_json_object(text or "")
    if data is None:
        return None
    tags = data.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    return {
        "title": str(data.get("title") or "").strip(),
        "body_markdown": str(data.get("body_markdown") or "").strip(),
        "teaser": str(data.get("teaser") or "").strip(),
        "tags": [str(t).strip() for t in tags if str(t).strip()],
    }


def is_declined(draft: dict) -> bool:
    """The model returned the empty object: sources too thin."""
    return not draft.get("title") and not draft.get("body_markdown") and not draft.get("teaser")


def produce_article(
    cluster: list[dict],
    settings: Settings,
    llm: LLM,
    existing_titles: set[str] | None = None,
    max_attempts: int = 2,
) -> DraftOutcome:
    """Draft + validate, regenerating once with feedback on failure."""
    if not cluster:
        return DraftOutcome(errors=["empty cluster"], declined=True)

    system = load_system_prompt()
    feedback: str | None = None
    last_errors: list[str] = ["no attempt made"]

    for attempt in range(1, max_attempts + 1):
        user = build_user_prompt(cluster, feedback=feedback)
        try:
            raw = llm.complete(system, user, cluster=cluster)
        except LLMError as exc:
            logger.warning(kv("draft_llm_error", attempt=attempt, error=str(exc)))
            return DraftOutcome(errors=[f"llm error: {exc}"], attempts=attempt, declined=False)

        parsed = parse_draft(raw)
        if parsed is None:
            last_errors = ["response was not a JSON object"]
            feedback = "Your previous response was not valid JSON. Return ONLY the JSON object."
            logger.warning(kv("draft_parse_failed", attempt=attempt))
            continue

        if is_declined(parsed):
            logger.info(kv("draft_declined", attempt=attempt))
            return DraftOutcome(errors=["model declined: sources too thin"], attempts=attempt, declined=True)

        result = validate_article(parsed, cluster, settings, existing_titles)
        if result.ok:
            logger.info(kv("draft_valid", attempt=attempt, title=parsed["title"][:60]))
            return DraftOutcome(article=finalize_article(parsed, cluster), attempts=attempt)

        last_errors = result.errors
        feedback = result.as_feedback()
        logger.warning(kv("draft_invalid", attempt=attempt, errors=len(result.errors)))

    return DraftOutcome(errors=last_errors, attempts=max_attempts, declined=False)


__all__ = [
    "DraftOutcome",
    "build_source_block",
    "build_user_prompt",
    "derive_tags",
    "is_declined",
    "load_system_prompt",
    "parse_draft",
    "produce_article",
]
