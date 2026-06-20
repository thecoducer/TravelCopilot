"""Shared helpers for mock tools."""

from __future__ import annotations

import json
import pathlib
from typing import Any

# Resolve once at import time — reliable regardless of cwd.
_FIXTURES_DIR = (
    pathlib.Path(__file__)
    .resolve()
    .parent.parent.parent.parent  # mock/  # tools/  # app/  # backend/
    / "tests"
    / "fixtures"
)


def load_fixture(filename: str) -> dict[str, Any]:
    """Load a JSON fixture file from tests/fixtures/."""
    path = _FIXTURES_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Fixture not found: {path}")
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def find_fixture(prefix: str, *keys: str) -> dict[str, Any] | None:
    """Try to find a fixture by matching {prefix}_{key1}_{key2}.json.
    Falls back to any file matching {prefix}_*.json.
    Returns None if no file exists at all.
    """
    slug = "_".join(k.lower().replace(" ", "_") for k in keys)
    exact = _FIXTURES_DIR / f"{prefix}_{slug}.json"
    if exact.exists():
        result: dict[str, Any] = json.loads(exact.read_text(encoding="utf-8"))
        return result

    # Fallback: first available file with the given prefix
    candidates = sorted(_FIXTURES_DIR.glob(f"{prefix}_*.json"))
    if candidates:
        fallback: dict[str, Any] = json.loads(candidates[0].read_text(encoding="utf-8"))
        return fallback

    return None
