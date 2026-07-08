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

On each invocation (throttled to once per 6 hours), checks GitHub for new commits on `main`. If an update is available, prints a one-line hint to stderr. Silent in CI, non-TTY, or on network failure.

## orrery-upgrade

Plans or installs/upgrades all orrery tools from GitHub main. The bare command
is read-only and prints the install plan:

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
