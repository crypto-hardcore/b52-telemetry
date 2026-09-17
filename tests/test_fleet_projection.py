from __future__ import annotations

import json
from pathlib import Path

from b52_telemetry.contract import TELEMETRY_SCHEMA_VERSION
from b52_telemetry.fleet_projection import project_fleet
from b52_telemetry.source_registry import B52InstanceId, TelemetrySourceRegistry


def canonical_payload(
    generated_at: str = "2026-09-17T00:00:00+00:00",
) -> dict[str, object]:
    return {
        "schema_version": TELEMETRY_SCHEMA_VERSION,
        "generated_at": generated_at,
        "system": {
            "https": {
                "state": "HEALTHY",
                "observed_at": generated_at,
            }
        },
        "market": {
            "symbol": "BTCUSDC",
            "price": "79508.10",
            "observed_at": generated_at,
        },
        "mission": None,
    }


def write_payload(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, separators=(",", ":")),
        encoding="utf-8",
    )


def test_projects_single_available_instance_without_reinterpreting_payload(
    tmp_path: Path,
) -> None:
    path = tmp_path / "B52-001.json"
    payload = canonical_payload()
    payload["future_b52_field"] = {
        "owned_by": "B-52",
        "value": "authoritative",
    }
    write_payload(path, payload)

    registry = TelemetrySourceRegistry(
        {
            B52InstanceId("B52-001"): path,
        }
    )

    assert project_fleet(registry) == {
        "instances": [
            {
                "instance_id": "B52-001",
                "source_state": "AVAILABLE",
                "telemetry": payload,
            }
        ]
    }


def test_projects_multiple_instances_in_registry_order(
    tmp_path: Path,
) -> None:
    first_path = tmp_path / "B52-003.json"
    second_path = tmp_path / "B52-001.json"

    first_payload = canonical_payload("2026-09-17T00:00:01+00:00")
    second_payload = canonical_payload("2026-09-17T00:00:02+00:00")

    write_payload(first_path, first_payload)
    write_payload(second_path, second_payload)

    registry = TelemetrySourceRegistry(
        {
            B52InstanceId("B52-003"): first_path,
            B52InstanceId("B52-001"): second_path,
        }
    )

    projection = project_fleet(registry)

    assert [member["instance_id"] for member in projection["instances"]] == [
        "B52-003",
        "B52-001",
    ]
    assert projection["instances"][0]["telemetry"] == first_payload
    assert projection["instances"][1]["telemetry"] == second_payload


def test_unavailable_instance_does_not_suppress_available_peers(
    tmp_path: Path,
) -> None:
    first_path = tmp_path / "B52-001.json"
    missing_path = tmp_path / "B52-002.json"
    third_path = tmp_path / "B52-003.json"

    first_payload = canonical_payload("2026-09-17T00:00:01+00:00")
    third_payload = canonical_payload("2026-09-17T00:00:03+00:00")

    write_payload(first_path, first_payload)
    write_payload(third_path, third_payload)

    registry = TelemetrySourceRegistry(
        {
            B52InstanceId("B52-001"): first_path,
            B52InstanceId("B52-002"): missing_path,
            B52InstanceId("B52-003"): third_path,
        }
    )

    projection = project_fleet(registry)

    assert projection == {
        "instances": [
            {
                "instance_id": "B52-001",
                "source_state": "AVAILABLE",
                "telemetry": first_payload,
            },
            {
                "instance_id": "B52-002",
                "source_state": "UNAVAILABLE",
                "telemetry": None,
            },
            {
                "instance_id": "B52-003",
                "source_state": "AVAILABLE",
                "telemetry": third_payload,
            },
        ]
    }


def test_invalid_instance_does_not_suppress_available_peers(
    tmp_path: Path,
) -> None:
    first_path = tmp_path / "B52-001.json"
    invalid_path = tmp_path / "B52-002.json"
    third_path = tmp_path / "B52-003.json"

    first_payload = canonical_payload("2026-09-17T00:00:01+00:00")
    third_payload = canonical_payload("2026-09-17T00:00:03+00:00")

    write_payload(first_path, first_payload)
    invalid_path.write_text('{"schema_version":3', encoding="utf-8")
    write_payload(third_path, third_payload)

    registry = TelemetrySourceRegistry(
        {
            B52InstanceId("B52-001"): first_path,
            B52InstanceId("B52-002"): invalid_path,
            B52InstanceId("B52-003"): third_path,
        }
    )

    projection = project_fleet(registry)

    assert projection == {
        "instances": [
            {
                "instance_id": "B52-001",
                "source_state": "AVAILABLE",
                "telemetry": first_payload,
            },
            {
                "instance_id": "B52-002",
                "source_state": "INVALID",
                "telemetry": None,
            },
            {
                "instance_id": "B52-003",
                "source_state": "AVAILABLE",
                "telemetry": third_payload,
            },
        ]
    }


def test_invalid_canonical_snapshot_is_reported_as_invalid(
    tmp_path: Path,
) -> None:
    path = tmp_path / "B52-001.json"
    payload = canonical_payload()
    payload["schema_version"] = 2
    write_payload(path, payload)

    registry = TelemetrySourceRegistry(
        {
            B52InstanceId("B52-001"): path,
        }
    )

    assert project_fleet(registry) == {
        "instances": [
            {
                "instance_id": "B52-001",
                "source_state": "INVALID",
                "telemetry": None,
            }
        ]
    }
