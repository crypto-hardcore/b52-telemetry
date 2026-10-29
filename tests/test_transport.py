from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from b52_telemetry.app import create_app
from b52_telemetry.authorization import deny_telemetry_access
from b52_telemetry.persistence import (
    CONTROL_XATTR,
    SNAPSHOT_XATTR,
    TransportCommitFailed,
    accept_snapshot,
    establish_baseline,
    read_accepted_snapshot,
    reset_ordering_baseline,
    update_current_authorization_generation,
)
from b52_telemetry.source_registry import (
    B52InstanceId,
    ProducerAuthorization,
    TelemetrySourceRegistration,
    TelemetrySourceRegistry,
)


def token(character: str) -> str:
    return "b52r_v1_" + character * 43


def payload(generated_at: str = "2026-10-29T00:00:00+00:00") -> dict[str, object]:
    return {
        "schema_version": 10,
        "instance": "deadbeef00112233deadbeef00112233",
        "environment": "testnet",
        "position_sizing_leverage": 3,
        "generated_at": generated_at,
        "phase": "AWAITING_OPERATOR",
        "system": {},
        "market": None,
        "mission": None,
        "future_b52_field": {"preserved": True},
    }


def body(value: dict[str, object] | None = None) -> bytes:
    return json.dumps(
        payload() if value is None else value,
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")


def registration(
    path: Path,
    credential: str,
    *,
    generation: int = 1,
    enabled: bool = True,
) -> TelemetrySourceRegistration:
    return TelemetrySourceRegistration(
        path=path,
        producer=ProducerAuthorization(
            enabled=enabled,
            authorization_generation=generation,
            credential_sha256=sha256(credential.encode()).hexdigest(),
        ),
    )


def registry_for(
    path: Path,
    credential: str,
    *,
    generation: int = 1,
    enabled: bool = True,
) -> TelemetrySourceRegistry:
    return TelemetrySourceRegistry(
        {
            B52InstanceId("B52-001"): registration(
                path,
                credential,
                generation=generation,
                enabled=enabled,
            )
        }
    )


def client_for(registry: TelemetrySourceRegistry) -> TestClient:
    return TestClient(
        create_app(registry, telemetry_authorizer=deny_telemetry_access),
        base_url="https://testserver",
    )


def headers(credential: str, sequence: str | int) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {credential}",
        "Content-Type": "application/json",
        "X-B52-Transport-Sequence": str(sequence),
    }


def test_ingest_preserves_exact_canonical_bytes_and_unknown_fields(
    tmp_path: Path,
) -> None:
    path = tmp_path / "B52-001" / "telemetry.latest.json"
    credential = token("A")
    establish_baseline(path, fleet_identity="B52-001", authorization_generation=1)
    client = client_for(registry_for(path, credential))
    exact_body = body()

    response = client.put(
        "/api/telemetry/instances/B52-001/latest",
        content=exact_body,
        headers=headers(credential, 1),
    )

    assert response.status_code == 204
    assert response.headers["x-b52-transport-result"] == "accepted"
    assert path.read_bytes() == exact_body
    assert client.get("/api/public/instances/B52-001/snapshot").status_code == 200


def test_ingest_requires_https(tmp_path: Path) -> None:
    path = tmp_path / "B52-001" / "telemetry.latest.json"
    credential = token("A")
    establish_baseline(path, fleet_identity="B52-001", authorization_generation=1)
    client = TestClient(create_app(registry_for(path, credential)))
    response = client.put(
        "/api/telemetry/instances/B52-001/latest",
        content=body(),
        headers=headers(credential, 1),
    )
    assert response.status_code == 400
    assert not path.exists()


def test_authorization_is_rechecked_under_acceptance_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "B52-001" / "telemetry.latest.json"
    credential = token("A")
    establish_baseline(path, fleet_identity="B52-001", authorization_generation=1)
    client = client_for(registry_for(path, credential))
    monkeypatch.setattr("b52_telemetry.app.revalidate_producer", lambda *_args: False)

    response = client.put(
        "/api/telemetry/instances/B52-001/latest",
        content=body(),
        headers=headers(credential, 1),
    )

    assert response.status_code == 401
    assert not path.exists()


