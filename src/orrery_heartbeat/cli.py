"""Install or upgrade Orrery CLI tools from immutable GitHub Release assets."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from . import _ssl_context
from .launchers import launcher_script
from .receipt import (
    InstalledAsset,
    InstallReceipt,
    dumps,
    load,
    payload_name,
    receipt_name,
    receipt_path,
    sha256,
    tree_sha256,
    verify,
)
from .registry import DEFAULT_TOOLS, TOOL_SPECS, TOOLS

CHECKSUM_FIELD_COUNT = 2
SHA256_HEX_LENGTH = 64


@dataclass(frozen=True)
class Release:
    tag: str
    download_base: str
    assets: dict[str, str] | None = None


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
    tools = _validate_platforms(tools, parser, explicit=bool(args.tools))
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
        return [ToolRequest(tool) for tool in DEFAULT_TOOLS]
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
    return TOOL_SPECS[tool].repo


def _platform_id() -> str:
    platform_name, arch = _platform()
    return f"{platform_name}-{arch}"


def _validate_platforms(
    requests: list[ToolRequest], parser: argparse.ArgumentParser, *, explicit: bool
) -> list[ToolRequest]:
    platform_id = _platform_id()
    supported = [
        request
        for request in requests
        if platform_id in TOOL_SPECS[request.tool].platforms
    ]
    unavailable = [
        request.tool
        for request in requests
        if platform_id not in TOOL_SPECS[request.tool].platforms
    ]
    if unavailable and explicit:
        parser.error(f"unsupported on {platform_id}: {', '.join(sorted(unavailable))}")
    return supported


def _print_plan(tools: list[ToolRequest], bin_dir: Path) -> None:
    platform_name, arch = _platform()
    for request in tools:
        tool = request.tool
        desired = request.tag or "latest"
        assets = ", ".join(
            f"{name}-{platform_name}-{arch}.tar.gz -> {bin_dir / name}"
            for name in TOOL_SPECS[tool].assets
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
    spec = TOOL_SPECS[tool]
    errors = verify(receipt, tool=tool, expected_repo=spec.repo, bin_dir=bin_dir)
    expected_assets = set(spec.assets)
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
    return urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "orrery-heartbeat",
        },
    )


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


def _fetch_release(tool: str, *, tag: str | None, timeout: float) -> Release:
    spec = TOOL_SPECS[tool]
    if spec.access == "gh":
        return _fetch_authenticated_release(spec.repo, tag=tag, timeout=timeout)
    repo = spec.repo
    if tag:
        return Release(tag, f"https://github.com/{repo}/releases/download/{tag}")
    return _fetch_latest_release(repo, timeout=timeout)


def _fetch_authenticated_release(
    repo: str, *, tag: str | None, timeout: float
) -> Release:
    endpoint = (
        f"repos/{repo}/releases/tags/{tag}" if tag else f"repos/{repo}/releases/latest"
    )
    payload = _gh_api_json(endpoint, timeout=timeout)
    release_tag = payload.get("tag_name")
    if not isinstance(release_tag, str) or not release_tag:
        raise RuntimeError(f"{repo}: release has no tag_name")
    raw_assets = payload.get("assets")
    if not isinstance(raw_assets, list):
        raise TypeError(f"{repo} {release_tag}: release has no asset list")
    assets: dict[str, str] = {}
    for raw_asset in raw_assets:
        if not isinstance(raw_asset, dict):
            continue
        name = raw_asset.get("name")
        url = raw_asset.get("url")
        if isinstance(name, str) and name and isinstance(url, str) and url:
            assets[name] = url
    return Release(release_tag, "", assets)


def _gh_api_json(endpoint: str, *, timeout: float) -> dict[str, object]:
    result = _run_gh(["api", "--hostname", "github.com", endpoint], timeout=timeout)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"GitHub API returned invalid JSON for {endpoint}") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"GitHub API returned invalid payload for {endpoint}")
    return payload


def _run_gh(
    args: list[str], *, timeout: float, stdout: int | object = subprocess.PIPE
) -> subprocess.CompletedProcess:
    if not shutil.which("gh"):
        raise RuntimeError(
            "authenticated release requires GitHub CLI; install `gh`, then run "
            "`gh auth login` or provide GH_TOKEN/GITHUB_TOKEN"
        )
    try:
        return subprocess.run(
            ["gh", *args],
            check=True,
            stdout=stdout,
            stderr=subprocess.PIPE,
            text=stdout == subprocess.PIPE,
            timeout=timeout,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if isinstance(exc.stderr, str) else ""
        detail = stderr or f"exit {exc.returncode}"
        raise RuntimeError(f"GitHub CLI request failed: {detail}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"GitHub CLI request timed out after {timeout:g}s") from exc


def _download(url: str, destination: Path, *, timeout: float) -> None:
    with (
        urllib.request.urlopen(
            _request(url), timeout=timeout, context=_ssl_context()
        ) as response,
        destination.open("wb") as output,
    ):
        shutil.copyfileobj(response, output)


def _download_release_asset(
    release: Release,
    name: str,
    destination: Path,
    *,
    access: str,
    timeout: float,
) -> None:
    if access == "public":
        _download(f"{release.download_base}/{name}", destination, timeout=timeout)
        return
    if access != "gh" or release.assets is None:
        raise RuntimeError(f"unsupported release access policy: {access}")
    url = release.assets.get(name)
    if not url:
        raise RuntimeError(f"{release.tag}: release asset missing: {name}")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "api.github.com":
        raise RuntimeError(f"{release.tag}: unsafe release asset URL for {name}")
    endpoint = parsed.path.lstrip("/")
    with destination.open("wb") as output:
        _run_gh(
            [
                "api",
                "--hostname",
                "github.com",
                "-H",
                "Accept: application/octet-stream",
                endpoint,
            ],
            timeout=timeout,
            stdout=output,
        )


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
    spec = TOOL_SPECS[tool]
    platform_name, arch = _platform()
    release = _fetch_release(tool, tag=tag, timeout=timeout)
    asset_names = {
        binary: f"{binary}-{platform_name}-{arch}.tar.gz" for binary in spec.assets
    }
    bin_dir.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".orrery-{tool}-", dir=bin_dir))
    try:
        checksum_file = stage / "SHA256SUMS"
        _download_release_asset(
            release,
            "SHA256SUMS",
            checksum_file,
            access=spec.access,
            timeout=timeout,
        )
        checksums = _parse_checksums(checksum_file.read_text(encoding="utf-8"))
        payload = stage / payload_name(tool)
        payload.mkdir()
        release_hashes: dict[str, str] = {}
        for binary, asset in asset_names.items():
            expected = checksums.get(asset)
            if not expected:
                message = f"{tool} {release.tag}: checksum missing for {asset}"
                raise RuntimeError(message)
            path = stage / asset
            _download_release_asset(
                release, asset, path, access=spec.access, timeout=timeout
            )
            actual = sha256(path)
            if actual != expected:
                message = f"{tool} {release.tag}: checksum mismatch for {asset}"
                raise RuntimeError(message)
            _extract_bundle(path, payload=payload, binary=binary)
            release_hashes[binary] = expected
        staged: dict[str, Path] = {payload_name(tool): payload}
        for binary in spec.assets:
            launcher = payload / binary / binary
            if not launcher.is_file() or not launcher.stat().st_mode & 0o111:
                message = f"{tool} {release.tag}: bundle launcher invalid: {launcher}"
                raise RuntimeError(message)
            wrapper = stage / binary
            wrapper.write_text(launcher_script(tool, binary), encoding="utf-8")
            wrapper.chmod(0o755)
            staged[binary] = wrapper
        receipt = InstallReceipt(
            repo=_repo(tool),
            tag=release.tag,
            platform=f"{platform_name}-{arch}",
            assets=tuple(
                InstalledAsset(
                    name=binary,
                    release_asset=asset_names[binary],
                    target=bin_dir / binary,
                    bundle=bin_dir / payload_name(tool) / binary,
                    release_sha256=release_hashes[binary],
                    tree_sha256=tree_sha256(payload / binary),
                )
                for binary in spec.assets
            ),
        )
        receipt_file = stage / receipt_name(tool)
        receipt_file.write_text(dumps(receipt), encoding="utf-8")
        staged[receipt_name(tool)] = receipt_file
        _atomic_replace(staged, bin_dir=bin_dir, stage=stage)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return receipt


def _extract_bundle(archive: Path, *, payload: Path, binary: str) -> None:
    """Extract one release bundle while rejecting cross-bundle archive paths."""
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            if not members:
                raise RuntimeError(f"empty release bundle: {archive.name}")
            for member in members:
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts or not path.parts:
                    raise RuntimeError(
                        f"unsafe path in release bundle {archive.name}: {member.name}"
                    )
                if path.parts[0] != binary:
                    raise RuntimeError(
                        f"unexpected path in release bundle {archive.name}: {member.name}"
                    )
            bundle.extractall(payload, members=members, filter="data")
    except (OSError, tarfile.TarError) as exc:
        raise RuntimeError(f"invalid release bundle {archive.name}: {exc}") from exc


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
