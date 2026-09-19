"""Public LLM package API."""

from app.llm.concurrency import llm_semaphore
from app.llm.context import get_active_llm_run_id, reset_active_llm_run_id, set_active_llm_run_id
from app.llm.provider import get_llm, init_llm, try_enable_litellm_langfuse_callbacks
from app.llm.structured_output import StructuredOutputError, invoke_structured, structured_llm
from app.llm.telemetry import extract_llm_call_usage

__all__ = [
    "extract_llm_call_usage",
    "get_active_llm_run_id",
    "get_llm",
    "init_llm",
    "invoke_structured",
    "llm_semaphore",
    "reset_active_llm_run_id",
    "set_active_llm_run_id",
    "StructuredOutputError",
    "structured_llm",
    "try_enable_litellm_langfuse_callbacks",
]
