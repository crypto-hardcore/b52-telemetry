from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_receiver_unit_enforces_private_single_process_architecture() -> None:
    unit = (ROOT / "deploy/systemd/b52-telemetry.service").read_text()
    assert "User=b52-telemetry" in unit
    assert "Group=b52-telemetry" in unit
    assert "UMask=0077" in unit
    assert "StateDirectory=b52-telemetry" in unit
    assert "StateDirectoryMode=0700" in unit
    assert "EnvironmentFile=/etc/b52-telemetry/application.env" in unit
    assert "ExecStart=/opt/b52-telemetry/venv/bin/b52-telemetry" in unit
    assert "Restart=on-failure" in unit
    assert "TimeoutStopSec=30" in unit
    assert "ProtectSystem=strict" in unit
    assert "ReadOnlyPaths=/opt/b52-telemetry" in unit
    assert "ReadWritePaths=/var/lib/b52-telemetry" in unit
    assert "NoNewPrivileges=yes" in unit
    assert "CapabilityBoundingSet=" in unit
    assert "--host" not in unit
    assert "--port" not in unit
    assert "--workers" not in unit
    assert "uvicorn" not in unit
    assert "/bin/sh" not in unit
    assert "b52-telemetry-relay" not in unit


def test_receiver_operations_preserve_configuration_and_state_ownership() -> None:
    operations = (ROOT / "deploy/TRANSPORT_OPERATIONS.md").read_text()
    assert "/etc/b52-telemetry/application.env" in operations
    assert "`root:root` with mode `0600`" in operations
    assert "`b52-telemetry:b52-telemetry` with mode `0700`" in operations
    admin = "/opt/b52-telemetry/venv/bin/b52-telemetry-admin"
    assert f"{admin} receiver-baseline" in operations
    assert f"{admin} receiver-generation" in operations
    assert f"{admin} receiver-reset" in operations
    assert operations.count("sudo -u b52-telemetry") == 3


def test_receiver_unit_verifies_in_disposable_installed_layout(
    tmp_path: Path,
) -> None:
    analyzer = shutil.which("systemd-analyze")
    if analyzer is None:
        pytest.skip("systemd-analyze is unavailable")

    root = tmp_path / "root"
    unit_directory = root / "etc/systemd/system"
    executable = root / "opt/b52-telemetry/venv/bin/b52-telemetry"
    system_units = root / "usr/lib/systemd/system"
    unit_directory.mkdir(parents=True)
    executable.parent.mkdir(parents=True)
    system_units.mkdir(parents=True)

    shutil.copyfile(
        ROOT / "deploy/systemd/b52-telemetry.service",
        unit_directory / "b52-telemetry.service",
    )
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    for target in ("sysinit.target", "network-online.target", "multi-user.target"):
        (system_units / target).write_text(f"[Unit]\nDescription={target}\n")

    result = subprocess.run(
        [
            analyzer,
            "verify",
            f"--root={root}",
            "/etc/systemd/system/b52-telemetry.service",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_relay_unit_requires_apparmor_and_systemd_credentials() -> None:
    unit = (ROOT / "deploy/systemd/b52-telemetry-relay@.service").read_text()
    assert "User=b52" in unit
    assert "Group=b52" in unit
    assert "AppArmorProfile=b52-relay-%i" in unit
    assert "LoadCredential=producer.token:" in unit
    assert "RestartPreventExitStatus=78" in unit
    assert "ReadOnlyPaths=/var/lib/b52/%i/data/telemetry.latest.json" in unit
    assert "ReadWritePaths=/var/lib/b52-relay/%i" in unit
    assert "NoNewPrivileges=yes" in unit
    assert "CapabilityBoundingSet=" in unit
    assert "b52@.service" not in unit


def test_six_profiles_grant_only_their_own_snapshot_and_state() -> None:
    policy = (ROOT / "deploy/apparmor/b52-telemetry-relays").read_text()
    for index in range(1, 7):
        identity = f"B52-{index:03d}"
        assert f"profile b52-relay-{identity} " in policy
        assert f"/var/lib/b52/{identity}/data/telemetry.latest.json r," in policy
        assert f"/var/lib/b52-relay/{identity}/state.json" in policy
        assert (
            f"/run/credentials/b52-telemetry-relay@{identity}.service/producer.token r,"
            in policy
        )
    assert "signal (receive)," in policy
    assert "deny signal (send)," in policy
    assert "deny ptrace," in policy
    assert "b52.sqlite3" not in policy
    assert "control.sock" not in policy


def test_caddy_and_relay_examples_enforce_contract_boundaries() -> None:
    caddy = (ROOT / "deploy/Caddyfile").read_text()
    relay_environment = (ROOT / "deploy/relay.env.example").read_text()
    assert "max_size 1048576" in caddy
    assert "reverse_proxy 127.0.0.1:8000" in caddy
    assert "https://" in relay_environment
    assert "producer.token" not in relay_environment
