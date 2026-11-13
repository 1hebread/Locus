# Pinned by digest — bump tag and digest together (Dependabot can do it).
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

# Install uv 0.13.7 from the official binary image (digest-pinned)
COPY --from=ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 /uv /uvx /bin/

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