def test_producer_authentication_is_engine_bound_and_separate_from_browser(
    tmp_path: Path,
) -> None:
    first_path = tmp_path / "B52-001" / "telemetry.latest.json"
    second_path = tmp_path / "B52-002" / "telemetry.latest.json"
    first_token = token("A")
    second_token = token("B")
    establish_baseline(first_path, fleet_identity="B52-001", authorization_generation=1)
    establish_baseline(
        second_path, fleet_identity="B52-002", authorization_generation=1
    )
    registry = TelemetrySourceRegistry(
        {
            B52InstanceId("B52-001"): registration(first_path, first_token),
            B52InstanceId("B52-002"): registration(second_path, second_token),
        }
    )
    client = client_for(registry)

    wrong_engine = client.put(
        "/api/telemetry/instances/B52-002/latest",
        content=body(),
        headers=headers(first_token, 1),
    )
    unknown_engine = client.put(
        "/api/telemetry/instances/B52-999/latest",
        content=body(),
        headers=headers(first_token, 1),
    )
    cookie_only = client.put(
        "/api/telemetry/instances/B52-001/latest",
        content=body(),
        headers={
            "Content-Type": "application/json",
            "X-B52-Transport-Sequence": "1",
            "Cookie": "b52_telemetry_session=browser-session",
        },
    )
    browser_get = client.get(
        "/api/telemetry/instances/B52-001/latest",
        headers={"Authorization": f"Bearer {first_token}"},
    )

    assert wrong_engine.status_code == 401
    assert unknown_engine.status_code == 401
    assert cookie_only.status_code == 401
    assert browser_get.status_code == 403
    assert wrong_engine.json() == unknown_engine.json() == cookie_only.json()


def test_monotonic_ordering_accepts_gaps_and_rejects_old_or_conflicting(
    tmp_path: Path,
) -> None:
    path = tmp_path / "B52-001" / "telemetry.latest.json"
    credential = token("A")
    establish_baseline(path, fleet_identity="B52-001", authorization_generation=1)
    client = client_for(registry_for(path, credential))
    first = body(payload("2026-10-29T00:00:01+00:00"))
    newer = body(payload("2026-10-29T00:00:02+00:00"))
    conflict = body(payload("2026-10-29T00:00:03+00:00"))

    assert (
        client.put(
            "/api/telemetry/instances/B52-001/latest",
            content=first,
            headers=headers(credential, 10),
        ).status_code
        == 204
    )
    gap = client.put(
        "/api/telemetry/instances/B52-001/latest",
        content=newer,
        headers=headers(credential, 20),
    )
    duplicate = client.put(
        "/api/telemetry/instances/B52-001/latest",
        content=newer,
        headers=headers(credential, 20),
    )
    stale = client.put(
        "/api/telemetry/instances/B52-001/latest",
        content=first,
        headers=headers(credential, 19),
    )
    collision = client.put(
        "/api/telemetry/instances/B52-001/latest",
        content=conflict,
        headers=headers(credential, 20),
    )

    assert gap.status_code == 204
    assert duplicate.status_code == 204
    assert duplicate.headers["x-b52-transport-result"] == "duplicate"
    assert stale.status_code == 409
    assert collision.status_code == 409
    assert path.read_bytes() == newer


@pytest.mark.parametrize(
    "sequence",
    ["0", "01", "+1", "-1", " 1", "1 ", "1.0", str(2**63), "9" * 5000],
)
def test_sequence_syntax_and_bounds_are_strict(
    tmp_path: Path,
    sequence: str,
) -> None:
    path = tmp_path / "B52-001" / "telemetry.latest.json"
    credential = token("A")
    establish_baseline(path, fleet_identity="B52-001", authorization_generation=1)
    response = client_for(registry_for(path, credential)).put(
        "/api/telemetry/instances/B52-001/latest",
        content=body(),
        headers=headers(credential, sequence),
    )
    assert response.status_code == 400


