import pytest

from app.main import configure_logging


@pytest.fixture(autouse=True, scope="session")
def setup_logging() -> None:
    configure_logging()
