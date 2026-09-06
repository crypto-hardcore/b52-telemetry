from __future__ import annotations

from b52_telemetry.contract import TelemetryPayload
from b52_telemetry.public_projection import project_public_telemetry


def test_projects_only_approved_public_fields() -> None:
    telemetry: TelemetryPayload = {
        "schema_version": 3,
        "generated_at": "2026-09-06T00:15:02+00:00",
        "system": {
            "authentication": {
                "state": "HEALTHY",
                "observed_at": "2026-09-06T00:15:02+00:00",
            },
        },
        "market": {
            "symbol": "BTCUSDC",
            "price": "79508.10",
            "observed_at": "2026-09-06T00:15:02+00:00",
        },
        "mission": {
            "lifecycle": {
                "lifecycle_id": "private-lifecycle-id",
                "beginning_wallet_balance": "5000.00",
            },
            "position": {
                "quantity": "0.003",
                "liquidation_price": "50000.00",
            },
        },
        "future_b52_field": {
            "private": "authoritative-but-not-public",
        },
    }

    assert project_public_telemetry(telemetry) == {
        "generated_at": "2026-09-06T00:15:02+00:00",
        "market": {
            "symbol": "BTCUSDC",
            "price": "79508.10",
        },
    }


def test_projects_null_market_without_manufacturing_market_state() -> None:
    telemetry: TelemetryPayload = {
        "schema_version": 3,
        "generated_at": "2026-09-06T00:15:02+00:00",
        "system": {},
        "market": None,
        "mission": None,
    }

    assert project_public_telemetry(telemetry) == {
        "generated_at": "2026-09-06T00:15:02+00:00",
        "market": None,
    }