def test_maximum_transport_sequence_is_permitted(tmp_path: Path) -> None:
    path = tmp_path / "B52-001" / "telemetry.latest.json"
    credential = token("A")
    establish_baseline(path, fleet_identity="B52-001", authorization_generation=1)
    response = client_for(registry_for(path, credential)).put(
        "/api/telemetry/instances/B52-001/latest",
        content=body(),
        headers=headers(credential, 2**63 - 1),
    )
    assert response.status_code == 204


def test_request_size_is_bounded_before_json_processing(tmp_path: Path) -> None:
    path = tmp_path / "B52-001" / "telemetry.latest.json"
    credential = token("A")
    establish_baseline(path, fleet_identity="B52-001", authorization_generation=1)
    response = client_for(registry_for(path, credential)).put(
        "/api/telemetry/instances/B52-001/latest",
        content=b"x" * 1_048_577,
        headers=headers(credential, 1),
    )
    assert response.status_code == 413


def test_concurrent_requests_serialize_and_highest_sequence_wins(
    tmp_path: Path,
) -> None:
    path = tmp_path / "B52-001" / "telemetry.latest.json"
    credential = token("A")
    establish_baseline(path, fleet_identity="B52-001", authorization_generation=1)
    client = client_for(registry_for(path, credential))
    tenth = body(payload("2026-10-29T00:00:10+00:00"))
    twentieth = body(payload("2026-10-29T00:00:20+00:00"))

    def submit(sequence: int, request_body: bytes) -> int:
        return int(
            client.put(
                "/api/telemetry/instances/B52-001/latest",
                content=request_body,
                headers=headers(credential, sequence),
            ).status_code
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = set(
            executor.map(
                lambda arguments: submit(*arguments),
                [(10, tenth), (20, twentieth)],
            )
        )

    assert statuses <= {204, 409}
    assert 204 in statuses
    accepted = read_accepted_snapshot(
        path,
        fleet_identity="B52-001",
        authorization_generation=1,
    )
    assert accepted is not None
    assert accepted.metadata.sequence == 20
    assert accepted.body == twentieth


@pytest.mark.parametrize("xattr", [SNAPSHOT_XATTR, CONTROL_XATTR])
def test_missing_or_corrupt_transport_metadata_fails_closed(
    tmp_path: Path,
    xattr: str,
) -> None:
    path = tmp_path / "B52-001" / "telemetry.latest.json"
    credential = token("A")
    establish_baseline(path, fleet_identity="B52-001", authorization_generation=1)
    client = client_for(registry_for(path, credential))
    assert (
        client.put(
            "/api/telemetry/instances/B52-001/latest",
            content=body(),
            headers=headers(credential, 1),
        ).status_code
        == 204
    )
    target: Path = path if xattr == SNAPSHOT_XATTR else path.parent
    os.removexattr(target, xattr)

    assert (
        client.put(
            "/api/telemetry/instances/B52-001/latest",
            content=body(),
            headers=headers(credential, 2),
        ).status_code
        == 503
    )
    assert client.get("/api/public/instances/B52-001/snapshot").status_code == 503


def test_rotation_preserves_hwm_and_revokes_old_credential(tmp_path: Path) -> None:
    path = tmp_path / "B52-001" / "telemetry.latest.json"
    old_token = token("A")
    new_token = token("B")
    establish_baseline(path, fleet_identity="B52-001", authorization_generation=1)
    old_client = client_for(registry_for(path, old_token))
    assert (
        old_client.put(
            "/api/telemetry/instances/B52-001/latest",
            content=body(),
            headers=headers(old_token, 50),
        ).status_code
        == 204
    )

    update_current_authorization_generation(
        path,
        fleet_identity="B52-001",
        previous_generation=1,
        authorization_generation=2,
    )
    new_client = client_for(registry_for(path, new_token, generation=2))
    assert (
        new_client.put(
            "/api/telemetry/instances/B52-001/latest",
            content=body(),
            headers=headers(old_token, 51),
        ).status_code
        == 401
    )
    assert (
        new_client.put(
            "/api/telemetry/instances/B52-001/latest",
            content=body(payload("2026-10-29T01:00:00+00:00")),
            headers=headers(new_token, 60),
        ).status_code
        == 204
    )

    accepted = read_accepted_snapshot(
        path,
        fleet_identity="B52-001",
        authorization_generation=2,
    )
    assert accepted is not None
    assert accepted.metadata.sequence == 60
    assert accepted.metadata.authorization_generation == 2


def test_revocation_and_authorized_reset(tmp_path: Path) -> None:
    path = tmp_path / "B52-001" / "telemetry.latest.json"
    first_token = token("A")
    second_token = token("B")
    establish_baseline(path, fleet_identity="B52-001", authorization_generation=1)
    first_client = client_for(registry_for(path, first_token))
    assert (
        first_client.put(
            "/api/telemetry/instances/B52-001/latest",
            content=body(),
            headers=headers(first_token, 100),
        ).status_code
        == 204
    )

    reset_ordering_baseline(
        path,
        fleet_identity="B52-001",
        previous_generation=1,
        authorization_generation=2,
    )
    revoked = client_for(registry_for(path, second_token, generation=2, enabled=False))
    assert (
        revoked.put(
            "/api/telemetry/instances/B52-001/latest",
            content=body(),
            headers=headers(second_token, 1),
        ).status_code
        == 401
    )

    reset_client = client_for(registry_for(path, second_token, generation=2))
    assert (
        reset_client.put(
            "/api/telemetry/instances/B52-001/latest",
            content=body(),
            headers=headers(second_token, 1),
        ).status_code
        == 204
    )


def test_failed_atomic_replace_preserves_previous_complete_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "B52-001" / "telemetry.latest.json"
    establish_baseline(path, fleet_identity="B52-001", authorization_generation=1)
    original = body()
    accept_snapshot(
        path,
        fleet_identity="B52-001",
        authorization_generation=1,
        sequence=1,
        body=original,
    )

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(TransportCommitFailed):
        accept_snapshot(
            path,
            fleet_identity="B52-001",
            authorization_generation=1,
            sequence=2,
            body=body(payload("2026-10-29T02:00:00+00:00")),
        )
    assert path.read_bytes() == original


def test_six_engines_have_independent_credentials_sequences_and_failures(
    tmp_path: Path,
) -> None:
    registrations: dict[B52InstanceId, TelemetrySourceRegistration] = {}
    tokens: dict[str, str] = {}
    paths: dict[str, Path] = {}
    for index in range(1, 7):
        identity = f"B52-{index:03d}"
        credential = token(chr(64 + index))
        path = tmp_path / identity / "telemetry.latest.json"
        establish_baseline(path, fleet_identity=identity, authorization_generation=1)
        registrations[B52InstanceId(identity)] = registration(path, credential)
        tokens[identity] = credential
        paths[identity] = path
    client = client_for(TelemetrySourceRegistry(registrations))

    for index, identity in enumerate(tokens, start=1):
        response = client.put(
            f"/api/telemetry/instances/{identity}/latest",
            content=body(payload(f"2026-10-29T00:00:{index:02d}+00:00")),
            headers=headers(tokens[identity], index * 10),
        )
        assert response.status_code == 204

    os.removexattr(paths["B52-003"], SNAPSHOT_XATTR)
    assert client.get("/api/public/instances/B52-003/snapshot").status_code == 503
    assert client.get("/api/public/instances/B52-004/snapshot").status_code == 200
    assert (
        client.put(
            "/api/telemetry/instances/B52-006/latest",
            content=body(),
            headers=headers(tokens["B52-001"], 100),
        ).status_code
        == 401
    )


def test_transport_freshness_is_separate_from_canonical_generated_at(
    tmp_path: Path,
) -> None:
    path = tmp_path / "B52-001" / "telemetry.latest.json"
    establish_baseline(path, fleet_identity="B52-001", authorization_generation=1)
    old_canonical_time = "2020-01-01T00:00:00+00:00"
    accept_snapshot(
        path,
        fleet_identity="B52-001",
        authorization_generation=1,
        sequence=1,
        body=body(payload(old_canonical_time)),
    )
    accepted = read_accepted_snapshot(
        path,
        fleet_identity="B52-001",
        authorization_generation=1,
    )
    assert accepted is not None
    assert accepted.payload["generated_at"] == old_canonical_time
    assert not accepted.metadata.accepted_at.startswith("2020-")
