#!/bin/sh
# Render pre-deploy command (BD-04): needs DATABASE_URL only. Idempotent.
# GeoNames is already in the image (downloaded during the Docker build).
set -e
alembic upgrade head
python -m scripts.reference.load_geonames
# --strict since spike S-2 confirmed every Wave 0 indicator code (BD-13): a placeholder
# code now stops the deploy instead of being skipped.
python -m scripts.reference.load_yaml_reference --strict
