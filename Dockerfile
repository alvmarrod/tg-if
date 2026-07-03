FROM python:3.14-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libc6-dev && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen


FROM python:3.14-slim

RUN pip install --no-cache-dir uv

ARG APP_UID=999
RUN groupadd -g $APP_UID appuser && useradd -g appuser -u $APP_UID -m appuser

WORKDIR /app

COPY --from=builder /app/.venv .venv

COPY src/ src/
# config/ is not baked in — mount config/bots.json at /app/config
COPY main.py .

ENV PYTHONPATH=/app/src
ENV PATH="/app/.venv/bin:$PATH"

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

CMD ["python", "main.py"]
