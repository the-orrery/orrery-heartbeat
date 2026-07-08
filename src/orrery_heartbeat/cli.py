"""orrery-upgrade: install/upgrade all orrery CLI tools from GitHub main."""

from __future__ import annotations

import argparse
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orrery-upgrade",
        description="Install or upgrade orrery CLI tools from GitHub main.",
    )
    parser.add_argument(
        "tools",
        nargs="*",
        metavar="TOOL",
        help="tool(s) to upgrade; defaults to all managed tools",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="run uv installs; without this flag, only print the plan",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list managed tools and exit without installing",
    )
    parser.add_argument(
        "--dry-run",
        "--plan",
        action="store_true",
        help="print the uv install commands without running them",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="per-tool uv install timeout in seconds",
    )
    return parser


def run(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    tools = _select_tools(args.tools, parser)

    if args.list:
        for tool in TOOLS:
            print(tool)
        return

    if args.dry_run or not args.apply:
        _print_plan(tools)
        if not args.apply:
            suffix = f" {' '.join(tools)}" if args.tools else ""
            print(f"\nRun `orrery-upgrade --apply{suffix}` to install.")
        return

    failed: list[str] = []
    for tool in tools:
        print(f"  {tool}: ", end="", flush=True)
        result = _install_tool(tool, timeout=args.timeout)
        if result.returncode != 0:
            print("✗")
            detail = result.stderr.strip() or result.stdout.strip()
            if detail:
                print(f"    {detail}", file=sys.stderr)
            failed.append(tool)
            continue

        sha = ""
        with contextlib.suppress(Exception):
            sha = _fetch_latest_sha(_repo(tool))
        if sha:
            mark_installed(tool, sha)
        print("✓")

    if failed:
        print(f"\n  {len(failed)} failed: {', '.join(failed)}", file=sys.stderr)
        raise SystemExit(1)
    print(f"\n  {len(tools)} tools up to date")


def _select_tools(requested: list[str], parser: argparse.ArgumentParser) -> list[str]:
    if not requested:
        return TOOLS.copy()
    unknown = sorted(set(requested) - set(TOOLS))
    if unknown:
        parser.error(f"unknown tool(s): {', '.join(unknown)}")
    return requested


def _repo(tool: str) -> str:
    return f"{ORG}/{tool}"


def _git_url(tool: str) -> str:
    return f"git+ssh://git@github.com/{_repo(tool)}.git"


def _install_command(tool: str) -> list[str]:
    return ["uv", "tool", "install", "--from", _git_url(tool), tool, "--force"]


def _print_plan(tools: list[str]) -> None:
    for tool in tools:
        print(" ".join(_install_command(tool)))


def _install_tool(tool: str, *, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*_install_command(tool), "--quiet"],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
