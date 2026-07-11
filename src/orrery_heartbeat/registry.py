"""Release repository and platform contracts for managed CLI tools."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSpec:
    """Describe one release repository without inferring policy from its owner."""

    repo: str
    assets: tuple[str, ...]
    platforms: frozenset[str]
    access: str = "public"
    default: bool = True


PUBLIC_PLATFORMS = frozenset({"darwin-arm64", "linux-x86_64"})

TOOL_SPECS: dict[str, ToolSpec] = {
    "almagest": ToolSpec("the-orrery/almagest", ("almagest",), PUBLIC_PLATFORMS),
    "crux": ToolSpec("the-orrery/crux", ("crux",), PUBLIC_PLATFORMS),
    "docket": ToolSpec("the-orrery/docket", ("docket", "pm"), PUBLIC_PLATFORMS),
    "memex": ToolSpec("the-orrery/memex", ("memex", "memex-sync"), PUBLIC_PLATFORMS),
    "orrery-heartbeat": ToolSpec(
        "the-orrery/orrery-heartbeat",
        ("orrery-upgrade", "orrery-env"),
        PUBLIC_PLATFORMS,
    ),
    "pharos": ToolSpec("the-orrery/pharos", ("pharos",), PUBLIC_PLATFORMS),
    "registrar": ToolSpec("the-orrery/registrar", ("registrar",), PUBLIC_PLATFORMS),
    "rhizome": ToolSpec("the-orrery/rhizome", ("rhizome",), PUBLIC_PLATFORMS),
    "seed": ToolSpec("the-orrery/seed", ("seed",), PUBLIC_PLATFORMS),
    # Personal authenticated extensions are explicit-only. They must never enter
    # the public fleet default or its cross-repository release E2E.
    "hostdiag": ToolSpec(
        "Eridanus117/hostdiag",
        ("hostdiag",),
        frozenset({"darwin-arm64"}),
        access="gh",
        default=False,
    ),
}

TOOLS = tuple(TOOL_SPECS)
DEFAULT_TOOLS = tuple(name for name, spec in TOOL_SPECS.items() if spec.default)
