"""orrery-upgrade: install/upgrade all orrery CLI tools from GitHub main."""

from __future__ import annotations

import contextlib
import subprocess
import sys

from . import _fetch_latest_sha, mark_installed

ORG = "the-orrery"
TOOLS = [
    "registrar",
    "docket",
    "crux",
    "pharos",
    "memex",
    "rhizome",
    "almagest",
    "seed",
    "orrery-heartbeat",
]


def run() -> None:
    failed: list[str] = []
    for tool in TOOLS:
        repo = f"{ORG}/{tool}"
        git_url = f"git+ssh://git@github.com/{repo}.git"
        print(f"  {tool}: ", end="", flush=True)
        result = subprocess.run(
            ["uv", "tool", "install", "--from", git_url, tool, "--force", "--quiet"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print("✗")
            detail = result.stderr.strip() or result.stdout.strip()
            if detail:
                print(f"    {detail}", file=sys.stderr)
            failed.append(tool)
            continue

        sha = ""
        with contextlib.suppress(Exception):
            sha = _fetch_latest_sha(repo)
        if sha:
            mark_installed(tool, sha)
        print("✓")

    if failed:
        print(f"\n  {len(failed)} failed: {', '.join(failed)}", file=sys.stderr)
        raise SystemExit(1)
    print(f"\n  {len(TOOLS)} tools up to date")
