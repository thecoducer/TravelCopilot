"""Apply SQL migrations at application startup.

Migration files under ``backend/migrations`` are written to be idempotent
(``IF NOT EXISTS`` guards and self-healing ``ALTER``s), so running them on every
startup keeps the schema in sync without relying on a manual ``make migrate``
step. Each file manages its own transaction via ``BEGIN``/``COMMIT``.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from app.db import engine

logger = structlog.get_logger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


async def run_migrations() -> None:
    """Execute every ``*.sql`` migration in lexical order."""
    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not sql_files:
        logger.warning("no_migrations_found", path=str(MIGRATIONS_DIR))
        return

    async with engine.connect() as conn:
        raw_connection = await conn.get_raw_connection()
        driver_connection = raw_connection.driver_connection
        if driver_connection is None:
            raise RuntimeError("Database driver connection is unavailable")
        for sql_file in sql_files:
            sql = sql_file.read_text(encoding="utf-8")
            await driver_connection.execute(sql)
            logger.info("migration_applied", file=sql_file.name)
