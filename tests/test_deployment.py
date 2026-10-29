from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
