#!/bin/sh
# Container start (REPO_STRUCTURE §5, BD-04). No migrations here: Render runs
# scripts/predeploy.sh as the pre-deploy command before each release starts.
# On Render, NEO4J_HOST and QDRANT_HOST come from the private services; the URLs
# are built here because a blueprint cannot join strings.
set -e
if [ -n "$NEO4J_HOST" ] && [ -z "$NEO4J_URI" ]; then export NEO4J_URI="bolt://$NEO4J_HOST:7687"; fi
if [ -n "$QDRANT_HOST" ] && [ -z "$QDRANT_URL" ]; then export QDRANT_URL="http://$QDRANT_HOST:6333"; fi
# Shared store secrets use a STORE_ prefix: the Neo4j image treats every NEO4J_*
# variable as a setting and refuses to start on an unknown one (BD-04).
if [ -n "$STORE_NEO4J_PASSWORD" ] && [ -z "$NEO4J_PASSWORD" ]; then export NEO4J_PASSWORD="$STORE_NEO4J_PASSWORD"; fi
if [ -n "$STORE_QDRANT_API_KEY" ] && [ -z "$QDRANT_API_KEY" ]; then export QDRANT_API_KEY="$STORE_QDRANT_API_KEY"; fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
