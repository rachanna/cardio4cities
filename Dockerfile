# Application image (REPO_STRUCTURE §5, BD-04).
# Still to come: a Node stage that builds web/out (D3-4) and WeasyPrint system
# libraries (verified in a spike). Until then FastAPI serves web/placeholder at /.

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

COPY scripts/__init__.py ./scripts/
COPY scripts/reference ./scripts/reference
COPY reference/geonames/README.md ./reference/geonames/
COPY app ./app
# GeoNames is downloaded at build time (BD-04): deploys never depend on download.geonames.org.
RUN python -m scripts.reference.load_geonames --download-only

COPY config ./config
COPY reference/*.yaml ./reference/
COPY scripts/start.sh scripts/predeploy.sh ./scripts/
COPY web/placeholder ./web/placeholder

RUN useradd --system --uid 10001 c4c
USER c4c

EXPOSE 8000
# Migrations and reference loading run as Render's pre-deploy command (scripts/predeploy.sh).
CMD ["sh", "scripts/start.sh"]
