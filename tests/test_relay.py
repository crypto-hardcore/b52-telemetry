from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from b52_telemetry.relay import (
    PermanentDeliveryError,
    RelayConfiguration,
    RelayState,
    RelayStateInvalid,
    RetryableDeliveryError,
    TelemetryRelay,
    initialize_relay_state,
    read_relay_state,
    reset_relay_state,
    rotate_relay_generation,
    write_relay_state,
)
from tests.test_transport import body, payload, token


def configuration(tmp_path: Path, generation: int = 1) -> RelayConfiguration:
    return RelayConfiguration(
        fleet_identity="B52-001",
        authorization_generation=generation,
        telemetry_path=tmp_path / "engine" / "telemetry.latest.json",
        state_path=tmp_path / "relay" / "state.json",
        receiver_url="https://telemetry.example.com/api/telemetry/instances/B52-001/latest",
        credential_path=tmp_path / "credentials" / "producer.token",
    )


def write_snapshot(path: Path, snapshot: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(snapshot)
    os.replace(temporary, path)


def test_relay_state_contains_only_approved_fields(tmp_path: Path) -> None:
    state_path = tmp_path / "relay" / "state.json"
    initialize_relay_state(
        state_path,
        fleet_identity="B52-001",
        authorization_generation=1,
    )
    assert set(json.loads(state_path.read_text())) == {
        "version",
        "fleet_identity",
        "authorization_generation",
        "last_assigned_sequence",
    }


def test_relay_retries_same_in_memory_bytes_and_sequence_after_network_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = configuration(tmp_path)
    initialize_relay_state(
        config.state_path,
        fleet_identity=config.fleet_identity,
        authorization_generation=1,
    )
    snapshot = body()
    write_snapshot(config.telemetry_path, snapshot)
    calls: list[tuple[int, bytes]] = []

    def sender(_url: str, _token: str, sequence: int, sent: bytes) -> None:
        calls.append((sequence, sent))
        if len(calls) == 1:
            raise RetryableDeliveryError("network interruption")

    monkeypatch.setattr("b52_telemetry.relay.RETRY_DELAYS_SECONDS", (0.0,))
    relay = TelemetryRelay(config, token("A"), sender=sender)

    assert relay.deliver_current_if_changed()
    assert calls == [(1, snapshot), (1, snapshot)]
    assert read_relay_state(config.state_path).last_assigned_sequence == 1
    assert not relay.deliver_current_if_changed()


def test_relay_restart_assigns_new_sequence_without_durable_pending_payload(
    tmp_path: Path,
) -> None:
    config = configuration(tmp_path)
    initialize_relay_state(
        config.state_path,
        fleet_identity=config.fleet_identity,
        authorization_generation=1,
    )
    snapshot = body()
    write_snapshot(config.telemetry_path, snapshot)

    def interrupted(_url: str, _token: str, _sequence: int, _body: bytes) -> None:
        raise PermanentDeliveryError("simulated process-ending response")

    first_process = TelemetryRelay(config, token("A"), sender=interrupted)
    with pytest.raises(PermanentDeliveryError):
        first_process.deliver_current_if_changed()
    assert read_relay_state(config.state_path).last_assigned_sequence == 1

    calls: list[tuple[int, bytes]] = []

    def recovered(_url: str, _token: str, sequence: int, sent: bytes) -> None:
        calls.append((sequence, sent))

    restarted = TelemetryRelay(config, token("A"), sender=recovered)
    assert restarted.deliver_current_if_changed()
    assert calls == [(2, snapshot)]
    assert set(json.loads(config.state_path.read_text())) == {
        "version",
        "fleet_identity",
        "authorization_generation",
        "last_assigned_sequence",
    }


def test_relay_reopens_atomic_snapshot_path_and_coalesces_intermediate_updates(
    tmp_path: Path,
) -> None:
    config = configuration(tmp_path)
    initialize_relay_state(
        config.state_path,
        fleet_identity=config.fleet_identity,
        authorization_generation=1,
    )
    first = body(payload("2026-10-29T00:00:01+00:00"))
    final = body(payload("2026-10-29T00:00:03+00:00"))
    write_snapshot(config.telemetry_path, first)
    calls: list[bytes] = []
    relay = TelemetryRelay(
        config,
        token("A"),
        sender=lambda _url, _token, _sequence, sent: calls.append(sent),
    )
    relay.deliver_current_if_changed()

    write_snapshot(
        config.telemetry_path,
        body(payload("2026-10-29T00:00:02+00:00")),
    )
    write_snapshot(config.telemetry_path, final)
    relay.deliver_current_if_changed()

    assert calls == [first, final]
    assert read_relay_state(config.state_path).last_assigned_sequence == 2


def test_relay_generation_rotation_preserves_sequence_and_reset_clears_it(
    tmp_path: Path,
) -> None:
    config = configuration(tmp_path)
    initialize_relay_state(
        config.state_path,
        fleet_identity="B52-001",
        authorization_generation=1,
    )
    write_snapshot(config.telemetry_path, body())
    TelemetryRelay(
        config,
        token("A"),
        sender=lambda _url, _token, _sequence, _body: None,
    ).deliver_current_if_changed()

    rotate_relay_generation(
        config.state_path,
        fleet_identity="B52-001",
        previous_generation=1,
        authorization_generation=2,
    )
    rotated = read_relay_state(config.state_path)
    assert rotated.authorization_generation == 2
    assert rotated.last_assigned_sequence == 1

    reset_relay_state(
        config.state_path,
        fleet_identity="B52-001",
        previous_generation=2,
        authorization_generation=3,
    )
    reset = read_relay_state(config.state_path)
    assert reset.authorization_generation == 3
    assert reset.last_assigned_sequence == 0


def test_corrupt_or_generation_mismatched_relay_state_fails_closed(
    tmp_path: Path,
) -> None:
    config = configuration(tmp_path, generation=2)
    config.state_path.parent.mkdir(parents=True)
    config.state_path.write_text("{}", encoding="utf-8")
    with pytest.raises(RelayStateInvalid):
        TelemetryRelay(config, token("A"), sender=lambda *_arguments: None)

    config.state_path.unlink()
    initialize_relay_state(
        config.state_path,
        fleet_identity="B52-001",
        authorization_generation=1,
    )
    with pytest.raises(RelayStateInvalid):
        TelemetryRelay(config, token("A"), sender=lambda *_arguments: None)


@pytest.mark.parametrize(
    ("replacement_identity", "replacement_generation"),
    [("B52-002", 1), ("B52-001", 2)],
)
def test_relay_revalidates_replaced_state_between_deliveries(
    tmp_path: Path,
    replacement_identity: str,
    replacement_generation: int,
) -> None:
    config = configuration(tmp_path)
    initialize_relay_state(
        config.state_path,
        fleet_identity=config.fleet_identity,
        authorization_generation=config.authorization_generation,
    )
    write_snapshot(config.telemetry_path, body())
    calls: list[int] = []
    relay = TelemetryRelay(
        config,
        token("A"),
        sender=lambda _url, _token, sequence, _body: calls.append(sequence),
    )
    assert relay.deliver_current_if_changed()

    write_relay_state(
        config.state_path,
        RelayState(
            version=1,
            fleet_identity=replacement_identity,
            authorization_generation=replacement_generation,
            last_assigned_sequence=1,
        ),
    )
    write_snapshot(
        config.telemetry_path,
        body(payload("2026-10-29T00:00:01+00:00")),
    )

    with pytest.raises(RelayStateInvalid):
        relay.deliver_current_if_changed()
    assert calls == [1]
