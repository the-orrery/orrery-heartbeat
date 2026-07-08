"""orrery-env: read ~/.config/orrery/env.toml → shell exports or JSON."""

from __future__ import annotations

import json
import os
import sys
import tomllib
from pathlib import Path

_ENV_FILE = Path(
    os.environ.get("ORRERY_ENV_FILE", "~/.config/orrery/env.toml")
).expanduser()

_ENV_PREFIX_MAP = {
    "core": {
        "docket_root": "DOCKET_ROOT",
        "docket_id_prefix": "DOCKET_ID_PREFIX",
        "workspace_tier": "WORKSPACE_TIER",
    },
    "kb": {
        "workspace_root": "KB_WORKSPACE_ROOT",
        "sources": "KB_SOURCES",
        "search_embedding_url": "KB_SEARCH_EMBEDDING_URL",
        "search_qdrant_url": "KB_SEARCH_QDRANT_URL",
        "search_ca_bundle": "KB_SEARCH_CA_BUNDLE",
    },
    "crux": {
        "tools_root": "CRUX_TOOLS_ROOT",
        "memex_project": "CRUX_MEMEX_PROJECT",
    },
    "rhizome": {
        "asset_prefixes": "RHIZOME_ASSET_PREFIXES",
        "code_roots": "RHIZOME_CODE_ROOTS",
    },
}


def load_env(path: Path | None = None) -> dict[str, str]:
    """Parse env.toml and return {ENV_VAR_NAME: expanded_value}."""
    p = path or _ENV_FILE
    if not p.exists():
        return {}
    with open(p, "rb") as f:
        data = tomllib.load(f)

    result: dict[str, str] = {}
    for section, mapping in _ENV_PREFIX_MAP.items():
        section_data = data.get(section, {})
        for key, env_name in mapping.items():
            if key in section_data:
                value = str(section_data[key])
                result[env_name] = (
                    str(Path(value).expanduser()) if value.startswith("~") else value
                )
    return result


def run() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="orrery-env",
        description="Export orrery env from ~/.config/orrery/env.toml",
    )
    parser.add_argument("--json", action="store_true", help="output as JSON object")
    parser.add_argument(
        "--claude",
        action="store_true",
        help="output as Claude profile env template fragment",
    )
    parser.add_argument("--file", default=None, help="override env.toml path")
    args = parser.parse_args()

    path = Path(args.file).expanduser() if args.file else None
    env = load_env(path)

    if not env:
        print(f"# orrery-env: no config found at {path or _ENV_FILE}", file=sys.stderr)
        raise SystemExit(1)

    if args.json:
        print(json.dumps(env, indent=2))
    elif args.claude:
        for name, value in sorted(env.items()):
            print(f'    "{name}": "{value}",')
    else:
        for name, value in sorted(env.items()):
            print(f"export {name}={_shell_quote(value)}")


def _shell_quote(value: str) -> str:
    if all(c.isalnum() or c in "/-_.:~" for c in value):
        return value
    return f"'{value}'"
