# Application image (REPO_STRUCTURE §5).
# Still to come: a Node stage that builds web/out (D1-4) and WeasyPrint system
# libraries (verified in a spike).

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
COPY config ./config
COPY reference/*.yaml ./reference/
COPY reference/geonames/README.md ./reference/geonames/
COPY scripts/__init__.py ./scripts/
COPY scripts/reference ./scripts/reference

# The reference loader downloads GeoNames into reference/geonames when run in the container.
RUN useradd --system --uid 10001 c4c && chown -R c4c /srv/reference/geonames
USER c4c

EXPOSE 8000
# Migrations need DATABASE_URL only; the app then refuses to start until reference data is loaded.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
