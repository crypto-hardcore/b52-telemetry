from __future__ import annotations

import pytest

from b52_telemetry.contract import (
    TELEMETRY_SCHEMA_VERSION,
    TelemetryContractError,
    validate_telemetry_payload,
)


def canonical_payload() -> dict[str, object]:
    return {
        "schema_version": TELEMETRY_SCHEMA_VERSION,
        "generated_at": "2026-09-05T10:45:02+00:00",
        "system": {
            "https": {
                "state": "HEALTHY",
                "observed_at": "2026-09-05T10:45:02+00:00",
            },
            "websocket": {
                "state": "HEALTHY",
                "observed_at": "2026-09-05T10:45:02+00:00",
            },
            "authentication": {
                "state": "HEALTHY",
                "observed_at": "2026-09-05T10:45:02+00:00",
            },
            "stream_freshness": {
                "state": "HEALTHY",
                "observed_at": "2026-09-05T10:45:02+00:00",
            },
            "evidence_continuity": {
                "state": "HEALTHY",
                "observed_at": "2026-09-05T10:45:02+00:00",
            },
            "sqlite": {
                "state": "HEALTHY",
                "observed_at": "2026-09-05T10:45:02+00:00",
            },
            "reconciliation": {
                "state": "HEALTHY",
                "observed_at": "2026-09-05T10:45:02+00:00",
            },
        },
        "market": {
            "symbol": "BTCUSDC",
            "price": "79508.10",
            "observed_at": "2026-09-05T10:45:02+00:00",
        },
        "mission": None,
    }


def test_accepts_supported_canonical_snapshot() -> None:
    payload = canonical_payload()

    result = validate_telemetry_payload(payload)

    assert result is payload


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("generated_at", None, "generated_at must be a non-empty string"),
        ("system", None, "system must be a JSON object"),
        ("market", "BTCUSDC", "market must be a JSON object or null"),
        ("mission", "ACTIVE", "mission must be a JSON object or null"),
    ],
)
def test_rejects_invalid_canonical_envelope_fields(
    field: str,
    value: object,
    message: str,
) -> None:
    payload = canonical_payload()
    payload[field] = value

    with pytest.raises(TelemetryContractError, match=message):
        validate_telemetry_payload(payload)


def test_rejects_non_object_payload() -> None:
    with pytest.raises(
        TelemetryContractError,
        match="telemetry payload must be a JSON object",
    ):
        validate_telemetry_payload([])


def test_rejects_unsupported_schema_version() -> None:
    payload = canonical_payload()
    payload["schema_version"] = 2

    with pytest.raises(
        TelemetryContractError,
        match="unsupported telemetry schema version",
    ):
        validate_telemetry_payload(payload)


def test_does_not_reject_unknown_fields_from_b52() -> None:
    payload = canonical_payload()
    payload["future_b52_field"] = {"owned_by": "B-52"}

    result = validate_telemetry_payload(payload)

    assert result["future_b52_field"] == {"owned_by": "B-52"}
