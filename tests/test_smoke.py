from orrery_heartbeat import check_update


def test_check_update_noop_in_ci(monkeypatch):
    """check_update does nothing in CI (env CI=true)."""
    monkeypatch.setenv("CI", "true")
    check_update("test", "the-orrery/test")


def test_load_env_missing_file(tmp_path):
    from orrery_heartbeat.env import load_env

    result = load_env(tmp_path / "nonexistent.toml")
    assert result == {}
