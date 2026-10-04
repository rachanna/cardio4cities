"""Writes the API's OpenAPI document for the web app's generated types (`poe types`,
REPO_STRUCTURE §4). No settings or stores are needed: the document comes from the routes."""

import json
import sys
from pathlib import Path

from app.main import create_app

OUT = Path(__file__).resolve().parents[1] / "web" / "lib" / "openapi.json"


def main() -> int:
    OUT.write_text(json.dumps(create_app(env_file=None).openapi(), indent=1), encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
