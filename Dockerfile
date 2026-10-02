# Application image (REPO_STRUCTURE §5).
# Still to come: a Node stage that builds web/out (D1-4), WeasyPrint system
# libraries (verified in a spike), config/ and reference/*.yaml (D1-2, D1-3),
# and running migrations before Uvicorn (D1-3).

FROM python:3.12-slim AS app

COPY --from=ghcr.io/astral-sh/uv:0.12.22 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR /srv

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev

COPY app ./app

RUN useradd --system --uid 10001 c4c
USER c4c

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
