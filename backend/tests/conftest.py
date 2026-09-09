import os

os.environ.setdefault("LLM_PROVIDER", "openai")
os.environ.setdefault("LLM_MODEL", "gpt-4o")
os.environ.setdefault("APP_ENV", "production")

import pytest

from app.main import configure_logging


@pytest.fixture(autouse=True)
def setup_logging() -> None:
    configure_logging()
