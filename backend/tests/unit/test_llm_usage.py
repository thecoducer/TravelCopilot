from types import SimpleNamespace

from app.llm import extract_llm_call_usage


def test_extracts_langchain_usage_metadata_and_hidden_cost() -> None:
    response = SimpleNamespace(
        usage_metadata={"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
        response_metadata={},
        _hidden_params={"response_cost": 0.0042},
    )

    usage = extract_llm_call_usage(response, model="openrouter/some-model")

    assert usage["input_tokens"] == 12
    assert usage["output_tokens"] == 8
    assert usage["total_tokens"] == 20
    assert usage["cost_usd"] == 0.0042


def test_prefers_openrouter_reported_cost_over_hidden_params() -> None:
    response = SimpleNamespace(
        usage_metadata={"input_tokens": 4, "output_tokens": 6, "total_tokens": 10},
        response_metadata={"token_usage": {"cost": 0.0009}},
        _hidden_params={"response_cost": 0.0015},
    )

    usage = extract_llm_call_usage(response, model="openrouter/some-model")

    assert usage["cost_usd"] == 0.0009


def test_extracts_reasoning_and_cached_tokens_from_raw_litellm_usage() -> None:
    response = SimpleNamespace(
        usage_metadata={},
        response_metadata={
            "token_usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
                "completion_tokens_details": {"reasoning_tokens": 30},
                "prompt_tokens_details": {"cached_tokens": 20},
            }
        },
    )

    usage = extract_llm_call_usage(response, model="openrouter/some-model")

    assert usage["reasoning_tokens"] == 30
    assert usage["cached_tokens"] == 20
    assert usage["total_tokens"] == 150


def test_falls_back_to_cost_per_token_when_no_reported_cost(monkeypatch) -> None:
    monkeypatch.setattr(
        "litellm.cost_per_token",
        lambda model, prompt_tokens, completion_tokens: (0.001, 0.002),
    )
    response = SimpleNamespace(
        usage_metadata={"input_tokens": 10, "output_tokens": 10, "total_tokens": 20},
        response_metadata={},
    )

    usage = extract_llm_call_usage(response, model="openai/gpt-4o")

    assert usage["cost_usd"] == 0.003
