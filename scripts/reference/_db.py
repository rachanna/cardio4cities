"""DATABASE_URL is the only setting the reference loaders need (not full settings validation)."""

import os

from dotenv import load_dotenv

from app.adapters.postgres.relational import PostgresRelational


def relational_from_env() -> PostgresRelational:
    load_dotenv(".env", override=False)
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("DATABASE_URL is not set; it is the only setting the loaders need")
    return PostgresRelational(url)
