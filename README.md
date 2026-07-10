# orrery-heartbeat

Lightweight update-check for [the-orrery](https://github.com/the-orrery) CLI tools.

## Usage

Add `orrery-heartbeat` as a dependency, then call at your CLI entry point:

```python
from orrery_heartbeat import check_update

def main():
    check_update("my-tool", "the-orrery/my-tool")
    # ... rest of CLI
```

On each invocation (throttled to once per 6 hours), it checks the latest stable
GitHub Release tag against the release receipt written by `orrery-upgrade`. If an
update is available, it prints one line to stderr. It is silent in CI, non-TTY,
or on network failure.

## orrery-upgrade

Plans or installs/upgrades the nine executable Orrery repositories from verified
GitHub Release assets. `gnomon` is a library and is intentionally excluded. The
bare command is read-only and prints the install plan:

```
orrery-upgrade
```

Apply the upgrade explicitly:

```
orrery-upgrade --apply
```

Useful read-only modes:

```
orrery-upgrade --help
orrery-upgrade --list
orrery-upgrade --dry-run crux rhizome
```

Upgrade selected tools by naming them:

```
orrery-upgrade --apply crux rhizome
```

The installer selects macOS arm64 or Linux x86_64 assets, verifies each asset
against `SHA256SUMS`, downloads every asset for a repository before replacing
anything, and installs atomically into `$ORRERY_BIN_DIR` or `~/.local/bin`.
Use `--bin-dir` for an explicit destination. Runtime installation does not need
Python, `uv`, or a local source checkout.

## Release binaries

`./scripts/build-release.sh` builds `orrery-upgrade` and `orrery-env` for the
current platform. Pull requests build and smoke-test both supported platforms;
a matching `v<project.version>` tag publishes immutable GitHub Release assets
and `SHA256SUMS`.
