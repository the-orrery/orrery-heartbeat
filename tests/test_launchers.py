import json
import os
import subprocess
from pathlib import Path

from orrery_heartbeat.launchers import launcher_script


def _executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_launcher_execs_payload_and_writes_opt_in_local_timing(tmp_path):
    payload = tmp_path / ".orrery-crux.payload" / "crux"
    payload.mkdir(parents=True)
    _executable(payload / "crux", '#!/bin/sh\nexit "${1:-0}"\n')
    launcher = tmp_path / "crux"
    _executable(launcher, launcher_script("crux", "crux"))
    log = tmp_path / "state" / "timing.jsonl"
    environment = os.environ | {
        "ORRERY_CLI_TIMING": "1",
        "ORRERY_CLI_TIMING_LOG": str(log),
    }

    completed = subprocess.run(
        [str(launcher), "7"], env=environment, capture_output=True, text=True
    )

    assert completed.returncode == 7
    event = json.loads(log.read_text(encoding="utf-8"))
    assert event["schema"] == 1
    assert event["tool"] == "crux"
    assert event["entrypoint"] == "crux"
    assert event["exit_code"] == 7
    assert event["duration_ms"] >= 0
    assert "argv" not in event
