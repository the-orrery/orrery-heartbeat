import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

import orrery_heartbeat
from orrery_heartbeat import cli, env
from orrery_heartbeat.receipt import load, receipt_path


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def _bundle(name: str, content: bytes) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        info = tarfile.TarInfo(f"{name}/{name}")
        info.mode = 0o755
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    return stream.getvalue()


def test_ssl_context_uses_bundled_roots_by_default(monkeypatch):
    calls = []
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    monkeypatch.setattr(orrery_heartbeat.certifi, "where", lambda: "/bundle/ca.pem")
    monkeypatch.setattr(
        orrery_heartbeat.ssl,
        "create_default_context",
        lambda **kwargs: calls.append(kwargs) or object(),
    )

    orrery_heartbeat._ssl_context()

    assert calls == [{"cafile": "/bundle/ca.pem"}]


def test_ssl_context_honors_operator_trust_store(monkeypatch):
    calls = []
    monkeypatch.setenv("SSL_CERT_FILE", "/operator/ca.pem")
    monkeypatch.setattr(
        orrery_heartbeat.ssl,
        "create_default_context",
        lambda **kwargs: calls.append(kwargs) or object(),
    )

    orrery_heartbeat._ssl_context()

    assert calls == [{}]


def test_load_env_missing_file(tmp_path):
    assert env.load_env(tmp_path / "nonexistent.toml") == {}


def test_load_env_exports_crux_binary_overrides(tmp_path):
    path = tmp_path / "env.toml"
    path.write_text(
        '[crux]\nmemex_bin = "/opt/bin/memex"\ndocket_bin = "/opt/bin/docket"\n'
    )
    assert env.load_env(path) == {
        "CRUX_MEMEX_BIN": "/opt/bin/memex",
        "CRUX_DOCKET_BIN": "/opt/bin/docket",
    }


def test_upgrade_help_has_no_network_side_effect(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        cli.urllib.request,
        "urlopen",
        lambda *args, **_kwargs: calls.append(args),
    )
    with pytest.raises(SystemExit) as exc_info:
        cli.run(["--help"])
    assert exc_info.value.code == 0
    assert calls == []
    assert "usage: orrery-upgrade" in capsys.readouterr().out


def test_upgrade_bare_command_prints_release_plan_without_network(
    monkeypatch, capsys, tmp_path
):
    calls = []
    monkeypatch.setattr(
        cli.urllib.request,
        "urlopen",
        lambda *args, **_kwargs: calls.append(args),
    )
    cli.run(["--bin-dir", str(tmp_path)])
    assert calls == []
    out = capsys.readouterr().out
    assert "crux: latest verified GitHub Release" in out
    assert "uv tool install" not in out
    assert "Run `orrery-upgrade --apply` to install." in out


def test_upgrade_selected_tool_installs_verified_asset(monkeypatch, tmp_path, capsys):
    binary = b"frozen-crux"
    bundle = _bundle("crux", binary)
    checksum = hashlib.sha256(bundle).hexdigest()
    metadata = json.dumps({"tag_name": "v1.2.3"}).encode()
    checksums = f"{checksum}  crux-darwin-arm64.tar.gz\n".encode()

    def fake_urlopen(request, **_kwargs):
        url = request.full_url
        if url.endswith("/releases/latest"):
            return _Response(metadata)
        if url.endswith("/SHA256SUMS"):
            return _Response(checksums)
        if url.endswith("/crux-darwin-arm64.tar.gz"):
            return _Response(bundle)
        raise AssertionError(url)

    monkeypatch.setattr(cli, "_platform", lambda: ("darwin", "arm64"))
    monkeypatch.setattr(cli.urllib.request, "urlopen", fake_urlopen)
    cli.run(["--apply", "--bin-dir", str(tmp_path), "crux"])

    assert (tmp_path / "crux").is_symlink()
    assert (tmp_path / "crux").resolve().read_bytes() == binary
    assert (tmp_path / "crux").stat().st_mode & 0o111
    receipt = load(receipt_path("crux", tmp_path))
    assert receipt.tag == "v1.2.3"
    assert receipt.assets[0].release_sha256 == checksum
    assert "1 repositories up to date" in capsys.readouterr().out


