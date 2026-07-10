# orrery-heartbeat

Verified release installer for [the-orrery](https://github.com/the-orrery) CLI tools.

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

## Local CLI timing

Every installed entrypoint supports opt-in, local-only duration logging. Set
`ORRERY_CLI_TIMING=1` in a shell or before one command:

```bash
ORRERY_CLI_TIMING=1 crux recall "example"
ORRERY_CLI_TIMING=1 docket show OPS-9
```

Events are appended as JSON Lines to
`$XDG_STATE_HOME/orrery/cli-timing.jsonl` (or
`$HOME/.local/state/orrery/cli-timing.jsonl` when `XDG_STATE_HOME` is unset,
or the path set in `ORRERY_CLI_TIMING_LOG`). Each event contains only the tool, entrypoint,
start timestamp, duration in milliseconds, and exit code. Arguments, working
directory, command output, and environment values are never recorded or sent
anywhere. Logs rotate at 5 MiB into a single `.1` file.

Useful read-only modes:

```
orrery-upgrade --help
orrery-upgrade --dry-run crux rhizome
orrery-upgrade --verify crux@v0.1.3 rhizome@v0.1.3
```

Upgrade selected tools by naming them:

```
orrery-upgrade --apply crux rhizome
```

Pin an exact release for a reproducible install or rollback:

```
orrery-upgrade --apply crux@v0.1.1
```

The installer selects macOS arm64 or Linux x86_64 onedir archives, verifies each
archive against `SHA256SUMS`, and extracts it once into a persistent bundle.
It downloads every archive for a repository before replacing anything, then
commits the bundles, launcher symlinks, and repository receipt as one atomic
group. `--verify` is offline: it checks the asset set, platform, launcher,
release checksum provenance, and a recursive bundle-tree digest.

The default destination is `$ORRERY_BIN_DIR` or `~/.local/bin`; use `--bin-dir`
for an explicit destination. Runtime installation and verification do not need
Python, `uv`, or a local source checkout.

## Release binaries

`./scripts/build-release.sh` builds persistent `orrery-upgrade` and `orrery-env`
bundles for the current platform. Pull requests extract and smoke-test both
supported platforms; a matching `v<project.version>` tag publishes immutable
GitHub Release archives and `SHA256SUMS`.
