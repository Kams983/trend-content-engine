"""Tests for :mod:`src.generate.llm` — the Groq client's model handling.

``requests`` is never used: ``src.generate.llm.request`` is monkeypatched with a
scripted fake, so the tests assert the *payloads* sent to Groq (this is where
the gpt-oss reasoning budget bug lived) and the fallback behaviour.
"""

from __future__ import annotations

import pytest

from src.config import Settings
from src.generate import llm as llm_mod
from src.generate.llm import LLMError, GroqLLM
from src.util.http import HttpError


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def completion(content: str, finish_reason: str = "stop") -> FakeResponse:
    return FakeResponse(
        {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish_reason}]}
    )


@pytest.fixture
def groq_settings(tmp_path) -> Settings:
    return Settings(
        db_path=tmp_path / "test.sqlite",
        content_posts_dir=tmp_path / "posts",
        groq_api_key="test-key",
        groq_model="qwen/qwen3.8-27b",
        groq_model_fallback="openai/gpt-oss-20b",
    )


class Recorder:
    """Scripted stand-in for ``llm.request`` that records every payload."""

    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.payloads: list[dict] = []

    def __call__(self, method, url, *, headers=None, json=None, policy=None):
        self.payloads.append(json)
        if not self.responses:
            raise AssertionError("more requests than scripted responses")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_reasoning_model_is_asked_for_low_effort(monkeypatch, groq_settings):
    recorder = Recorder([completion('{"title": "ok"}')])
    monkeypatch.setattr(llm_mod, "request", recorder)
    llm = GroqLLM(groq_settings, models=["openai/gpt-oss-20b"])

    assert llm.complete("system", "user") == '{"title": "ok"}'
    assert recorder.payloads[0]["reasoning_effort"] == llm_mod.REASONING_EFFORT


def test_non_reasoning_model_sends_no_reasoning_effort(monkeypatch, groq_settings):
    recorder = Recorder([completion('{"title": "ok"}')])
    monkeypatch.setattr(llm_mod, "request", recorder)
    llm = GroqLLM(groq_settings, models=["qwen/qwen3.8-27b"])

    llm.complete("system", "user")
    assert "reasoning_effort" not in recorder.payloads[0]


def test_budget_truncated_response_is_retried_with_a_larger_budget(monkeypatch, groq_settings):
    # What gpt-oss-20b actually returned: every token spent reasoning, no content.
    recorder = Recorder([completion("", "length"), completion('{"title": "rescued"}')])
    monkeypatch.setattr(llm_mod, "request", recorder)
    llm = GroqLLM(groq_settings, models=["openai/gpt-oss-20b"])

    assert llm.complete("system", "user") == '{"title": "rescued"}'
    assert [p["max_tokens"] for p in recorder.payloads] == [
        groq_settings.groq_max_tokens,
        llm_mod.TRUNCATION_RETRY_MAX_TOKENS,
    ]
    assert recorder.payloads[1]["model"] == "openai/gpt-oss-20b"


def test_truncated_json_that_stays_truncated_falls_back_to_the_next_model(monkeypatch, groq_settings):
    recorder = Recorder(
        [
            completion('{"title": "half a ti', "length"),
            completion('{"title": "still', "length"),
            completion('{"title": "from the fallback"}'),
        ]
    )
    monkeypatch.setattr(llm_mod, "request", recorder)
    llm = GroqLLM(groq_settings)

    assert llm.complete("system", "user") == '{"title": "from the fallback"}'
    assert [p["model"] for p in recorder.payloads] == [
        "qwen/qwen3.8-27b",
        "qwen/qwen3.8-27b",
        "openai/gpt-oss-20b",
    ]


def test_empty_content_without_truncation_falls_back(monkeypatch, groq_settings):
    recorder = Recorder([completion(""), completion('{"title": "fallback"}')])
    monkeypatch.setattr(llm_mod, "request", recorder)
    llm = GroqLLM(groq_settings)

    assert llm.complete("system", "user") == '{"title": "fallback"}'
    assert len(recorder.payloads) == 2


def test_no_model_producing_content_raises_with_every_reason(monkeypatch, groq_settings):
    recorder = Recorder([HttpError("POST groq → HTTP 429"), completion("", "length"), completion("", "length")])
    monkeypatch.setattr(llm_mod, "request", recorder)
    llm = GroqLLM(groq_settings)

    with pytest.raises(LLMError) as excinfo:
        llm.complete("system", "user")
    message = str(excinfo.value)
    assert "qwen/qwen3.8-27b: POST groq → HTTP 429" in message
    assert f"openai/gpt-oss-20b: response truncated at {llm_mod.TRUNCATION_RETRY_MAX_TOKENS} tokens" in message


def test_missing_api_key_is_reported_before_any_request(monkeypatch, tmp_path):
    settings = Settings(db_path=tmp_path / "t.sqlite", content_posts_dir=tmp_path / "p", groq_api_key="")
    recorder = Recorder([])
    monkeypatch.setattr(llm_mod, "request", recorder)

    with pytest.raises(LLMError, match="GROQ_API_KEY"):
        GroqLLM(settings, models=["openai/gpt-oss-20b"]).complete("system", "user")
    assert recorder.payloads == []
