FROM python:3.12-slim

WORKDIR /app

# Install system dependencies (libpq5 required by psycopg pure-Python impl at runtime)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install Python dependencies
COPY pyproject.toml .
RUN uv pip install --system -e ".[dev]"

# Copy application code (overridden by volume mount in dev)
COPY . .

# Lint + format check (fails the build on violations)
RUN ruff format --check app/ && ruff check app/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
