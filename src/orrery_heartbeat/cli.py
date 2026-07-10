"""Install or upgrade Orrery CLI tools from immutable GitHub Release assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import mark_installed

ORG = "the-orrery"
TOOL_ASSETS: dict[str, tuple[str, ...]] = {
    "almagest": ("almagest",),
    "crux": ("crux",),
    "docket": ("docket", "pm"),
    "memex": ("memex", "memex-sync"),
    "orrery-heartbeat": ("orrery-upgrade", "orrery-env"),
    "pharos": ("pharos",),
    "registrar": ("registrar",),
    "rhizome": ("rhizome",),
    "seed": ("seed",),
}
TOOLS = tuple(TOOL_ASSETS)


@dataclass(frozen=True)
class Release:
    tag: str
    download_base: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orrery-upgrade",
        description="Install Orrery CLI tools from verified GitHub Release assets.",
    )
    parser.add_argument(
        "tools",
        nargs="*",
        metavar="TOOL",
        help="tool(s) to upgrade; defaults to all managed CLI repositories",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="download, verify, and atomically install; otherwise print the plan",
    )
    parser.add_argument(
        "--list", action="store_true", help="list managed repositories and assets"
    )
    parser.add_argument(
        "--dry-run", "--plan", action="store_true", help="print the install plan"
    )
    parser.add_argument(
        "--bin-dir",
        type=Path,
        default=None,
        help="install directory (default: ORRERY_BIN_DIR or ~/.local/bin)",
    )
    parser.add_argument(
        "--timeout", type=float, default=30.0, help="download timeout in seconds"
    )
    return parser


def run(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    tools = _select_tools(args.tools, parser)
    bin_dir = _bin_dir(args.bin_dir)

    if args.list:
        for tool, assets in TOOL_ASSETS.items():
            print(f"{tool}: {', '.join(assets)}")
        return

    if args.dry_run or not args.apply:
        _print_plan(tools, bin_dir)
        if not args.apply:
            suffix = f" {' '.join(tools)}" if args.tools else ""
            print(f"\nRun `orrery-upgrade --apply{suffix}` to install.")
        return

    failed: list[str] = []
    for tool in tools:
        print(f"  {tool}: ", end="", flush=True)
        try:
            tag = _install_tool(tool, bin_dir=bin_dir, timeout=args.timeout)
        except Exception as exc:  # noqa: BLE001 - one repo must not block the fleet
            print("✗")
            print(f"    {exc}", file=sys.stderr)
            failed.append(tool)
            continue
        mark_installed(tool, tag)
        print(f"✓ {tag}")

    if failed:
        print(f"\n  {len(failed)} failed: {', '.join(failed)}", file=sys.stderr)
        raise SystemExit(1)
    print(f"\n  {len(tools)} repositories up to date in {bin_dir}")


def _select_tools(requested: list[str], parser: argparse.ArgumentParser) -> list[str]:
    if not requested:
        return list(TOOLS)
    unknown = sorted(set(requested) - set(TOOLS))
    if unknown:
        parser.error(f"unknown tool(s): {', '.join(unknown)}")
    return requested


def _bin_dir(value: Path | None) -> Path:
    configured = value or Path(os.environ.get("ORRERY_BIN_DIR", "~/.local/bin"))
    return configured.expanduser().resolve()


def _platform() -> tuple[str, str]:
    import platform

    os_name = {"Darwin": "darwin", "Linux": "linux"}.get(platform.system())
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x86_64"}.get(
        platform.machine().lower()
    )
    if not os_name or not arch:
        raise RuntimeError(
            f"unsupported platform: {platform.system()} {platform.machine()}"
        )
    return os_name, arch


def _repo(tool: str) -> str:
    return f"{ORG}/{tool}"


def _print_plan(tools: list[str], bin_dir: Path) -> None:
    platform_name, arch = _platform()
    for tool in tools:
        assets = ", ".join(
            f"{name}-{platform_name}-{arch} -> {bin_dir / name}"
            for name in TOOL_ASSETS[tool]
        )
        print(f"{tool}: latest verified GitHub Release ({assets})")


def _request(url: str) -> urllib.request.Request:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "orrery-heartbeat",
    }
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


def _fetch_latest_release(repo: str, *, timeout: float) -> Release:
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    with urllib.request.urlopen(_request(url), timeout=timeout) as response:
        payload = json.load(response)
    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not tag:
        raise RuntimeError(f"{repo}: latest release has no tag_name")
    return Release(tag, f"https://github.com/{repo}/releases/download/{tag}")


def _download(url: str, destination: Path, *, timeout: float) -> None:
    with urllib.request.urlopen(_request(url), timeout=timeout) as response:
        with destination.open("wb") as output:
            shutil.copyfileobj(response, output)


def _parse_checksums(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) != 2:
            continue
        digest, name = parts
        name = name.lstrip("*")
        if len(digest) == 64:
            result[name] = digest.lower()
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _install_tool(tool: str, *, bin_dir: Path, timeout: float) -> str:
    platform_name, arch = _platform()
    release = _fetch_latest_release(_repo(tool), timeout=timeout)
    asset_names = {
        binary: f"{binary}-{platform_name}-{arch}" for binary in TOOL_ASSETS[tool]
    }
    bin_dir.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".orrery-{tool}-", dir=bin_dir))
    try:
        checksum_file = stage / "SHA256SUMS"
        _download(f"{release.download_base}/SHA256SUMS", checksum_file, timeout=timeout)
        checksums = _parse_checksums(checksum_file.read_text(encoding="utf-8"))
        staged: dict[str, Path] = {}
        for binary, asset in asset_names.items():
            expected = checksums.get(asset)
            if not expected:
                raise RuntimeError(
                    f"{tool} {release.tag}: checksum missing for {asset}"
                )
            path = stage / asset
            _download(f"{release.download_base}/{asset}", path, timeout=timeout)
            actual = _sha256(path)
            if actual != expected:
                raise RuntimeError(
                    f"{tool} {release.tag}: checksum mismatch for {asset}"
                )
            path.chmod(0o755)
            staged[binary] = path
        _atomic_replace(staged, bin_dir=bin_dir, stage=stage)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return release.tag


def _atomic_replace(staged: dict[str, Path], *, bin_dir: Path, stage: Path) -> None:
    backups: dict[str, Path] = {}
    installed: list[str] = []
    try:
        for binary in staged:
            target = bin_dir / binary
            if target.exists():
                backup = stage / f"{binary}.previous"
                os.replace(target, backup)
                backups[binary] = backup
        for binary, source in staged.items():
            os.replace(source, bin_dir / binary)
            installed.append(binary)
    except Exception:
        for binary in installed:
            (bin_dir / binary).unlink(missing_ok=True)
        for binary, backup in backups.items():
            if backup.exists():
                os.replace(backup, bin_dir / binary)
        raise
