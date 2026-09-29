FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY sre_agent/ ./sre_agent/
COPY --from=frontend /build/dist ./frontend/dist
RUN useradd --uid 10001 --create-home app
USER 10001
ENV PATH="/app/.venv/bin:$PATH" PORT=8080 PYTHONUNBUFFERED=1
CMD ["sh", "-c", "exec uvicorn sre_agent.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
