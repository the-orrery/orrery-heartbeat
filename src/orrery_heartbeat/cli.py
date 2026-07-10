"""Install or upgrade Orrery CLI tools from immutable GitHub Release assets."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import _ssl_context
from .receipt import (
    InstalledAsset,
    InstallReceipt,
    dumps,
    load,
    receipt_name,
    receipt_path,
    sha256,
    verify,
)

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
CHECKSUM_FIELD_COUNT = 2
SHA256_HEX_LENGTH = 64


@dataclass(frozen=True)
class Release:
    tag: str
    download_base: str


@dataclass(frozen=True)
class ToolRequest:
    tool: str
    tag: str | None = None


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
        "--verify",
        action="store_true",
        help="verify installed binaries against local release receipts",
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
    tools = _select_tools(args.tools, parser, allow_tags=True)
    bin_dir = _bin_dir(args.bin_dir)

    if args.apply and args.verify:
        parser.error("--apply and --verify are mutually exclusive")

    if args.verify:
        _verify_tools(tools, bin_dir)
        return

    if args.dry_run or not args.apply:
        _print_plan(tools, bin_dir)
        if not args.apply:
            suffix = f" {' '.join(args.tools)}" if args.tools else ""
            print(f"\nRun `orrery-upgrade --apply{suffix}` to install.")
        return

    failed: list[str] = []
    for request in tools:
        tool = request.tool
        print(f"  {tool}: ", end="", flush=True)
        try:
            receipt = _install_tool(
                tool, tag=request.tag, bin_dir=bin_dir, timeout=args.timeout
            )
        except Exception as exc:
            print("✗")
            print(f"    {exc}", file=sys.stderr)
            failed.append(tool)
            continue
        print(f"✓ {receipt.tag}")

    if failed:
        print(f"\n  {len(failed)} failed: {', '.join(failed)}", file=sys.stderr)
        raise SystemExit(1)
    print(f"\n  {len(tools)} repositories up to date in {bin_dir}")


def _select_tools(
    requested: list[str], parser: argparse.ArgumentParser, *, allow_tags: bool
) -> list[ToolRequest]:
    if not requested:
        return [ToolRequest(tool) for tool in TOOLS]
    result: list[ToolRequest] = []
    for value in requested:
        tool, separator, tag = value.partition("@")
        if separator and (not allow_tags or not tag or not tag.startswith("v")):
            parser.error(f"invalid tool selection: {value}")
        result.append(ToolRequest(tool, tag or None))
    unknown = sorted({item.tool for item in result} - set(TOOLS))
    if unknown:
        parser.error(f"unknown tool(s): {', '.join(unknown)}")
    return result


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
        message = f"unsupported platform: {platform.system()} {platform.machine()}"
        raise RuntimeError(message)
    return os_name, arch


def _repo(tool: str) -> str:
    return f"{ORG}/{tool}"


def _print_plan(tools: list[ToolRequest], bin_dir: Path) -> None:
    platform_name, arch = _platform()
    for request in tools:
        tool = request.tool
        desired = request.tag or "latest"
        assets = ", ".join(
            f"{name}-{platform_name}-{arch} -> {bin_dir / name}"
            for name in TOOL_ASSETS[tool]
        )
        print(f"{tool}: {desired} verified GitHub Release ({assets})")


def _verify_tools(tools: list[ToolRequest], bin_dir: Path) -> None:
    failed: list[str] = []
    for request in tools:
        tool = request.tool
        path = receipt_path(tool, bin_dir)
        try:
            receipt = load(path)
            errors = _verify_receipt(receipt, tool=tool, bin_dir=bin_dir)
            if request.tag and receipt.tag != request.tag:
                errors.append(f"tag is {receipt.tag}, expected {request.tag}")
        except RuntimeError as exc:
            errors = [str(exc)]
            receipt = None
        if errors:
            failed.append(tool)
            print(f"{tool}: ✗", file=sys.stderr)
            for error in errors:
                print(f"  {error}", file=sys.stderr)
        else:
            assert receipt is not None
            print(f"{tool}: ✓ {receipt.tag}")
    if failed:
        print(f"\n{len(failed)} failed: {', '.join(failed)}", file=sys.stderr)
        raise SystemExit(1)


def _verify_receipt(receipt: InstallReceipt, *, tool: str, bin_dir: Path) -> list[str]:
    errors = verify(receipt, tool=tool, bin_dir=bin_dir)
    expected_assets = set(TOOL_ASSETS[tool])
    actual_assets = {asset.name for asset in receipt.assets}
    if actual_assets != expected_assets:
        errors.append(
            f"asset set is {sorted(actual_assets)}, expected {sorted(expected_assets)}"
        )
    platform_name, arch = _platform()
    expected_platform = f"{platform_name}-{arch}"
    if receipt.platform != expected_platform:
        errors.append(f"platform is {receipt.platform}, expected {expected_platform}")
    return errors


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
    with urllib.request.urlopen(
        _request(url), timeout=timeout, context=_ssl_context()
    ) as response:
        payload = json.load(response)
    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not tag:
        message = f"{repo}: latest release has no tag_name"
        raise RuntimeError(message)
    return Release(tag, f"https://github.com/{repo}/releases/download/{tag}")


def _fetch_release(repo: str, *, tag: str | None, timeout: float) -> Release:
    if tag:
        return Release(tag, f"https://github.com/{repo}/releases/download/{tag}")
    return _fetch_latest_release(repo, timeout=timeout)


def _download(url: str, destination: Path, *, timeout: float) -> None:
    with (
        urllib.request.urlopen(
            _request(url), timeout=timeout, context=_ssl_context()
        ) as response,
        destination.open("wb") as output,
    ):
        shutil.copyfileobj(response, output)


def _parse_checksums(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) != CHECKSUM_FIELD_COUNT:
            continue
        digest, name = parts
        name = name.lstrip("*")
        if len(digest) == SHA256_HEX_LENGTH:
            result[name] = digest.lower()
    return result


def _install_tool(
    tool: str, *, tag: str | None = None, bin_dir: Path, timeout: float
) -> InstallReceipt:
    platform_name, arch = _platform()
    release = _fetch_release(_repo(tool), tag=tag, timeout=timeout)
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
                message = f"{tool} {release.tag}: checksum missing for {asset}"
                raise RuntimeError(message)
            path = stage / asset
            _download(f"{release.download_base}/{asset}", path, timeout=timeout)
            actual = sha256(path)
            if actual != expected:
                message = f"{tool} {release.tag}: checksum mismatch for {asset}"
                raise RuntimeError(message)
            path.chmod(0o755)
            staged[binary] = path
        receipt = InstallReceipt(
            repo=_repo(tool),
            tag=release.tag,
            platform=f"{platform_name}-{arch}",
            assets=tuple(
                InstalledAsset(
                    name=binary,
                    release_asset=asset_names[binary],
                    target=bin_dir / binary,
                    sha256=checksums[asset_names[binary]],
                )
                for binary in TOOL_ASSETS[tool]
            ),
        )
        receipt_file = stage / receipt_name(tool)
        receipt_file.write_text(dumps(receipt), encoding="utf-8")
        staged[receipt_name(tool)] = receipt_file
        _atomic_replace(staged, bin_dir=bin_dir, stage=stage)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return receipt


def _atomic_replace(staged: dict[str, Path], *, bin_dir: Path, stage: Path) -> None:
    backups: dict[str, Path] = {}
    installed: list[str] = []
    try:
        for binary in staged:
            target = bin_dir / binary
            if target.exists() or target.is_symlink():
                backup = stage / f"{binary}.previous"
                target.replace(backup)
                backups[binary] = backup
        for binary, source in staged.items():
            source.replace(bin_dir / binary)
            installed.append(binary)
    except Exception:
        for binary in installed:
            (bin_dir / binary).unlink(missing_ok=True)
        for binary, backup in backups.items():
            if backup.exists():
                backup.replace(bin_dir / binary)
        raise
