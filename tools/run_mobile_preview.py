#!/usr/bin/env python
"""Launch the Lyra dev server and open a mobile-sized browser preview."""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "http://127.0.0.1:5000/"
DEFAULT_WIDTH = 390
DEFAULT_HEIGHT = 844
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Flask server and open a browser window sized like a phone.",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="URL to open once the server is responding (default: %(default)s)",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=DEFAULT_WIDTH,
        help="Viewport width in pixels for the preview window (default: %(default)s)",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=DEFAULT_HEIGHT,
        help="Viewport height in pixels for the preview window (default: %(default)s)",
    )
    parser.add_argument(
        "--browser",
        help="Path or executable name of a Chromium browser (Chrome/Edge/Chromium).",
    )
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help="User-Agent string to spoof for the preview tab.",
    )
    parser.add_argument(
        "--skip-open",
        action="store_true",
        help="Only run the server; do not launch a browser window.",
    )
    return parser.parse_args()


def candidate_browser_paths() -> list[str]:
    names = [
        os.environ.get("MOBILE_PREVIEW_BROWSER"),
        "chrome",
        "google-chrome",
        "chromium",
        "chromium-browser",
        "msedge",
        "edge",
        "brave",
    ]
    candidates: list[str] = [name for name in names if name]

    # Common Windows install paths for Chrome/Edge if not on PATH.
    windows_paths = [
        Path(os.environ.get("ProgramFiles", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe",
    ]
    for path in windows_paths:
        if path and path.exists():
            candidates.append(str(path))

    return candidates


def find_browser(explicit: str | None) -> str | None:
    if explicit:
        explicit_path = shutil.which(explicit) if not Path(explicit).exists() else explicit
        if explicit_path:
            return explicit_path

    for candidate in candidate_browser_paths():
        if not candidate:
            continue
        if Path(candidate).exists():
            return str(Path(candidate))
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def wait_for_server(url: str, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except (urllib.error.URLError, ConnectionError, TimeoutError, ConnectionRefusedError):
            time.sleep(0.5)
    return False


def open_browser(browser: str, url: str, width: int, height: int, user_agent: str) -> None:
    args = [
        browser,
        "--new-window",
        f"--window-size={width},{height}",
        f"--user-agent={user_agent}",
        url,
    ]
    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Failed to launch browser '{browser}': {exc}") from exc


def main() -> int:
    args = parse_args()

    server_cmd = [sys.executable, "web/server.py"]
    env = os.environ.copy()

    server_proc = subprocess.Popen(server_cmd, cwd=REPO_ROOT)

    def _handle_exit(signum: int, frame) -> None:  # type: ignore[override]
        if server_proc.poll() is None:
            server_proc.terminate()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _handle_exit)
    signal.signal(signal.SIGTERM, _handle_exit)

    print("?? Starting Flask server via python web/server.py ...", flush=True)
    if wait_for_server(args.url):
        print(f"? Server responding at {args.url}", flush=True)
    else:
        print(
            f"??  Server did not respond within timeout. Check logs above and refresh {args.url} manually.",
            flush=True,
        )

    if not args.skip_open:
        browser_path = find_browser(args.browser)
        if browser_path:
            print(
                f"?? Opening {browser_path} at {args.url} with window {args.width}x{args.height} (mobile UA)",
                flush=True,
            )
            try:
                open_browser(browser_path, args.url, args.width, args.height, args.user_agent)
            except RuntimeError as exc:
                print(f"??  {exc}", flush=True)
        else:
            print(
                "??  Could not locate Chrome/Edge. Launch a browser manually or set MOBILE_PREVIEW_BROWSER.",
                flush=True,
            )

    try:
        server_proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        if server_proc.poll() is None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_proc.kill()
        print("?? Server stopped.", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
