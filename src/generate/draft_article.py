"""Generate a short article from the top-ranked cluster of trending items.

Calls the Groq API (OpenAI-compatible). The model is configurable via
GROQ_MODEL (default ``openai/gpt-oss-120b``) with GROQ_MODEL_FALLBACK used
after retryable failures. Returns {title, body_markdown, teaser} or None if
the source material is too thin for a 400-word article.
"""

import json
import logging
import os
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "openai/gpt-oss-120b"
_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "article_prompt.txt"


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8").strip()


def _build_source_block(cluster: list[dict]) -> str:
    """Format cluster items into a source block for the LLM."""
    parts: list[str] = []
    for i, item in enumerate(cluster, 1):
        title = item.get("title", "")
        content = item.get("content", "")[:500]
        url = item.get("url", "")
        source = item.get("source", "")
        parts.append(f"[{i}] ({source}) {title}\n{content}\nURL: {url}")
    return "\n\n".join(parts)


def _build_user_prompt(cluster: list[dict]) -> str:
    source_block = _build_source_block(cluster)
    empty_json = json.dumps({"title": "", "body_markdown": "", "teaser": ""})
    return (
        f"Write a 400-600 word article about the trend represented by these "
        f"{len(cluster)} source items.\n\n"
        f"SOURCE ITEMS:\n\n{source_block}\n\n"
        f"Return your response as a JSON object with exactly these keys:\n"
        f'  "title": a short, specific headline\n'
        f'  "body_markdown": the article body in Markdown (400-600 words)\n'
        f'  "teaser": a standalone social post under 200 characters\n\n'
        f"If the source material is too thin for a 400-word article with "
        f"real substance, return {empty_json} — an empty object with "
        f"all empty strings.\n"
        f"Return ONLY the JSON object, no markdown fences, no commentary."
    )


def _parse_response(text: str) -> dict | None:
    """Extract {title, body_markdown, teaser} from LLM output."""
    text = text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in the text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start:end])
            except json.JSONDecodeError:
                logger.warning("Could not parse LLM response as JSON")
                return None
        else:
            logger.warning("No JSON object found in LLM response")
            return None

    title = (data.get("title") or "").strip()
    body = (data.get("body_markdown") or "").strip()
    teaser = (data.get("teaser") or "").strip()

    if not title or not body:
        return None

    return {"title": title, "body_markdown": body, "teaser": teaser}


def draft_article(cluster: list[dict]) -> dict | None:
    """Generate an article from the top-ranked cluster.

    Returns {title, body_markdown, teaser} or None if the source
    material is insufficient or the API call fails.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        logger.error("GROQ_API_KEY not set")
        return None

    if not cluster:
        logger.warning("Empty cluster — nothing to write about")
        return None

    system_prompt = _load_system_prompt()
    user_prompt = _build_user_prompt(cluster)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 2048,
    }

    try:
        resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
    except Exception as exc:
        logger.error("Groq API call failed: %s", exc)
        return None

    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        logger.error("Unexpected Groq response shape: %s", exc)
        return None

    return _parse_response(content)
