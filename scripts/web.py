"""The web app's npm steps for poe (REPO_STRUCTURE §4, BD-41): `build` writes the static
export to web/out; `types` regenerates web/lib/api-types.ts from the API's OpenAPI document.
npm is looked up on PATH so that `npm.cmd` works on Windows too."""

import shutil
import subprocess
import sys
from pathlib import Path

from scripts import openapi

WEB = Path(__file__).resolve().parents[1] / "web"


def npm(*args: str) -> None:
    found = shutil.which("npm")
    if found is None:
        raise SystemExit("npm was not found: install Node 22.12 or later")
    subprocess.run([found, *args], cwd=WEB, check=True)  # noqa: S603 - fixed arguments


def install() -> None:
    npm("ci", "--no-audit", "--no-fund")


def main(argv: list[str]) -> int:
    match argv:
        case ["build"]:
            install()
            npm("run", "build")
        case ["types"]:
            openapi.main()
            if not (WEB / "node_modules").is_dir():
                install()
            npm("run", "types")
        case _:
            print("usage: python -m scripts.web build|types", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
