#!/bin/sh
# Render pre-deploy command (BD-04): needs DATABASE_URL only. Idempotent.
# GeoNames is already in the image (downloaded during the Docker build).
set -e
alembic upgrade head
python -m scripts.reference.load_geonames
# Add --strict once spike S-2 confirms the WHO and DHS indicator codes (BD-04).
python -m scripts.reference.load_yaml_reference
