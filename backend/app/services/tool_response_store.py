"""Versioned local response recording and exact-match replay."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel

from app.config import (
    TOOL_RESPONSE_EXECUTION_MODE_KEY,
    TOOL_RESPONSE_FILENAME_SEPARATOR,
    TOOL_RESPONSE_FINGERPRINT_PREFIX,
    TOOL_RESPONSE_JSON_SUFFIX,
    TOOL_RESPONSE_REAL_MODE,
    TOOL_RESPONSE_REDACTED_VALUE,
    TOOL_RESPONSE_SCHEMA_VERSION,
    TOOL_RESPONSE_SENSITIVE_KEY_PARTS,
    TOOL_RESPONSE_SENSITIVE_QUERY_KEYS,
    TOOL_RESPONSE_STATUS_SUCCESS,
    TOOL_RESPONSE_TEMP_SUFFIX,
    TOOL_RESPONSE_TIMESTAMP_FORMAT,
    settings,
)


class ToolResponseStore:
    """Persist sanitized invocation envelopes and replay exact successful matches."""

    def __init__(self, response_dir: str | None = None, retention_days: int | None = None) -> None:
        self._root = self._resolve_root(response_dir or settings.tool_response_dir)
        self._retention_days = retention_days or settings.tool_response_retention_days
        self._write_lock = Lock()
        self._cleanup()

    @property
    def root(self) -> Path:
        return self._root

    def fingerprint(self, arguments: dict[str, Any]) -> str:
        canonical_arguments = self._canonicalize(arguments)
        payload = json.dumps(canonical_arguments, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"{TOOL_RESPONSE_FINGERPRINT_PREFIX}{digest}"

    def find_latest_success(
        self, tool_name: str, request_fingerprint: str
    ) -> dict[str, Any] | None:
        matches = self._matching_envelopes(tool_name, request_fingerprint)
        if not matches:
            return None
        matches.sort(key=self._recorded_at, reverse=True)
        return matches[0]

    def write(self, envelope: dict[str, Any]) -> Path | None:
        if not settings.tool_response_recording_enabled:
            return None
        tool_name = str(envelope["tool_name"])
        tool_dir = self._tool_directory(tool_name)
        tool_dir.mkdir(parents=True, exist_ok=True)
        self._cleanup()
        recorded_at = datetime.now(UTC)
        payload = self._canonicalize(envelope)
        payload["schema_version"] = TOOL_RESPONSE_SCHEMA_VERSION
        with self._write_lock:
            filename = self._unique_filename(tool_name, recorded_at, tool_dir)
            temporary_path: Path | None = None
            try:
                file_descriptor, temporary_name = tempfile.mkstemp(
                    dir=tool_dir,
                    prefix=f"{filename}{TOOL_RESPONSE_TEMP_SUFFIX}",
                    text=True,
                )
                temporary_path = Path(temporary_name)
                with os.fdopen(file_descriptor, "w", encoding="utf-8") as response_file:
                    json.dump(payload, response_file, sort_keys=True, indent=2)
                    response_file.write("\n")
                temporary_path.replace(tool_dir / filename)
            finally:
                if temporary_path and temporary_path.exists():
                    temporary_path.unlink()
        return tool_dir / filename

    def _resolve_root(self, configured_dir: str) -> Path:
        repository_root = Path(__file__).resolve().parents[3]
        configured_path = Path(configured_dir)
        resolved_path = (repository_root / configured_path).resolve()
        if repository_root not in resolved_path.parents and resolved_path != repository_root:
            raise ValueError("TOOL_RESPONSE_DIR must remain inside the repository root")
        return resolved_path

    def _tool_directory(self, tool_name: str) -> Path:
        safe_tool_name = Path(tool_name).name
        return self._root / safe_tool_name

    def _unique_filename(self, tool_name: str, recorded_at: datetime, tool_dir: Path) -> str:
        timestamp = recorded_at.strftime(TOOL_RESPONSE_TIMESTAMP_FORMAT)
        base_name = f"{tool_name}{TOOL_RESPONSE_FILENAME_SEPARATOR}{timestamp}"
        candidate = f"{base_name}{TOOL_RESPONSE_JSON_SUFFIX}"
        suffix = 1
        while (tool_dir / candidate).exists():
            candidate = (
                f"{base_name}{TOOL_RESPONSE_FILENAME_SEPARATOR}{suffix}{TOOL_RESPONSE_JSON_SUFFIX}"
            )
            suffix += 1
        return candidate

    def _matching_envelopes(self, tool_name: str, request_fingerprint: str) -> list[dict[str, Any]]:
        tool_dir = self._tool_directory(tool_name)
        if not tool_dir.exists():
            return []
        envelopes: list[dict[str, Any]] = []
        for path in tool_dir.glob(f"*{TOOL_RESPONSE_JSON_SUFFIX}"):
            try:
                envelope = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if self._is_replay_match(envelope, tool_name, request_fingerprint):
                envelopes.append(envelope)
        return envelopes

    def _is_replay_match(
        self,
        envelope: object,
        tool_name: str,
        request_fingerprint: str,
    ) -> bool:
        if not isinstance(envelope, dict):
            return False
        return (
            envelope.get("schema_version") == TOOL_RESPONSE_SCHEMA_VERSION
            and envelope.get("tool_name") == tool_name
            and envelope.get("request_fingerprint") == request_fingerprint
            and envelope.get(TOOL_RESPONSE_EXECUTION_MODE_KEY) == TOOL_RESPONSE_REAL_MODE
            and envelope.get("status") == TOOL_RESPONSE_STATUS_SUCCESS
            and isinstance(envelope.get("normalized_result"), dict)
        )

    def _recorded_at(self, envelope: dict[str, Any]) -> datetime:
        value = envelope.get("recorded_at")
        if not isinstance(value, str):
            return datetime.min.replace(tzinfo=UTC)
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.min.replace(tzinfo=UTC)

    def _cleanup(self) -> None:
        if not self._root.exists():
            return
        cutoff = datetime.now(UTC) - timedelta(days=self._retention_days)
        for path in self._root.glob(f"*/*{TOOL_RESPONSE_JSON_SUFFIX}"):
            try:
                if datetime.fromtimestamp(path.stat().st_mtime, UTC) < cutoff:
                    path.unlink()
            except OSError:
                continue

    def _canonicalize(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): self._redact_value(str(key), item)
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            }
        if isinstance(value, (list, tuple)):
            return [self._canonicalize(item) for item in value]
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, BaseModel):
            return self._canonicalize(value.model_dump(mode="json"))
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, str):
            return self._sanitize_string(value)
        return value

    def _redact_value(self, key: str, value: Any) -> Any:
        normalized_key = key.lower().replace("-", "_")
        if any(part in normalized_key for part in TOOL_RESPONSE_SENSITIVE_KEY_PARTS):
            return TOOL_RESPONSE_REDACTED_VALUE
        return self._canonicalize(value)

    def _sanitize_string(self, value: str) -> str:
        parsed = urlsplit(value)
        if not parsed.scheme or not parsed.netloc:
            return value
        username = parsed.username
        hostname = parsed.hostname or ""
        netloc = hostname
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        if username or parsed.password:
            netloc = TOOL_RESPONSE_REDACTED_VALUE
        query = urlencode(
            [
                (
                    key,
                    TOOL_RESPONSE_REDACTED_VALUE
                    if key.lower() in TOOL_RESPONSE_SENSITIVE_QUERY_KEYS
                    else item,
                )
                for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            ]
        )
        return urlunsplit((parsed.scheme, netloc, parsed.path, query, parsed.fragment))
