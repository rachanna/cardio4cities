"""Local development (`poe dev`, REPO_STRUCTURE §4): the API on :8000 with reload and the
web app's `next dev` on :3000, which proxies /api to the API (BD-41). Stops both on Ctrl+C
or when either exits."""

import shutil
import subprocess
import sys
import time
from pathlib import Path

from scripts.web import WEB, install

ROOT = Path(__file__).resolve().parents[1]
API = [sys.executable, "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000"]


def main() -> int:
    npm = shutil.which("npm")
    if npm is None:
        print("npm was not found: install Node 22.12 or later", file=sys.stderr)
        return 1
    if not (WEB / "node_modules").is_dir():
        install()
    children = [
        subprocess.Popen(API, cwd=ROOT),  # noqa: S603 - fixed arguments
        subprocess.Popen([npm, "run", "dev"], cwd=WEB),  # noqa: S603 - fixed arguments
    ]
    print("API on http://127.0.0.1:8000, web app on http://localhost:3000")
    try:
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            child.wait(timeout=20)
    return max((child.returncode or 0) for child in children)


if __name__ == "__main__":
    sys.exit(main())
