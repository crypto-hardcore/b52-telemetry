from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from b52_telemetry.app import create_app
from b52_telemetry.contract import TELEMETRY_SCHEMA_VERSION


def canonical_payload() -> dict[str, object]:
    return {
        "schema_version": TELEMETRY_SCHEMA_VERSION,
        "generated_at": "2026-09-06T00:15:02+00:00",
        "system": {
            "https": {
                "state": "HEALTHY",
                "observed_at": "2026-09-06T00:15:02+00:00",
            },
            "websocket": {
                "state": "HEALTHY",
                "observed_at": "2026-09-06T00:15:02+00:00",
            },
            "authentication": {
                "state": "HEALTHY",
                "observed_at": "2026-09-06T00:15:02+00:00",
            },
            "stream_freshness": {
                "state": "HEALTHY",
                "observed_at": "2026-09-06T00:15:02+00:00",
            },
            "evidence_continuity": {
                "state": "HEALTHY",
                "observed_at": "2026-09-06T00:15:02+00:00",
            },
            "sqlite": {
                "state": "HEALTHY",
                "observed_at": "2026-09-06T00:15:02+00:00",
            },
            "reconciliation": {
                "state": "HEALTHY",
                "observed_at": "2026-09-06T00:15:02+00:00",
            },
        },
        "market": {
            "symbol": "BTCUSDC",
            "price": "79508.10",
            "observed_at": "2026-09-06T00:15:02+00:00",
        },
        "mission": None,
    }


def write_payload(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, separators=(",", ":")),
        encoding="utf-8",
    )


def test_latest_returns_canonical_payload_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.latest.json"
    payload = canonical_payload()
    payload["future_b52_field"] = {
        "owned_by": "B-52",
        "value": "authoritative",
    }
    write_payload(path, payload)

    client = TestClient(create_app(path))

    response = client.get("/api/telemetry/latest")

    assert response.status_code == 200
    assert response.json() == payload


def test_latest_returns_503_when_source_is_unavailable(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.latest.json"
    client = TestClient(create_app(path))

    response = client.get("/api/telemetry/latest")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "telemetry source unavailable",
    }


def test_latest_returns_503_when_source_contains_invalid_json(
    tmp_path: Path,
) -> None:
    path = tmp_path / "telemetry.latest.json"
    path.write_text('{"schema_version":3', encoding="utf-8")
    client = TestClient(create_app(path))

    response = client.get("/api/telemetry/latest")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "telemetry source invalid",
    }


def test_latest_returns_503_for_unsupported_schema(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.latest.json"
    payload = canonical_payload()
    payload["schema_version"] = 2
    write_payload(path, payload)
    client = TestClient(create_app(path))

    response = client.get("/api/telemetry/latest")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "telemetry source invalid",
    }


def test_latest_does_not_reject_old_canonical_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.latest.json"
    payload = canonical_payload()
    payload["generated_at"] = "2025-01-01T00:00:00+00:00"
    write_payload(path, payload)
    client = TestClient(create_app(path))

    response = client.get("/api/telemetry/latest")

    assert response.status_code == 200
    assert response.json()["generated_at"] == "2025-01-01T00:00:00+00:00"
