# Application image (REPO_STRUCTURE §5, BD-04). Two stages: Node builds the web app's
# static export (BD-41), then the Python image serves it at / with the API. Reports are
# PDFs from fpdf2, which needs no system libraries (BD-40).

FROM node:22.20-slim AS web

WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web ./
RUN npm run build

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

# GeoNames is downloaded at build time (BD-04): deploys never depend on download.geonames.org.
# Before the app code, with the standard-library helper only, so a code change does not
# download it again (BD-36); the helper checks each file is whole and logs its SHA-256.
COPY scripts/__init__.py ./scripts/
COPY scripts/reference/__init__.py scripts/reference/geonames.py ./scripts/reference/
COPY reference/geonames/README.md ./reference/geonames/
RUN python -c "from scripts.reference.geonames import download; download()"

COPY scripts/reference ./scripts/reference
COPY app ./app

COPY config ./config
COPY reference/*.yaml ./reference/
COPY scripts/start.sh scripts/predeploy.sh ./scripts/
COPY --from=web /web/out ./web/out

RUN useradd --system --uid 10001 c4c
USER c4c

EXPOSE 8000
# Migrations and reference loading run as Render's pre-deploy command (scripts/predeploy.sh).
CMD ["sh", "scripts/start.sh"]
