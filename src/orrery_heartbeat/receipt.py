"""Install receipts for verified Orrery release binaries."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class InstalledAsset:
    name: str
    release_asset: str
    target: Path
    sha256: str


@dataclass(frozen=True)
class InstallReceipt:
    repo: str
    tag: str
    platform: str
    assets: tuple[InstalledAsset, ...]


def receipt_name(tool: str) -> str:
    return f".orrery-{tool}.release.json"


def receipt_path(tool: str, bin_dir: Path) -> Path:
    return bin_dir / receipt_name(tool)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
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
                "sha256": asset.sha256,
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
    for asset in receipt.assets:
        if asset.name in seen:
            errors.append(f"duplicate asset: {asset.name}")
            continue
        seen.add(asset.name)
        expected_target = root / asset.name
        if asset.target != expected_target:
            errors.append(
                f"{asset.name}: target is {asset.target}, expected {expected_target}"
            )
            continue
        if not asset.target.is_file():
            errors.append(f"{asset.name}: binary missing: {asset.target}")
            continue
        if not asset.target.stat().st_mode & 0o111:
            errors.append(f"{asset.name}: binary is not executable: {asset.target}")
        actual = sha256(asset.target)
        if actual != asset.sha256:
            errors.append(
                f"{asset.name}: checksum mismatch ({actual}, expected {asset.sha256})"
            )
    return errors


def installed_tag(tool: str, bin_dir: Path) -> str:
    try:
        return load(receipt_path(tool, bin_dir)).tag
    except RuntimeError:
        return ""


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
        sha256=_string(payload, "sha256"),
    )
