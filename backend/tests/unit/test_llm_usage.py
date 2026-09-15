import asyncio
from datetime import datetime
from types import SimpleNamespace

from app.llm import UsageLogger, _callback_metadata, extract_llm_usage


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


def test_reads_metadata_from_litellm_callback_payload() -> None:
    assert _callback_metadata(
        {"litellm_params": {"metadata": {"agent_name": "safety", "session_id": "sess"}}}
    ) == {"agent_name": "safety", "session_id": "sess"}


def test_async_usage_callback_queues_usage(monkeypatch) -> None:
    queued: list[tuple[str, str, dict[str, int | float]]] = []
    monkeypatch.setattr("app.llm._ensure_usage_worker", lambda: None)
    monkeypatch.setattr("app.llm._usage_queue.put", queued.append)

    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=8, total_tokens=20),
        _hidden_params={"response_cost": 0.0042},
    )

    asyncio.run(
        UsageLogger().async_log_success_event(
            {"litellm_params": {"metadata": {"agent_name": "safety", "session_id": "sess"}}},
            response,
            datetime.now(),
            datetime.now(),
        )
    )

    assert queued[0][0:2] == ("safety", "sess")
    assert queued[0][2]["total_tokens"] == 20
    assert queued[0][2]["cost_usd"] == 0.0042
