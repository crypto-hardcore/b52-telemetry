from __future__ import annotations

import json
from pathlib import Path

import pytest

from b52_telemetry.contract import TELEMETRY_SCHEMA_VERSION
from b52_telemetry.source import (
    TelemetryFileSource,
    TelemetrySourceInvalid,
    TelemetrySourceUnavailable,
)


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


def test_reads_supported_canonical_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.latest.json"
    payload = canonical_payload()
    write_payload(path, payload)

    result = TelemetryFileSource(path).read()

    assert result == payload


def test_preserves_unknown_b52_fields(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.latest.json"
    payload = canonical_payload()
    payload["future_b52_field"] = {
        "owned_by": "B-52",
        "value": "authoritative",
    }
    write_payload(path, payload)

    result = TelemetryFileSource(path).read()

    assert result["future_b52_field"] == {
        "owned_by": "B-52",
        "value": "authoritative",
    }


def test_missing_source_is_unavailable(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.latest.json"

    with pytest.raises(
        TelemetrySourceUnavailable,
        match="telemetry source unavailable",
    ):
        TelemetryFileSource(path).read()


def test_filesystem_read_failure_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "telemetry.latest.json"
    path.write_text("{}", encoding="utf-8")

    def fail_read_text(
        self: Path,
        *,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> str:
        raise OSError("read unavailable")

    monkeypatch.setattr(Path, "read_text", fail_read_text)

    with pytest.raises(
        TelemetrySourceUnavailable,
        match="telemetry source unavailable",
    ):
        TelemetryFileSource(path).read()


def test_invalid_json_is_invalid_source(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.latest.json"
    path.write_text('{"schema_version":3', encoding="utf-8")

    with pytest.raises(
        TelemetrySourceInvalid,
        match="telemetry source contains invalid JSON",
    ):
        TelemetryFileSource(path).read()


def test_unsupported_schema_is_invalid_source(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.latest.json"
    payload = canonical_payload()
    payload["schema_version"] = 2
    write_payload(path, payload)

    with pytest.raises(
        TelemetrySourceInvalid,
        match="telemetry source contains an invalid canonical snapshot",
    ) as exc_info:
        TelemetryFileSource(path).read()

    assert exc_info.value.__cause__ is not None


def test_invalid_canonical_envelope_is_invalid_source(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.latest.json"
    payload = canonical_payload()
    payload["system"] = None
    write_payload(path, payload)

    with pytest.raises(
        TelemetrySourceInvalid,
        match="telemetry source contains an invalid canonical snapshot",
    ):
        TelemetryFileSource(path).read()


def test_old_snapshot_is_still_valid_at_source_boundary(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.latest.json"
    payload = canonical_payload()
    payload["generated_at"] = "2025-01-01T00:00:00+00:00"
    write_payload(path, payload)

    result = TelemetryFileSource(path).read()

    assert result["generated_at"] == "2025-01-01T00:00:00+00:00"
