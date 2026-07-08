import json
import subprocess

import pytest

from orrery_heartbeat import check_update, cli, env, mark_installed


def test_check_update_noop_in_ci(monkeypatch):
    """check_update does nothing in CI (env CI=true)."""
    monkeypatch.setenv("CI", "true")
    check_update("test", "the-orrery/test")


def test_load_env_missing_file(tmp_path):
    result = env.load_env(tmp_path / "nonexistent.toml")
    assert result == {}


def test_upgrade_help_has_no_install_side_effect(monkeypatch, capsys):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args[0], 0, "", "")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc_info:
        cli.run(["--help"])

    assert exc_info.value.code == 0
    assert calls == []
    assert "usage: orrery-upgrade" in capsys.readouterr().out


def test_upgrade_bare_command_prints_plan_without_install(monkeypatch, capsys):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args[0], 0, "", "")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    cli.run([])

    assert calls == []
    out = capsys.readouterr().out
    assert "uv tool install --from" in out
    assert "Run `orrery-upgrade --apply` to install." in out


def test_upgrade_dry_run_has_no_install_side_effect(monkeypatch, capsys):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args[0], 0, "", "")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    cli.run(["--dry-run", "crux"])

    assert calls == []
    out = capsys.readouterr().out
    assert _crux_install_command_text() in out


def test_upgrade_selected_tool_requires_apply(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        cli.subprocess, "run", lambda *args, **_kwargs: calls.append(args)
    )

    cli.run(["crux"])

    assert calls == []
    assert _crux_install_command_text() in capsys.readouterr().out


def test_upgrade_apply_selected_tool_installs_only_that_tool(monkeypatch, capsys):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    monkeypatch.setattr(cli, "_fetch_latest_sha", lambda _repo: "abc123")
    installed = []
    monkeypatch.setattr(
        cli, "mark_installed", lambda tool, sha: installed.append((tool, sha))
    )

    cli.run(["--apply", "crux"])

    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command == [
        "uv",
        "tool",
        "install",
        "--from",
        "git+ssh://git@github.com/the-orrery/crux.git",
        "crux",
        "--force",
        "--quiet",
    ]
    assert kwargs["timeout"] == 120.0
    assert installed == [("crux", "abc123")]
    assert "1 tools up to date" in capsys.readouterr().out


def test_upgrade_unknown_tool_exits_before_install(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli.subprocess, "run", lambda *args, **_kwargs: calls.append(args)
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.run(["--apply", "nope"])

    assert exc_info.value.code == 2
    assert calls == []


def test_mark_installed_records_latest_sha(tmp_path, monkeypatch):
    monkeypatch.setattr("orrery_heartbeat._CACHE_DIR", tmp_path)

    mark_installed("crux", "abc123")

    state = json.loads((tmp_path / "crux" / "state.json").read_text())
    assert state["installed_sha"] == "abc123"
    assert state["latest_sha"] == "abc123"


def _crux_install_command_text():
    return (
        "uv tool install --from "
        "git+ssh://git@github.com/the-orrery/crux.git crux --force"
    )
