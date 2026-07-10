"""Install receipts for verified Orrery release bundles."""

from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .launchers import launcher_script

SCHEMA_VERSION = 2
SHA256_HEX_LENGTH = 64


@dataclass(frozen=True)
class InstalledAsset:
    name: str
    release_asset: str
    target: Path
    bundle: Path
    release_sha256: str
    tree_sha256: str


@dataclass(frozen=True)
class InstallReceipt:
    repo: str
    tag: str
    platform: str
    assets: tuple[InstalledAsset, ...]


def receipt_name(tool: str) -> str:
    return f".orrery-{tool}.release.json"


def payload_name(tool: str) -> str:
    return f".orrery-{tool}.payload"


def receipt_path(tool: str, bin_dir: Path) -> Path:
    return bin_dir / receipt_name(tool)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_sha256(root: Path) -> str:
    """Hash bundle paths, types, modes, symlink targets, and file contents."""
    if not root.is_dir():
        raise RuntimeError(f"bundle missing: {root}")
    digest = hashlib.sha256()
    for path in sorted(
        root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()
    ):
        relative = path.relative_to(root).as_posix()
        mode = path.lstat().st_mode
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(f"{stat.S_IMODE(mode):04o}".encode())
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(b"link\0")
            digest.update(str(path.readlink()).encode())
        elif path.is_dir():
            digest.update(b"dir")
        elif path.is_file():
            digest.update(b"file\0")
            digest.update(sha256(path).encode())
        else:
            raise RuntimeError(f"unsupported bundle entry: {path}")
        digest.update(b"\n")
    return digest.hexdigest()


def dumps(receipt: InstallReceipt) -> str:
    payload = {
        "schema": SCHEMA_VERSION,
        "repo": receipt.repo,
        "tag": receipt.tag,
        "platform": receipt.platform,
        "assets": [
            {
                "name": asset.name,
                "release_asset": asset.release_asset,
                "target": str(asset.target),
                "bundle": str(asset.bundle),
                "release_sha256": asset.release_sha256,
                "tree_sha256": asset.tree_sha256,
            }
            for asset in receipt.assets
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def load(path: Path) -> InstallReceipt:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RuntimeError(f"receipt missing: {path}") from None
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"receipt unreadable: {path}: {exc}") from exc

    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA_VERSION:
        raise RuntimeError(f"unsupported receipt schema: {path}")
    try:
        repo = _string(payload, "repo")
        tag = _string(payload, "tag")
        platform_name = _string(payload, "platform")
        raw_assets = payload["assets"]
        if not isinstance(raw_assets, list) or not raw_assets:
            raise ValueError("assets must be a non-empty list")
        assets = tuple(_asset(item) for item in raw_assets)
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid receipt: {path}: {exc}") from exc
    return InstallReceipt(repo, tag, platform_name, assets)


def verify(receipt: InstallReceipt, *, tool: str, bin_dir: Path) -> list[str]:
    errors: list[str] = []
    expected_repo = f"the-orrery/{tool}"
    if receipt.repo != expected_repo:
        errors.append(f"repo is {receipt.repo}, expected {expected_repo}")

    seen: set[str] = set()
    root = bin_dir.resolve()
    expected_payload = root / payload_name(tool)
    for asset in receipt.assets:
        if asset.name in seen:
            errors.append(f"duplicate asset: {asset.name}")
            continue
        seen.add(asset.name)
        errors.extend(
            _verify_asset(asset, tool=tool, root=root, payload=expected_payload)
        )
    return errors


def _verify_asset(
    asset: InstalledAsset, *, tool: str, root: Path, payload: Path
) -> list[str]:
    errors: list[str] = []
    expected_target = root / asset.name
    expected_bundle = payload / asset.name
    if asset.target != expected_target:
        return [f"{asset.name}: target is {asset.target}, expected {expected_target}"]
    if asset.bundle != expected_bundle:
        return [f"{asset.name}: bundle is {asset.bundle}, expected {expected_bundle}"]

    expected_link = Path(payload_name(tool)) / asset.name / asset.name
    if asset.target.is_symlink():
        if (actual_link := asset.target.readlink()) != expected_link:
            errors.append(
                f"{asset.name}: launcher points to {actual_link}, expected {expected_link}"
            )
    elif not asset.target.is_file():
        errors.append(f"{asset.name}: launcher missing: {asset.target}")
    elif asset.target.read_text(encoding="utf-8") != launcher_script(tool, asset.name):
        errors.append(f"{asset.name}: launcher wrapper content mismatch")
    elif not asset.target.stat().st_mode & 0o111:
        errors.append(f"{asset.name}: launcher wrapper is not executable")

    launcher = asset.bundle / asset.name
    if not launcher.is_file():
        errors.append(f"{asset.name}: bundle launcher missing: {launcher}")
    elif not launcher.stat().st_mode & 0o111:
        errors.append(f"{asset.name}: bundle launcher is not executable: {launcher}")
    if not _valid_sha256(asset.release_sha256):
        errors.append(f"{asset.name}: invalid release SHA256 in receipt")
    errors.extend(_verify_bundle(asset))
    return errors


def _verify_bundle(asset: InstalledAsset) -> list[str]:
    try:
        actual = tree_sha256(asset.bundle)
    except RuntimeError as exc:
        return [str(exc)]
    if actual != asset.tree_sha256:
        return [
            f"{asset.name}: bundle checksum mismatch "
            f"({actual}, expected {asset.tree_sha256})"
        ]
    return []


def installed_tag(tool: str, bin_dir: Path) -> str:
    try:
        return load(receipt_path(tool, bin_dir)).tag
    except RuntimeError:
        return ""


def _valid_sha256(value: str) -> bool:
    return len(value) == SHA256_HEX_LENGTH and all(
        character in "0123456789abcdef" for character in value
    )


def _string(payload: dict[str, Any], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _asset(payload: Any) -> InstalledAsset:
    if not isinstance(payload, dict):
        raise TypeError("asset must be an object")
    return InstalledAsset(
        name=_string(payload, "name"),
        release_asset=_string(payload, "release_asset"),
        target=Path(_string(payload, "target")),
        bundle=Path(_string(payload, "bundle")),
        release_sha256=_string(payload, "release_sha256"),
        tree_sha256=_string(payload, "tree_sha256"),
    )
