FROM python:3.14-slim AS builder

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen


FROM python:3.14-slim

RUN pip install --no-cache-dir uv

RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

COPY --from=builder /app/.venv .venv

COPY src/ src/
COPY config/ config/
COPY main.py .

ENV PYTHONPATH=/app/src
ENV PATH="/app/.venv/bin:$PATH"

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

CMD ["python", "main.py"]
