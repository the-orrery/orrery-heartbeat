import hashlib
import io
import json

import pytest

import orrery_heartbeat
from orrery_heartbeat import check_update, cli, env, mark_installed


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


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


def test_check_update_noop_in_ci(monkeypatch):
    monkeypatch.setenv("CI", "true")
    check_update("test", "the-orrery/test")


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
    checksum = hashlib.sha256(binary).hexdigest()
    metadata = json.dumps({"tag_name": "v1.2.3"}).encode()
    checksums = f"{checksum}  crux-darwin-arm64\n".encode()

    def fake_urlopen(request, **_kwargs):
        url = request.full_url
        if url.endswith("/releases/latest"):
            return _Response(metadata)
        if url.endswith("/SHA256SUMS"):
            return _Response(checksums)
        if url.endswith("/crux-darwin-arm64"):
            return _Response(binary)
        raise AssertionError(url)

    monkeypatch.setattr(cli, "_platform", lambda: ("darwin", "arm64"))
    monkeypatch.setattr(cli.urllib.request, "urlopen", fake_urlopen)
    installed = []
    monkeypatch.setattr(cli, "mark_installed", lambda *args: installed.append(args))

    cli.run(["--apply", "--bin-dir", str(tmp_path), "crux"])

    assert (tmp_path / "crux").read_bytes() == binary
    assert (tmp_path / "crux").stat().st_mode & 0o111
    assert installed == [("crux", "v1.2.3")]
    assert "1 repositories up to date" in capsys.readouterr().out


def test_checksum_failure_preserves_existing_binary(monkeypatch, tmp_path):
    existing = tmp_path / "crux"
    existing.write_bytes(b"old")
    metadata = json.dumps({"tag_name": "v1.2.3"}).encode()
    checksums = f"{'0' * 64}  crux-darwin-arm64\n".encode()

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
    payloads = {"docket-darwin-arm64": b"docket", "pm-darwin-arm64": b"pm"}
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
    assert (tmp_path / "docket").read_bytes() == b"docket"
    assert (tmp_path / "pm").read_bytes() == b"pm"


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


def test_mark_installed_records_release_tag(tmp_path, monkeypatch):
    monkeypatch.setattr("orrery_heartbeat._CACHE_DIR", tmp_path)
    mark_installed("crux", "v1.2.3")
    state = json.loads((tmp_path / "crux" / "state.json").read_text())
    assert state["installed_tag"] == "v1.2.3"
    assert state["latest_tag"] == "v1.2.3"