def test_checksum_failure_preserves_existing_binary(monkeypatch, tmp_path):
    existing = tmp_path / "crux"
    existing.write_bytes(b"old")
    metadata = json.dumps({"tag_name": "v1.2.3"}).encode()
    checksums = f"{'0' * 64}  crux-darwin-arm64.tar.gz\n".encode()

    def fake_urlopen(request, **_kwargs):
        url = request.full_url
        if url.endswith("/releases/latest"):
            return _Response(metadata)
        if url.endswith("/SHA256SUMS"):
            return _Response(checksums)
        return _Response(b"tampered")

    monkeypatch.setattr(cli, "_platform", lambda: ("darwin", "arm64"))
    monkeypatch.setattr(cli.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        cli._install_tool("crux", bin_dir=tmp_path, timeout=1)
    assert existing.read_bytes() == b"old"


def test_multi_asset_repo_installs_all_or_none(monkeypatch, tmp_path):
    payloads = {
        "docket-darwin-arm64.tar.gz": _bundle("docket", b"docket"),
        "pm-darwin-arm64.tar.gz": _bundle("pm", b"pm"),
    }
    checksum_text = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n"
        for name, data in payloads.items()
    ).encode()

    def fake_urlopen(request, **_kwargs):
        url = request.full_url
        if url.endswith("/releases/latest"):
            return _Response(json.dumps({"tag_name": "v9"}).encode())
        if url.endswith("/SHA256SUMS"):
            return _Response(checksum_text)
        return _Response(payloads[url.rsplit("/", 1)[-1]])

    monkeypatch.setattr(cli, "_platform", lambda: ("darwin", "arm64"))
    monkeypatch.setattr(cli.urllib.request, "urlopen", fake_urlopen)
    cli._install_tool("docket", bin_dir=tmp_path, timeout=1)
    assert (tmp_path / "docket").resolve().read_bytes() == b"docket"
    assert (tmp_path / "pm").resolve().read_bytes() == b"pm"


def test_upgrade_unknown_tool_exits_before_network(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli.urllib.request,
        "urlopen",
        lambda *args, **_kwargs: calls.append(args),
    )
    with pytest.raises(SystemExit) as exc_info:
        cli.run(["--apply", "nope"])
    assert exc_info.value.code == 2
    assert calls == []


def test_upgrade_pinned_tag_skips_latest_api(monkeypatch, tmp_path):
    bundle = _bundle("crux", b"frozen-crux")
    checksum = hashlib.sha256(bundle).hexdigest()
    checksums = f"{checksum}  crux-darwin-arm64.tar.gz\n".encode()
    urls = []

    def fake_urlopen(request, **_kwargs):
        urls.append(request.full_url)
        if request.full_url.endswith("/SHA256SUMS"):
            return _Response(checksums)
        return _Response(bundle)

    monkeypatch.setattr(cli, "_platform", lambda: ("darwin", "arm64"))
    monkeypatch.setattr(cli.urllib.request, "urlopen", fake_urlopen)
    cli.run(["--apply", "--bin-dir", str(tmp_path), "crux@v1.2.3"])

    assert not any(url.endswith("/releases/latest") for url in urls)
    assert all("/releases/download/v1.2.3/" in url for url in urls)
    assert load(receipt_path("crux", tmp_path)).tag == "v1.2.3"


def test_upgrade_rejects_non_version_tag_before_network(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli.urllib.request,
        "urlopen",
        lambda *args, **_kwargs: calls.append(args),
    )
    with pytest.raises(SystemExit) as exc_info:
        cli.run(["--apply", "crux@main"])
    assert exc_info.value.code == 2
    assert calls == []


