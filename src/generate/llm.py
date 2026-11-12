"""LLM access: Groq (primary + fallback model) and an offline stub.

The interface is a single method::

    complete(system: str, user: str, cluster: list[dict] | None = None) -> str

``GroqLLM`` retries 429/timeout with backoff (via :mod:`src.util.http`) and then
falls back to ``GROQ_MODEL_FALLBACK``. ``OfflineStubLLM`` deterministically
builds a grounded article from the supplied cluster so a fresh clone can run
``--use-fixtures --dry-run`` without any key or network.

Reasoning models (``openai/gpt-oss-*``) think before they answer and bill that
thinking to the same completion budget as the answer. Left at the default
effort, gpt-oss-20b spends *every* token on ``reasoning`` and returns
``content: ""`` with ``finish_reason: "length"`` — which looks like a dead
model and costs the day's article. So reasoning models are asked for
``reasoning_effort: low`` and, if a response is still cut off at the budget,
the model is retried once with a much larger one before falling through to the
next model.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..config import Settings
from ..util.http import HttpError, RetryPolicy, request
from ..util.logging_setup import kv
from .validate import derive_tags

logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

#: Model-name fragments whose models spend completion tokens on hidden
#: reasoning before emitting ``content`` (see the module docstring).
REASONING_MODEL_HINTS = ("gpt-oss",)

#: Effort passed for those models. ``low`` keeps reasoning to a few dozen
#: tokens; ``medium`` alone burned 8192 tokens and returned nothing at all.
REASONING_EFFORT = "low"

#: Budget used for the one retry a budget-truncated response earns.
TRUNCATION_RETRY_MAX_TOKENS = 8192


class LLMError(RuntimeError):
    """Raised when no configured model produced usable output."""


class LLM(Protocol):
    """Anything that can turn a system+user prompt into text."""

    def complete(self, system: str, user: str, cluster: list[dict] | None = None) -> str: ...


@dataclass
class GroqLLM:
    """Groq chat completions with retry, backoff and a fallback model."""

    settings: Settings
    models: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.models:
            self.models = [self.settings.groq_model]
            if self.settings.groq_model_fallback and self.settings.groq_model_fallback not in self.models:
                self.models.append(self.settings.groq_model_fallback)

    def _payload(self, model: str, system: str, user: str, max_tokens: int | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.settings.groq_temperature,
            "max_tokens": max_tokens or self.settings.groq_max_tokens,
        }
        if _is_reasoning_model(model):
            payload["reasoning_effort"] = REASONING_EFFORT
        return payload

    def complete(self, system: str, user: str, cluster: list[dict] | None = None) -> str:
        if not self.settings.groq_api_key:
            raise LLMError("GROQ_API_KEY is not set")

        headers = {
            "Authorization": f"Bearer {self.settings.groq_api_key}",
            "Content-Type": "application/json",
        }
        policy = RetryPolicy(
            attempts=max(1, self.settings.groq_max_attempts),
            backoff_base=1.0,
            backoff_max=20.0,
            timeout=self.settings.groq_timeout,
        )

        problems: list[str] = []
        for model in self.models:
            content = self._complete_with_model(model, system, user, headers, policy, problems)
            if content is not None:
                return content

        raise LLMError("all models failed → " + " | ".join(problems))

    def _complete_with_model(
        self,
        model: str,
        system: str,
        user: str,
        headers: dict[str, str],
        policy: RetryPolicy,
        problems: list[str],
    ) -> str | None:
        """One model's answer, or ``None`` after recording why it failed.

        A response cut off at the token budget is retried once with a larger
        one: for reasoning models that means the thinking ate the budget, and
        for the rest it means the JSON was truncated mid-object.
        """
        budget = self.settings.groq_max_tokens
        while True:
            try:
                response = request(
                    "POST", GROQ_URL, headers=headers, json=self._payload(model, system, user, budget), policy=policy
                )
                choice = response.json()["choices"][0]
                content = choice["message"].get("content") or ""
                finish_reason = choice.get("finish_reason")
            except HttpError as exc:
                problems.append(f"{model}: {exc}")
                logger.warning(kv("llm_model_failed", model=model, error=str(exc)))
                return None
            except (AttributeError, KeyError, IndexError, TypeError, ValueError) as exc:
                problems.append(f"{model}: unexpected response shape ({type(exc).__name__})")
                logger.warning(kv("llm_bad_response", model=model, error=str(exc)))
                return None

            if finish_reason == "length" and budget < TRUNCATION_RETRY_MAX_TOKENS:
                logger.warning(kv("llm_truncated", model=model, max_tokens=budget, chars=len(content)))
                budget = TRUNCATION_RETRY_MAX_TOKENS
                continue

            if finish_reason == "length":
                # Still cut off at the larger budget: half an answer (usually
                # half a JSON object) is worthless, so let the next model try.
                problems.append(f"{model}: response truncated at {budget} tokens")
                logger.warning(kv("llm_truncated_exhausted", model=model, max_tokens=budget))
                return None

            if not content.strip():
                problems.append(f"{model}: empty content (finish_reason={finish_reason})")
                logger.warning(kv("llm_empty_content", model=model, finish_reason=finish_reason))
                return None

            logger.info(kv("llm_completed", model=model, chars=len(content)))
            return content


def _is_reasoning_model(model: str) -> bool:
    """Whether *model* hides reasoning tokens inside the completion budget."""
    return any(hint in model.lower() for hint in REASONING_MODEL_HINTS)


# ---------------------------------------------------------------------------
# Offline stub
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"https?://\S+")


def _stub_tags(cluster: list[dict]) -> list[str]:
    return derive_tags(cluster) or ["technology"]


def _stub_body(cluster: list[dict], settings: Settings) -> tuple[str, str]:
    """Deterministic, grounded body built only from the cluster's own words."""
    sentences: list[str] = []
    for item in cluster:
        title = (item.get("title") or "").strip()
        content = " ".join((item.get("content") or "").split())
        url = item.get("url") or ""
        source = item.get("source") or "a source"
        if title:
            sentences.append(f"{title} was reported by {source} ({url}).")
        if content:
            chunk = " ".join(content.split()[:70]).strip()
            if chunk:
                sentences.append(chunk if chunk.endswith(".") else chunk + ".")
    for item in cluster:
        content = " ".join((item.get("content") or "").split())
        rest = " ".join(content.split()[70:170]).strip()
        if rest:
            sentences.append(rest if rest.endswith(".") else rest + ".")

    words = " ".join(sentences).split()
    low, high = settings.article_min_words, settings.article_max_words
    # Deterministic pad/trim so the stub always lands inside the word window.
    pool = words[:]
    while len(words) < low and pool:
        words.extend(pool[: low - len(words)])
    if len(words) > high:
        words = words[:high]
    body = " ".join(words).strip()
    if not body.endswith("."):
        body += "."

    teaser_words = " ".join(sentences).split()
    teaser = " ".join(teaser_words[:24]).strip()
    if len(teaser) > settings.teaser_max_len:
        teaser = teaser[: settings.teaser_max_len - 1].rstrip() + "…"
    return body, teaser


@dataclass
class OfflineStubLLM:
    """Deterministic stand-in used only for the fully offline smoke test."""

    settings: Settings

    def complete(self, system: str, user: str, cluster: list[dict] | None = None) -> str:
        cluster = cluster or []
        if not cluster:
            return json.dumps({"title": "", "body_markdown": "", "teaser": "", "tags": []})
        label = (cluster[0].get("title") or "Trending").strip()
        title = label[: self.settings.title_max_len].strip()
        body, teaser = _stub_body(cluster, self.settings)
        return json.dumps(
            {"title": title, "body_markdown": body, "teaser": teaser, "tags": _stub_tags(cluster)},
            ensure_ascii=False,
        )


def build_llm(settings: Settings) -> LLM:
    """Return the offline stub in offline mode, else the Groq client."""
    if settings.offline:
        logger.warning(
            kv(
                "offline_llm",
                note="offline mode (no GROQ_API_KEY / TCE_OFFLINE): using deterministic stub output",
            )
        )
        return OfflineStubLLM(settings)
    return GroqLLM(settings)
