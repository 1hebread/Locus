FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

# Install uv from official binary image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy dependency configuration and readme
COPY pyproject.toml uv.lock README.md ./

# Copy source code and migration scripts
COPY src/ ./src/
COPY migrations/ ./migrations/
COPY alembic.ini ./

# Install locus and all production dependencies
RUN uv pip install --system --no-cache -e .

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn locus.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