def test_verify_detects_tampered_binary(monkeypatch, tmp_path, capsys):
    binary = b"frozen-crux"
    bundle = _bundle("crux", binary)
    checksum = hashlib.sha256(bundle).hexdigest()
    metadata = json.dumps({"tag_name": "v1.2.3"}).encode()
    checksums = f"{checksum}  crux-darwin-arm64.tar.gz\n".encode()

    def fake_urlopen(request, **_kwargs):
        if request.full_url.endswith("/releases/latest"):
            return _Response(metadata)
        if request.full_url.endswith("/SHA256SUMS"):
            return _Response(checksums)
        return _Response(bundle)

    monkeypatch.setattr(cli, "_platform", lambda: ("darwin", "arm64"))
    monkeypatch.setattr(cli.urllib.request, "urlopen", fake_urlopen)
    cli.run(["--apply", "--bin-dir", str(tmp_path), "crux"])
    (tmp_path / "crux").resolve().write_bytes(b"tampered")

    with pytest.raises(SystemExit) as exc_info:
        cli.run(["--verify", "--bin-dir", str(tmp_path), "crux"])
    assert exc_info.value.code == 1
    assert "checksum mismatch" in capsys.readouterr().err


def test_verify_accepts_multi_asset_receipt(monkeypatch, tmp_path, capsys):
    payloads = {
        "docket-darwin-arm64.tar.gz": _bundle("docket", b"docket"),
        "pm-darwin-arm64.tar.gz": _bundle("pm", b"pm"),
    }
    checksum_text = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n"
        for name, data in payloads.items()
    ).encode()

    def fake_urlopen(request, **_kwargs):
        if request.full_url.endswith("/releases/latest"):
            return _Response(json.dumps({"tag_name": "v9"}).encode())
        if request.full_url.endswith("/SHA256SUMS"):
            return _Response(checksum_text)
        return _Response(payloads[request.full_url.rsplit("/", 1)[-1]])

    monkeypatch.setattr(cli, "_platform", lambda: ("darwin", "arm64"))
    monkeypatch.setattr(cli.urllib.request, "urlopen", fake_urlopen)
    cli.run(["--apply", "--bin-dir", str(tmp_path), "docket"])
    cli.run(["--verify", "--bin-dir", str(tmp_path), "docket"])
    assert "docket: ✓ v9" in capsys.readouterr().out


def test_verify_rejects_receipt_from_another_pinned_tag(monkeypatch, tmp_path, capsys):
    bundle = _bundle("crux", b"frozen-crux")
    checksum = hashlib.sha256(bundle).hexdigest()
    checksums = f"{checksum}  crux-darwin-arm64.tar.gz\n".encode()

    def fake_urlopen(request, **_kwargs):
        if request.full_url.endswith("/SHA256SUMS"):
            return _Response(checksums)
        return _Response(bundle)

    monkeypatch.setattr(cli, "_platform", lambda: ("darwin", "arm64"))
    monkeypatch.setattr(cli.urllib.request, "urlopen", fake_urlopen)
    cli.run(["--apply", "--bin-dir", str(tmp_path), "crux@v1.2.3"])

    with pytest.raises(SystemExit) as exc_info:
        cli.run(["--verify", "--bin-dir", str(tmp_path), "crux@v1.2.2"])
    assert exc_info.value.code == 1
    assert "tag is v1.2.3, expected v1.2.2" in capsys.readouterr().err


def test_atomic_replace_rolls_back_binary_group(monkeypatch, tmp_path):
    stage = tmp_path / "stage"
    stage.mkdir()
    for name, content in {"docket": b"new-docket", "pm": b"new-pm"}.items():
        (stage / name).write_bytes(content)
        (tmp_path / name).write_bytes(b"old-" + name.encode())

    original_replace = Path.replace

    def fail_second_install(self, target):
        if self == stage / "pm" and Path(target) == tmp_path / "pm":
            raise OSError("simulated commit failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_second_install)
    with pytest.raises(OSError, match="simulated commit failure"):
        cli._atomic_replace(
            {"docket": stage / "docket", "pm": stage / "pm"},
            bin_dir=tmp_path,
            stage=stage,
        )

    assert (tmp_path / "docket").read_bytes() == b"old-docket"
    assert (tmp_path / "pm").read_bytes() == b"old-pm"
