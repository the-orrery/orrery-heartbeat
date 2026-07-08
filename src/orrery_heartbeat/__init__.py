"""Lightweight update-check for orrery CLI tools.

Usage: call check_update() once at CLI entry point.

    from orrery_heartbeat import check_update

    def main():
        check_update("my-tool", "the-orrery/my-tool")
        ...
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

__version__ = "0.1.0"

_DEFAULT_HOURS = 6
_CACHE_DIR = (
    Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "orrery-heartbeat"
)


def check_update(
    tool: str,
    repo: str,
    *,
    hours: int = _DEFAULT_HOURS,
    upgrade_command: str = "orrery-upgrade",
) -> None:
    """Check GitHub for a newer commit on main; print a one-line hint if found.

    Non-blocking: network failures and all exceptions are silently swallowed.
    Skipped in CI, non-TTY, or if checked within *hours*.
    """
    try:
        _check(tool, repo, hours, upgrade_command)
    except Exception:
        pass


def _check(tool: str, repo: str, hours: int, upgrade_command: str) -> None:
    if not sys.stderr.isatty():
        return
    if os.environ.get("CI") or os.environ.get("ORRERY_NO_UPDATE_CHECK"):
        return

    state_file = _CACHE_DIR / tool / "state.json"
    state = _load_state(state_file)

    if state and (time.time() - state.get("checked_at", 0)) < hours * 3600:
        return

    latest_sha = _fetch_latest_sha(repo)
    if not latest_sha:
        return

    _save_state(state_file, latest_sha)

    installed_sha = _installed_sha(tool, state)
    if not installed_sha:
        # 首次运行：记录当前版本，不提示
        return

    if latest_sha != installed_sha:
        print(
            f"  {tool}: update available ({installed_sha[:7]}→{latest_sha[:7]}),"
            f" run `{upgrade_command}`",
            file=sys.stderr,
        )


def _fetch_latest_sha(repo: str) -> str:
    """GET /repos/{repo}/commits/main → latest commit SHA."""
    url = f"https://api.github.com/repos/{repo}/commits/main"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github.sha"})
    with urllib.request.urlopen(req, timeout=3) as resp:
        return resp.read().decode().strip()


def _load_state(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _save_state(path: Path, latest_sha: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state = _load_state(path) or {}
    state["checked_at"] = time.time()
    state["latest_sha"] = latest_sha
    path.write_text(json.dumps(state), encoding="utf-8")


def _installed_sha(tool: str, state: dict | None) -> str:
    """Return the SHA recorded at last install/upgrade, or empty string."""
    if state:
        return state.get("installed_sha", "")
    return ""


def mark_installed(tool: str, sha: str) -> None:
    """Record the installed SHA after uv tool install. Called by orrery-upgrade."""
    state_file = _CACHE_DIR / tool / "state.json"
    state = _load_state(state_file) or {}
    state["installed_sha"] = sha
    state["checked_at"] = time.time()
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state), encoding="utf-8")
