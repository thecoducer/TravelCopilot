from types import SimpleNamespace

from app.llm import extract_llm_usage


def test_extracts_litellm_usage_and_response_cost() -> None:
    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=8, total_tokens=20),
        _hidden_params={"response_cost": 0.0042},
    )

    assert extract_llm_usage(response) == {
        "prompt_tokens": 12,
        "completion_tokens": 8,
        "total_tokens": 20,
        "cost_usd": 0.0042,
    }


def test_extracts_langchain_metadata_and_nested_cost() -> None:
    response = SimpleNamespace(
        usage_metadata={"input_tokens": 4, "output_tokens": 6, "total_tokens": 10},
        response_metadata={"response_cost": 0.0015},
    )

    assert extract_llm_usage(response) == {
        "prompt_tokens": 4,
        "completion_tokens": 6,
        "total_tokens": 10,
        "cost_usd": 0.0015,
    }


def test_extracts_token_usage_dict_from_response_metadata() -> None:
    response = SimpleNamespace(
        response_metadata={
            "token_usage": {
                "prompt_tokens": 7,
                "completion_tokens": 3,
                "total_tokens": 10,
            }
        }
    )

    assert extract_llm_usage(response)["total_tokens"] == 10
