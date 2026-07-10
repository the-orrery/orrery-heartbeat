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
