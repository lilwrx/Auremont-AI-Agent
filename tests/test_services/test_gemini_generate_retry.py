"""Generation retries: transient faults must not read as quality failures.

Every answer and every Verifier judgement goes through `client_models_generate`. Before it
retried, one 503 or rate-limit blip failed the whole turn and landed in the Admin dashboard
looking exactly like an answer the Verifier had genuinely rejected.

The policy is deliberately tighter than the batch embedding loop's, because this sits on
the interactive path: one retry, transient codes only, capped backoff.
"""

import pytest
from google.genai import errors as genai_errors

from backend.core import gemini_client
from backend.core.config import settings


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text
        self.parsed = None


class _Usage:
    prompt_token_count = 120
    candidates_token_count = 45
    total_token_count = 165


def _api_error(code: int) -> genai_errors.APIError:
    error = genai_errors.APIError.__new__(genai_errors.APIError)
    error.code = code
    error.details = None
    return error


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """The backoff is real time; the assertions are about attempt counts, not duration."""
    monkeypatch.setattr(gemini_client.time, "sleep", lambda _seconds: None)


def _stub_generate(monkeypatch, outcomes: list):
    """Replay `outcomes` in order — an exception is raised, anything else returned."""
    calls = {"count": 0}

    class _Models:
        def generate_content(self, **_kwargs):
            outcome = outcomes[calls["count"]]
            calls["count"] += 1
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    class _Client:
        models = _Models()

    monkeypatch.setattr(gemini_client, "get_gemini_client", lambda: _Client())
    return calls


@pytest.mark.parametrize("code", sorted(gemini_client._GENERATE_RETRY_STATUS_CODES))
def test_a_transient_fault_is_retried_once_and_can_succeed(monkeypatch, code):
    calls = _stub_generate(monkeypatch, [_api_error(code), _FakeResponse("Đã trả lời.")])

    result = gemini_client.client_models_generate("câu hỏi", None)

    assert result.text == "Đã trả lời."
    assert calls["count"] == 2


def test_a_non_transient_error_is_not_retried(monkeypatch):
    """A 400 is a bad request — retrying it just doubles the latency of a certain failure."""
    calls = _stub_generate(monkeypatch, [_api_error(400)])

    with pytest.raises(genai_errors.APIError):
        gemini_client.client_models_generate("câu hỏi", None)

    assert calls["count"] == 1


def test_the_retry_budget_is_one_attempt_not_an_endless_loop(monkeypatch):
    calls = _stub_generate(monkeypatch, [_api_error(503), _api_error(503)])

    with pytest.raises(genai_errors.APIError):
        gemini_client.client_models_generate("câu hỏi", None)

    assert calls["count"] == gemini_client._GENERATE_MAX_ATTEMPTS == 2


def test_generate_text_goes_through_the_same_retry_path(monkeypatch):
    """It used to call the API directly, so it silently had no retry at all."""
    calls = _stub_generate(monkeypatch, [_api_error(429), _FakeResponse("Xin chào.")])

    assert gemini_client.generate_text("câu hỏi") == "Xin chào."
    assert calls["count"] == 2


def test_the_backoff_is_capped_so_a_long_retry_delay_cannot_stall_a_turn(monkeypatch):
    """A 429 can suggest tens of seconds — far past the field latency budget, where failing
    fast beats holding the Sale's screen."""
    slept: list[float] = []
    monkeypatch.setattr(gemini_client.time, "sleep", lambda seconds: slept.append(seconds))
    monkeypatch.setattr(gemini_client, "retry_delay_seconds", lambda _exc: 30.0)
    _stub_generate(monkeypatch, [_api_error(429), _FakeResponse("ok")])

    gemini_client.client_models_generate("câu hỏi", None)

    assert slept == [gemini_client._GENERATE_MAX_RETRY_DELAY_SECONDS]


def test_provider_usage_is_persisted_even_without_a_pipeline_trace(monkeypatch):
    response = _FakeResponse("ok")
    response.usage_metadata = _Usage()
    persisted: list[dict] = []
    monkeypatch.setattr(settings, "observability_metrics_enabled", True)
    monkeypatch.setattr("backend.core.observability_sink.persist_llm_usage", lambda **fields: persisted.append(fields))
    _stub_generate(monkeypatch, [response])

    gemini_client.client_models_generate("câu hỏi", None)

    assert len(persisted) == 1
    assert persisted[0]["run_id"] is None
    assert persisted[0]["input_tokens"] == 120
    assert persisted[0]["output_tokens"] == 45
    assert persisted[0]["total_tokens"] == 165
