"""Local development (`poe dev`, REPO_STRUCTURE §4): the tools-and-prompts MCP server
(E-15, BD-60), the API on :8000 with reload, and the web app's `next dev` on :3000, which
proxies /api to the API (BD-41). The API reaches search and its prompts through the MCP
server unless TOOLS_VIA_MCP=0. Stops all on Ctrl+C or when any exits."""

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from scripts.web import WEB, install

ROOT = Path(__file__).resolve().parents[1]
API = [sys.executable, "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000"]
MCP = [sys.executable, "-m", "app.mcp_server"]
MCP_ADDRESS = ("127.0.0.1", 8100)  # mcp.host and mcp.port in the local profiles
MCP_READY_S = 30


def _wait_for(address: tuple[str, int], process: subprocess.Popen[bytes], seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and process.poll() is None:
        try:
            with socket.create_connection(address, timeout=0.5):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def main() -> int:
    npm = shutil.which("npm")
    if npm is None:
        print("npm was not found: install Node 22.12 or later", file=sys.stderr)
        return 1
    if not (WEB / "node_modules").is_dir():
        install()
    children: list[subprocess.Popen[bytes]] = []
    env = dict(os.environ)
    if env.get("TOOLS_VIA_MCP", "1") != "0":
        server = subprocess.Popen(MCP, cwd=ROOT)  # noqa: S603 - fixed arguments
        children.append(server)
        if not _wait_for(MCP_ADDRESS, server, MCP_READY_S):
            print("the tools-and-prompts server did not start", file=sys.stderr)
            server.terminate()
            return 1
        env["TOOLS_VIA_MCP"] = "1"
    children += [
        subprocess.Popen(API, cwd=ROOT, env=env),  # noqa: S603 - fixed arguments
        subprocess.Popen([npm, "run", "dev"], cwd=WEB),  # noqa: S603 - fixed arguments
    ]
    via = " (search and prompts through the MCP server on :8100)" if len(children) == 3 else ""
    print(f"API on http://127.0.0.1:8000{via}, web app on http://localhost:3000")
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
