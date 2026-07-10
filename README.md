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

Useful read-only modes:

```
orrery-upgrade --help
orrery-upgrade --dry-run crux rhizome
orrery-upgrade --verify crux rhizome
```

Upgrade selected tools by naming them:

```
orrery-upgrade --apply crux rhizome
```

Pin an exact release for a reproducible install or rollback:

```
orrery-upgrade --apply crux@v0.1.1
```

The installer selects macOS arm64 or Linux x86_64 assets, verifies each asset
against `SHA256SUMS`, downloads every asset for a repository before replacing
anything, and commits the binaries and their repository receipt as one atomic
group. `--verify` is offline: it reads that receipt and checks the asset set,
platform, target, executable bit, and SHA-256 digest.

The default destination is `$ORRERY_BIN_DIR` or `~/.local/bin`; use `--bin-dir`
for an explicit destination. Runtime installation and verification do not need
Python, `uv`, or a local source checkout.

## Release binaries

`./scripts/build-release.sh` builds `orrery-upgrade` and `orrery-env` for the
current platform. Pull requests build and smoke-test both supported platforms;
a matching `v<project.version>` tag publishes immutable GitHub Release assets
and `SHA256SUMS`.
