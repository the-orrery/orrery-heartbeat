"""Low-noise update checks for Orrery GitHub Release installations."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

__version__ = "0.2.0"

_DEFAULT_HOURS = 6
_CACHE_DIR = (
    Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "orrery-heartbeat"
)


def check_update(
    tool: str,
    repo: str,
    *,
    hours: int = _DEFAULT_HOURS,
    upgrade_command: str = "orrery-upgrade --apply",
) -> None:
    """Print a non-blocking hint when a newer stable GitHub Release exists."""
    with contextlib.suppress(Exception):
        _check(tool, repo, hours, upgrade_command)


def _check(tool: str, repo: str, hours: int, upgrade_command: str) -> None:
    if not sys.stderr.isatty():
        return
    if os.environ.get("CI") or os.environ.get("ORRERY_NO_UPDATE_CHECK"):
        return

    state_file = _CACHE_DIR / tool / "state.json"
    state = _load_state(state_file)
    if state and (time.time() - state.get("checked_at", 0)) < hours * 3600:
        return

    latest_tag = _fetch_latest_tag(repo)
    if not latest_tag:
        return
    _save_state(state_file, latest_tag=latest_tag)

    installed_tag = (state or {}).get("installed_tag", "")
    if installed_tag and latest_tag != installed_tag:
        print(
            f"  {tool}: update available ({installed_tag}→{latest_tag}),"
            f" run `{upgrade_command}`",
            file=sys.stderr,
        )


def _fetch_latest_tag(repo: str) -> str:
    """Return the latest stable GitHub Release tag."""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "orrery-heartbeat",
    }
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=3) as response:
        payload = json.load(response)
    tag = payload.get("tag_name")
    return tag if isinstance(tag, str) else ""


def _load_state(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save_state(path: Path, *, latest_tag: str) -> None:
    state = _load_state(path) or {}
    state["checked_at"] = time.time()
    state["latest_tag"] = latest_tag
    _write_state(path, state)


def _write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state), encoding="utf-8")
    temporary.replace(path)


def mark_installed(tool: str, tag: str) -> None:
    """Record a verified release installed by ``orrery-upgrade``."""
    state_file = _CACHE_DIR / tool / "state.json"
    state = _load_state(state_file) or {}
    state["installed_tag"] = tag
    state["latest_tag"] = tag
    state["checked_at"] = time.time()
    _write_state(state_file, state)
